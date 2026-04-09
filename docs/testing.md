# Testing Guide

## Local Testing

### Unit Tests

92 unit tests covering all modules. Run with:

```bash
make test
```

### Pre-deployment Validation

Test API credentials and connectivity before deploying:

```bash
cp .env.example .env
# Fill in your credentials
make validate
```

### Dry Run

Preview what would sync without writing to HubSpot:

```bash
make dry-run
```

### LocalStack (Docker)

Run tests against real AWS services locally:

```bash
make local-up       # Start LocalStack
make local-test     # Run tests against it
make local-down     # Clean up
```

---

## Production Test Results

Tested against live GovWin and HubSpot APIs on 2026-04-08.

### Sync Tests

| # | Test | Result | Notes |
|---|---|---|---|
| 1 | GovWin OAuth2 authentication | PASS | Token obtained, 12hr expiry |
| 2 | Marked-for-sync discovery | PASS | 8 marked opps found via markedVersion=2.2 |
| 3 | OPP opportunity type | PASS | 5 tracked opps synced |
| 4 | OPN opportunity type | PASS | 2 APFS procurement notices synced |
| 5 | Federal agencies (DHS, GSA, DOD, HHS, DOE) | PASS | All created as HubSpot companies |
| 6 | State/local agencies (CA, MN) | PASS | SLED opps handled correctly |
| 7 | Pre-RFP status | PASS | Mapped to "Opportunity Identified" stage |
| 8 | Source Selection status | PASS | Mapped to "Submitted" stage |
| 9 | Forecast Pre-RFP status | PASS | Mapped to "Opportunity Identified" stage |
| 10 | $0 value deals | PASS | Amount field empty, no errors |
| 11 | Large value deals ($178M) | PASS | Correct dollar conversion |
| 12 | Deal-to-company associations | PASS | All deals linked to their agency |
| 13 | Deal-to-contact associations | PASS | 18 associations created across 8 deals |
| 14 | HubSpot custom properties | PASS | 30 deal, 5 company, 3 contact properties |
| 15 | Government pipeline stage mapping | PASS | Existing "Government" pipeline used |

### Dedup and Incremental Sync

| # | Test | Result | Notes |
|---|---|---|---|
| 16 | Incremental skip (no changes) | PASS | 0 opps synced, 1 API call |
| 17 | Repeat incremental skip | PASS | Confirmed idempotent on second run |
| 18 | Company dedup across opps | PASS | 3 GSA opps share 1 company record |
| 19 | Contact dedup across opps | PASS | 10 unique contacts, 0 duplicates |

### Infrastructure

| # | Test | Result | Notes |
|---|---|---|---|
| 20 | EventBridge schedule | PASS | rate(4 hours), ENABLED |
| 21 | SNS notifications | PASS | Email subscription confirmed |
| 22 | SQS dead letter queue | PASS | 0 messages (no unhandled errors) |
| 23 | 10 consecutive executions | PASS | All SUCCEEDED |
| 24 | API call efficiency | PASS | 1 call for "no changes" check |
| 25 | ARM64 (Graviton2) Lambda | PASS | All 7 functions on arm64 |

### Data Model Fixes from Live Testing

These issues were found and fixed during production testing with real GovWin data:

| Issue | Fix |
|---|---|
| `smartTag` returned as string for OPN type | Model accepts `list[dict] \| str` |
| `links.contacts` returned as dict `{"href":"..."}` | Model accepts `dict \| str` |
| `contactId` returned as integer | Model accepts `str \| int` |
| `contract.company` returned as list of dicts | Model accepts `dict \| list[dict]` |
| `contract.incumbent` returned as string | Model accepts `bool \| str` |
| HubSpot `industry` field requires enum value | Changed `"Government"` to `"GOVERNMENT_ADMINISTRATION"` |
| HubSpot date fields require epoch milliseconds | Added `_to_hubspot_timestamp()` converter |
| `hasUniqueValue` can't be set on existing properties | Created new `govwin_id` and `govwin_entity_id` dedup keys |
| Contact association lookup used email instead of contact_id | Fixed to use `contact_id` matching DynamoDB mappings |
