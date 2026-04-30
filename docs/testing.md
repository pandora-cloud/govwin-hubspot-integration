# Testing Guide

This guide covers everything you need to run the full test suite end to end before deploying or releasing the integration. The suite has four layers:

1. **Hermetic unit tests** (no network, no AWS, no GovWin/HubSpot)
2. **LocalStack integration tests** (real boto3 calls against a containerized AWS)
3. **Pre-deployment validation** (real GovWin/HubSpot/AWS credentials, read-only)
4. **End-to-end production smoke tests** (run by a human against your live deployment)

## 1. Unit Tests (no setup beyond Python)

128 unit tests covering models, mappers, dedup, rate limiters, both API clients, the orchestrator, and every Lambda handler. They mock all I/O and run in seconds.

```bash
make install-dev    # one-time
make test           # runs pytest tests/unit -v
```

You should see `128 passed`. Every supported opportunity type (OPP, BID, TNS, FBO, OPN, TOP) has a parse-and-map regression test, and the production data quirks (`smartTag` as string, `contract.company` as list, `contact_id` as int, etc.) are pinned by `tests/unit/test_models.py`.

## 2. Static Checks

Run these before opening a PR or deploying.

```bash
make lint           # ruff
make typecheck      # mypy with the pydantic plugin enabled
```

Both should report no issues. CI runs them automatically on every push.

## 3. LocalStack Integration Tests

These tests exercise the DynamoDB state manager and Secrets Manager paths against a real boto3 client talking to LocalStack. They auto-skip when `AWS_ENDPOINT_URL` is not set so `make test` stays hermetic.

```bash
make local-up       # docker compose up localstack + create tables/secrets
make local-test     # docker compose run test-runner pytest tests/
make local-down     # tear down
```

Behind the scenes `make local-test` runs `pytest tests/` inside a container with `AWS_ENDPOINT_URL=http://localstack:4566`. You'll see the 6 integration tests in `tests/integration/test_localstack_state.py` go from skipped to passing.

