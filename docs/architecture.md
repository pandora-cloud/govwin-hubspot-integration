# Architecture Overview

## System Context

This integration sits between two external APIs and orchestrates data flow on AWS:

```
                    +-------------------+
                    |   Deltek GovWin   |
                    |    WSAPI V3       |
                    +--------+----------+
                             |
                    OAuth2 + REST/JSON
                             |
                             v
+---------------------------------------------------+
|                    AWS Cloud                       |
|                                                    |
|  EventBridge ──> Step Functions ──> Lambda (x7)   |
|                       |                            |
|                       v                            |
|                   DynamoDB                         |
|              (sync state + mappings)               |
|                                                    |
|  Secrets Manager    SNS (alerts)    SQS (DLQ)     |
+---------------------------------------------------+
                             |
                    REST/JSON + Bearer token
                             |
                             v
                    +-------------------+
                    |   HubSpot CRM     |
                    |   (Deals, etc.)   |
                    +--------+----------+
                             |
                    SaaSify ACE Connector (existing)
                             |
                             v
                    +-------------------+
                    | AWS Partner       |
                    | Central (ACE)     |
                    +-------------------+
```

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

| Function | Purpose | Timeout | Memory |
|---|---|---|---|
| `authenticate` | Get/refresh GovWin OAuth token | 30s | 128 MB |
| `discover_changes` | Search for updated opportunities | 5 min | 256 MB |
| `fetch_opp_details` | Fetch full opportunity data for a batch | 5 min | 256 MB |
| `sync_to_hubspot` | Push data to HubSpot via batch APIs | 5 min | 256 MB |
| `update_sync_state` | Persist sync state to DynamoDB | 30s | 128 MB |
| `setup_hubspot` | One-time: create custom properties and pipeline | 2 min | 128 MB |
| `handle_error` | Error notification and DLQ management | 30s | 128 MB |

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

Maps GovWin entities to HubSpot objects.

| Key | Type | Description |
|---|---|---|
| `pk` | String | `GOVENTITY#{id}`, `CONTACT#{id}`, or `COMPANY#{id}` |
| `sk` | String | `HUBSPOT_MAPPING` |
| `hubspot_id` | String | Corresponding HubSpot object ID |
| `last_synced` | String | ISO-8601 datetime of last sync |

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

## Security

- All credentials stored in AWS Secrets Manager (never in Lambda env vars as plaintext)
- Lambda execution roles follow least-privilege principle
- GovWin OAuth tokens cached in Secrets Manager, refreshed before expiry
- No VPC required (external API calls only)
- Secret detection enabled in CI/CD pipeline
