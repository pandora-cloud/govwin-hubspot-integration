# Architecture Overview

## System Context

This integration sits between two external APIs and orchestrates data flow on AWS.

![Architecture Diagram](diagrams/architecture.svg)

The pipeline flows from GovWin IQ through this integration into HubSpot CRM, and onward to AWS Partner Central via the integration's own AWS Partner Central Selling API client (the SaaSify ACE Connector is no longer required).

![Pipeline Overview](diagrams/pipeline-overview.svg)

## Step Function Workflow

The sync runs as a Step Function state machine triggered by EventBridge on a configurable schedule (default: every 4 hours).

### States

```
Start
  |
  v
[Authenticate] ── Get/refresh GovWin OAuth token from Secrets Manager
  |
  v
[Discover Changes] ── Fetch opportunities to sync (mode-dependent):
  |                    - Default: get opps marked for "Web Services Download"
  |                    - Alternative: date-range search with saved search/bookmark filter
  |                    Paginate through results (max 100/page)
  |                    Compare updateDate against stored values (timezone-aware)
  |                    Return list of opportunity IDs needing sync
  |
  v
[Check For Changes] ── Choice state: if no changes, skip to end
  |
  v
[Process Opportunities] ── Map state (maxConcurrency=2)
  |   |
  |   +-- [Fetch Details] ── For each opportunity batch:
  |   |     GET summary + contacts + companies + contracts
  |   |     Rate-limit aware (Wait states if approaching 4,000/hr)
  |   |
  |   +-- [Sync to HubSpot] ── Batch upsert deals, companies, contacts
  |         Create associations (Deal<->Company, Deal<->Contact)
  |         Use idProperty for deduplication
  |
  v
[Update Sync State] ── Write last_sync timestamp to DynamoDB
  |                     Update per-opportunity updateDate records
  |                     Update GovWin<->HubSpot ID mappings
  |
  v
[Send Summary] ── SNS notification with sync statistics
  |
  v
End

On any error:
  [Handle Error] ── Log to CloudWatch, send SNS alert
                    Write failed items to SQS dead letter queue
```

## Lambda Functions

| Function | Purpose | Trigger | Timeout | Memory |
|---|---|---|---|---|
| `authenticate` | Get/refresh GovWin OAuth token | Step Function | 30s | 128 MB |
| `discover_changes` | Search for updated opportunities | Step Function | 5 min | 256 MB |
| `fetch_opp_details` | Fetch full opportunity data for a batch | Step Function | 5 min | 256 MB |
| `sync_to_hubspot` | Push data to HubSpot via batch APIs | Step Function | 5 min | 256 MB |
| `update_sync_state` | Persist sync state to DynamoDB | Step Function | 30s | 128 MB |
| `setup_hubspot` | One-time: create custom properties and pipeline | Manual / deploy | 2 min | 128 MB |
| `handle_error` | Error notification and DLQ management | Step Function | 30s | 128 MB |
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
- Step Function Map state `maxConcurrency=2` controls parallelism
- Built-in Wait states pause when approaching the limit

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
