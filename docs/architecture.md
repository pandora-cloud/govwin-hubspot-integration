# Architecture Overview

## System Context

This integration sits between three external APIs and orchestrates data flow on AWS. The pipeline runs end-to-end from GovWin IQ into HubSpot CRM and onward to AWS Partner Central via the integration's own Partner Central Selling API client. SaaSify is no longer required.

![Pipeline Overview](diagrams/pipeline-overview.svg)

### GovWin to HubSpot (v2.1)

EventBridge Scheduler invokes the orchestrator Lambda on a configurable cadence (default: hourly). The orchestrator refreshes the GovWin OAuth token, runs discovery, filters by `updateDate`, batches the changed opportunities, and fans them out as SQS messages. The worker Lambda drains the queue, fetches each opportunity bundle from GovWin, and pushes deals/companies/contacts/associations to HubSpot. Worker concurrency is governed by Lambda `reservedConcurrentExecutions` (default 2, sized for the GovWin 4,000 calls/hour budget).

The v2.0 Step Function chain (Authenticate → DiscoverChanges → Map(FetchDetails + SyncToHubSpot) → UpdateSyncState) is gone. Replacing the Map state with SQS removes the 256KB inter-state payload limit and lets each opportunity batch retry independently.

![GovWin to HubSpot architecture](diagrams/architecture.svg)

### HubSpot to AWS Partner Central

When a HubSpot deal moves to **Submit to AWS**, the webhook receiver enqueues the event onto SQS, the submit Lambda runs the three-call Selling-API flow, and EventBridge events from `aws.partnercentral-selling` flow back to update the HubSpot deal stage.

![HubSpot to AWS Partner Central architecture](diagrams/architecture-v2-ace.svg)

## Sync Flow

```
EventBridge Scheduler (rate(1 hour))
  |
  v
[govwin_orchestrator Lambda]
  |  - Refresh GovWin OAuth token (Secrets Manager)
  |  - Discover opportunities (marked / saved-search / bookmarked / date-range)
  |  - filter_changed_opportunities() against DynamoDB cursor
  |  - Batch into BATCH_SIZE-sized chunks
  |  - In date-range mode: advance the SYNC_CURSOR row inline
  |
  +--> SQS govwin-sync queue (one message per batch)
              |
              v
       [govwin_worker Lambda] (reservedConcurrency = MAX_CONCURRENCY)
         - Fetch opportunity bundle for each id (rate-limited)
         - SyncOrchestrator.sync_opportunity_batch(): batch upsert
           companies, contacts, deals; create associations
         - Per-opportunity updateDate persisted as the sync proceeds
         - Permanent errors: SNS alert + drop. Transient (rate limit,
           HubSpot 5xx): batchItemFailures so SQS redelivers.
              |
              v
       Failed messages -> govwin-sync-dlq (after 3 receives)
```

## Lambda Functions

| Function | Purpose | Trigger | Timeout | Memory |
|---|---|---|---|---|
| `govwin_orchestrator` | Discovery, OAuth refresh, SQS fan-out, cursor advance | EventBridge Scheduler | 10 min | 512 MB |
| `govwin_worker` | Per-batch fetch + HubSpot sync, partial-batch failure reporting | SQS govwin-sync queue | 5 min | 512 MB |
| `setup_hubspot` | One-time: create custom properties and pipeline | Manual / deploy | 2 min | 128 MB |
| `hubspot_webhook_receiver` | Validate `X-HubSpot-Signature-v3`, route events to SQS | API Gateway HTTP API | 5s | 256 MB |
| `submit_to_ace` | Three-call ACE submission (Create + Associate + StartEngagement) with resume-from-step idempotency | SQS submit queue | 5 min | 512 MB |
| `update_in_ace` | UpdateOpportunity with optimistic locking on `LastModifiedDate` | SQS update queue | 2 min | 256 MB |
| `handle_ace_event` | Mirror EventBridge events from `aws.partnercentral-selling` back to HubSpot deal stage | EventBridge | 1 min | 256 MB |
| `setup_hubspot_webhooks` | One-time: register webhook subscriptions on the HubSpot dev-platform app | Manual / deploy | 1 min | 128 MB |

## DynamoDB Tables

### `govwin_sync_state`

Stores sync cursors and per-opportunity state.

| Key | Type | Description |
|---|---|---|
| `pk` | String | `SYNC_CURSOR` (global) or `OPP#{govwin_id}` |
| `sk` | String | `METADATA` or `MAPPING` |
| `last_sync_timestamp` | String | ISO-8601 datetime of last successful sync |
| `govwin_update_date` | String | Per-opportunity updateDate from GovWin |
| `hubspot_deal_id` | String | HubSpot deal ID for cross-reference |

### `govwin_entity_mappings`

Maps GovWin entities to HubSpot objects, plus ACE-side state.

| pk pattern | sk | Purpose |
|---|---|---|
| `GOVENTITY#{id}` / `CONTACT#{id}` / `COMPANY#{id}` | `HUBSPOT_MAPPING` | GovWin entity to HubSpot object id |
| `ACE#{govwin_id}` | `MAPPING` | AWS opportunity id, ClientToken, engagement task id, last-modified date for optimistic locking |
| `EVT#{event_id}` | `SEEN` | EventBridge dedup record, 24-hour TTL |

Both tables use a 180-day TTL on per-opportunity and entity-mapping records (the `SYNC_CURSOR` row has none). DynamoDB encryption-at-rest with AWS-managed keys is enabled by default.

## Rate Limiting

### GovWin (4,000 calls/hour)

- Rolling 60-minute window across all API users in the organization
- Each opportunity requires ~4 detail calls (contacts, companies, places, contracts)
- Discovery pagination: ~50 calls per 5,000 opportunities
- Maximum throughput: ~975 opportunities per sync cycle
- Worker Lambda `reservedConcurrentExecutions` (default 2) caps parallelism within the org-wide budget
- Built-in token-bucket pause on the GovWin client when approaching the limit; SQS redelivery handles overruns

### HubSpot (100 requests/10 seconds)

- Batch endpoints process up to 100 records per request
- 5,000 deals = 50 batch requests (well within limits)
- Exponential backoff on 429 responses

### AWS Partner Central (1 write/sec, 10 reads/sec)

- Per-account rate limits enforced by a token-bucket limiter (`src/ace/rate_limiter.py`)
- Tenacity retries on `ThrottlingException`, `InternalServerException`, and `ServiceUnavailableException`
- Permanent errors (`ValidationException`, `AccessDeniedException`, `ResourceNotFoundException`) are dropped from the SQS batch instead of looping until DLQ
- HubSpot webhook delivery: 5-second response budget; receiver validates the signature, routes the event to SQS, and returns 200. All ACE API calls happen off the webhook critical path.

## Security

- All credentials stored in AWS Secrets Manager (never in Lambda env vars as plaintext)
- Lambda execution roles follow least-privilege principle
- GovWin OAuth tokens cached in Secrets Manager, refreshed before expiry
- No VPC required (external API calls only)
- Secret detection enabled in CI/CD pipeline