If you want to run them ad-hoc against an already-running LocalStack:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_DEFAULT_REGION=us-east-1
export SYNC_STATE_TABLE=govwin-hubspot-dev-sync-state
export ENTITY_MAPPINGS_TABLE=govwin-hubspot-dev-entity-mappings
export GOVWIN_SECRET_NAME=govwin-hubspot-dev/govwin
export HUBSPOT_SECRET_NAME=govwin-hubspot-dev/hubspot
export GOVWIN_TOKENS_SECRET_NAME=govwin-hubspot-dev/govwin-tokens
pytest tests/integration -v
```

## 4. Pre-deployment Validation (real credentials)

Before deploying to AWS, validate that your credentials actually work and the APIs are reachable. These scripts make real but read-only calls.

```bash
cp .env.example .env
# Fill in GovWin client id/secret/username/password and HubSpot token
make validate
```

`make validate` runs `scripts/validate.py`, which:
- exchanges your GovWin credentials for an OAuth token,
- calls `/opportunities?max=1` to confirm the WSAPI works,
- calls HubSpot `/crm/v3/objects/deals?limit=1` to confirm the token works,
- confirms the configured AWS profile can reach Secrets Manager.

To exercise only one side (handy when you only have one set of credentials at hand):

```bash
python scripts/validate.py --skip-hubspot
python scripts/validate.py --skip-govwin
python scripts/validate.py --skip-govwin --skip-hubspot   # AWS-only
```

## 5. Dry Run

Preview the next sync against real GovWin data without writing anything to HubSpot. The script discovers up to N opportunities, fetches their full details, runs them through the mapper, and prints the resulting payload.

```bash
make dry-run                          # default --limit 5
python scripts/dry_run.py --limit 25  # custom limit
```

Use this after `make validate` and before the first real sync. If a particular opportunity type or field shape would crash the mapper, this is where you'll see it.

## 6. End-to-End Production Smoke Tests

Once deployed, the integration owner (typically your BD lead) should run a one-time smoke pass to confirm the full pipeline works in production. These tests cannot be automated because they require interactive marking/unmarking inside GovWin IQ and visual inspection inside HubSpot.

The recommended matrix:

| # | Scenario | What to do | What to verify |
|---|---|---|---|
| 1 | OPP type | Mark a tracked-opportunity (`OPP*`) for Web Services Download. Trigger sync. | Deal appears in the Government pipeline with NAICS, agency, contacts populated. |
| 2 | BID type | Mark a `BID*` opportunity. Trigger sync. | Deal appears, no validation errors in CloudWatch. |
| 3 | TNS type | Mark a `TNS*` opportunity. Trigger sync. | Deal appears, deal stage maps correctly from GovWin status. |
| 4 | FBO type | Mark a `FBO*` opportunity. Trigger sync. | Deal appears, `govwin_source_url` populated with sam.gov link. |
| 5 | OPN type | Mark an `OPN*` (APFS) opportunity. Trigger sync. | Deal appears, `govwin_smart_tags` populated even when GovWin returns it as a plain string. |
| 6 | TOP type | Mark a `TOP*` (task-order) opportunity. Trigger sync. | Deal appears with task-order specific fields. |
| 7 | Update flow | Edit a previously-synced opp's status in GovWin. Trigger sync. | Same HubSpot deal id is updated; **no duplicate** is created. |
| 8 | Unmark behavior | Unmark a previously-synced opp. Trigger sync. | The HubSpot deal is **retained** untouched (intentional behavior so manual edits survive). |
| 9 | Re-mark | Re-mark the unmarked opp from #8. Trigger sync. | Same deal is updated, no duplicate appears. |
| 10 | DLQ replay | Temporarily revoke a credential, trigger sync, restore. | Failure lands in `*-dlq` SQS queue with sanitized JSON; an alert is sent via SNS; restoring credentials clears the next run. |

Production test results from the original Pandora Cloud rollout are recorded in the table below as a reference for what "passing" looks like.

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

## ACE sandbox smoke matrix

Run before flipping `ace_catalog` from `Sandbox` to `AWS`. Each test is scriptable and self-cleans by archiving the sandbox opportunities afterward.

| # | Scenario | Method |
|---|---|---|
| 1 | `CreateOpportunity` in Sandbox | Direct boto3 call from a script; verify the response contains `Id` and `LastModifiedDate` |
| 2 | `AssociateOpportunity` with the configured Solution | Use the first item from `aws partnercentral-selling list-solutions --catalog Sandbox` |
| 3 | `StartEngagementFromOpportunityTask` | Verify the task transitions IN_PROGRESS -> COMPLETE |
| 4 | `UpdateOpportunity` with optimistic locking | Update twice in sequence; second call uses the fresh `LastModifiedDate` from the first response |
| 5 | `UpdateOpportunity` with stale lock (negative test) | Force a `ConflictException` by passing the previous `LastModifiedDate`; verify our retry logic refetches and succeeds |
| 6 | EventBridge `Opportunity Updated` | Modify the sandbox opp; verify `handle_ace_event` fires and the HubSpot deal stage updates |
| 7 | EventBridge `Engagement Invitation Accepted` | Accept the invitation in sandbox; verify HubSpot stage moves to `approved_by_aws` |
| 8 | EventBridge `Engagement Invitation Rejected` | Reject the invitation; verify HubSpot stage moves to `closedlost` |
| 9 | HubSpot webhook signature validation (positive) | Trigger a real deal-stage change in HubSpot; verify the receiver returns 200 and the SQS submit queue gets a message |
| 10 | HubSpot webhook signature validation (negative) | Send a forged `X-HubSpot-Signature-v3` header to the API Gateway URL; verify 401 |
| 11 | End-to-end: GovWin marked -> HubSpot synced -> BD edits -> stage transition -> ACE submission | Full pipeline against the Sandbox catalog; verify the AWS Partner Central UI shows the opportunity with correct fields |

For automation scaffolding, see `scripts/find_test_candidates.py` and `scripts/check_marked_and_hubspot.py` for the v1 pattern.

### Sandbox status (2026-04-30)

Ten of the eleven scenarios run end-to-end against the AWS Sandbox catalog with `scripts/sandbox_smoke.py`. Scenario 11 (true GovWin -> HubSpot -> dealstage transition -> ACE) requires interactive HubSpot stage editing and is documented in `docs/phase4-runbook.md` for manual execution.

| # | Scenario | Status |
|---|---|---|
| 1 | CreateOpportunity in Sandbox | PASS |
| 2 | AssociateOpportunity (Solutions) | PASS via fallback. `list_solutions(Catalog="Sandbox")` is empty for newly onboarded orgs, so the script falls back to `RelatedEntityType="AwsProducts"`, `Identifier="AmazonEC2Linux"`. The deployed Lambda handles the same case in production by skipping AssociateOpportunity and relying on `OtherSolutionDescription` on `CreateOpportunity`. |
| 3 | StartEngagementFromOpportunityTask | PASS (task started; review status async-completes) |
| 4 | UpdateOpportunity (positive, optimistic locking) | PASS |
| 5 | UpdateOpportunity (stale lock, ConflictException + recovery) | PASS |
| 6 | EventBridge `Opportunity Updated` | PASS via synthetic Lambda invoke (no AWS-side opportunity needed) |
| 7 | Engagement Invitation Accepted | PASS via synthetic Lambda invoke |
| 8 | Engagement Invitation Rejected | PASS via synthetic Lambda invoke |
| 9 | HubSpot webhook signature validation (positive) | PASS. The script signs a synthetic body with the real client_secret, sends it to the deployed API Gateway URL, and confirms the receiver returns 200 with `dropped=1` (unknown property classification, so nothing is enqueued on the live SQS queues). |
| 10 | HubSpot webhook signature validation (negative, forged) | PASS |
| 11 | End-to-end (manual) | pending: requires interactive HubSpot dealstage transition. See `docs/phase4-runbook.md` Phase 4.1 step 7. |

**To get a real Sandbox Solution provisioned** (only required if you want scenarios 2 and 6-8 to use real Sandbox state instead of the AwsProducts fallback / synthetic invokes): open a Partner Central support case (Type: AWS Partner Central -> CRM Integration) and request that `S-1234567` be added to your org's Sandbox catalog. Typical turnaround is 2-5 business days. Until then, the smoke matrix above provides equivalent coverage.

**Findings from this round of smoke testing**, all already fixed in code:

- `Customer.Account.CountryCode` is nested under `Address`, not flat on `Account`.
- `Customer.Account.WebsiteUrl`, `Address.PostalCode`, and `Address.StateOrRegion` are required by Sandbox business validation.
- `StateOrRegion` uses an enum of full state names ("Dist. of Columbia"), not 2-letter abbreviations. The mapper now normalizes via a `_STATE_ABBR_TO_FULL` lookup.
- `Project.CustomerUseCase` is an AWS-published enum (38 service categories), not a free-text field. The mapper enforces a published default and a HubSpot override property `govwin_ace_use_case`.
- `Project.CustomerBusinessProblem` requires 20-2000 characters; deals with very short descriptions get padded with the title.
- `Origin = "AWS Referral"` puts opportunities in the incoming-referral inbox (not visible to GetOpportunity until accepted). Always use `"Partner Referral"` when we are originating.
- `LifeCycle.Stage = "Closed Lost"` cannot be set while `LifeCycle.ReviewStatus = "Pending Submission"`. Cleanup is best-effort; sandbox state is auto-purged.
- AWS `UpdateOpportunity` is **PUT, not PATCH**. Omitted fields are treated as cleared. Production `update_in_ace.py` and the smoke script both fetch the current opportunity, whitelist to the Update input schema (`PrimaryNeedsFromAws`, `NationalSecurity`, `Customer`, `Project`, `OpportunityType`, `Marketing`, `SoftwareRevenue`, `LifeCycle`), apply the delta, and send the full payload. `ACEClient.scrub_for_update` is the helper.
- AWS Partner Central is eventually consistent: GetOpportunity right after CreateOpportunity can return ResourceNotFoundException for several seconds. The script retries with backoff (5s, 10s, 15s, 20s, 25s, 30s).
