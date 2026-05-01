# Testing the integration in your own AWS account

This guide walks a downstream user (a federal AWS partner deploying the integration into their own account) through the steps to stand the pipeline up against an AWS Partner Central Sandbox catalog, run the smoke matrix end-to-end, and decide when it is safe to flip to the production AWS catalog.

The integration ships sandbox-first by default: the IAM policy on every Lambda includes a `partnercentral:Catalog: Sandbox` condition when `ace_catalog = "Sandbox"`, so even a misconfigured deploy cannot accidentally write to your production Partner Central catalog.

## Before you start

You need:

1. **A clean AWS account** (or a sub-account in your organization) where this integration will live. Region must be `us-east-1` because the Partner Central Selling API only operates in that region.
2. **Linked AWS Marketplace Seller and Partner Central accounts.** Required for any Partner Central Selling API access at all. Confirm via the Partner Central console: https://partnercentral.awspartner.com.
3. **Sandbox catalog access.** Run `aws partnercentral-selling list-opportunities --catalog Sandbox --region us-east-1` from a workstation with Partner Central IAM access. It should return an empty list, not an `AccessDeniedException`. If you get a permission error, your account is not yet enrolled in the Partner Central Selling API. Contact your AWS Partner Development Manager.
4. **A Deltek GovWin IQ account** with WSAPI V3 access enabled (separate from regular IQ access; talk to your Deltek rep). You'll need a client id, client secret, username, and password.
5. **A HubSpot account** with a private app token (Settings -> Integrations -> Private Apps), plus a developer-platform 2025.2+ app uploaded for webhooks. The HubSpot CLI (`hs`) is required for the second step: `npm install -g @hubspot/cli`.
6. **An MFA-aware AWS profile** in `~/.aws/config` for day-to-day deployment. Production is gated on this; see the MFA section below.

## A note about Sandbox catalog Solutions

AWS docs claim a default Solution `S-1234567` exists in every Sandbox catalog. In practice, newly onboarded partner orgs see `list_solutions(Catalog="Sandbox")` return an empty array. AWS support is the only way to provision one for your org.

**Two paths forward:**

1. **Long-term fix.** Open a Partner Central support case (Type: AWS Partner Central -> CRM Integration) requesting that the default Sandbox Solution `S-1234567` be provisioned to your org. Typical turnaround: 2-5 business days.
2. **Test today.** Set `ace_default_solution_id = ""` in `terraform.tfvars`. The deployed Lambda already handles this path: it skips `AssociateOpportunity` and relies on the `OtherSolutionDescription` field on `CreateOpportunity`, which AWS accepts. The included `scripts/sandbox_smoke.py` script automatically falls back to `AssociateOpportunity(RelatedEntityType="AwsProducts")` against an entry from the canonical AWS product list, so the full three-call flow runs end-to-end in tests without any partner-side Solution registration.

For production (catalog flipped to `AWS`), use a real Solution ID that has been Approved in your AWS-catalog Solutions Catalog (Partner Central UI -> My Solutions). A Limited or Public solution will work; a Draft will not.

## MFA on the deployer role

The integration's bootstrap module creates a deployer IAM role. Day-to-day `terraform apply` assumes that role. Its trust policy requires MFA on the assume call by default.

Why: the deployer role can update Lambda code, IAM policies, secrets, DynamoDB tables, and the public-facing webhook API. A leaked access key with `sts:AssumeRole` on the deployer ARN is a full-account compromise vector. MFA on the assume call converts a leaked-key incident from "attacker has a working session" into "attacker also needs the user's MFA device". This satisfies controls federal partners are typically on the hook for: NIST 800-53 IA-2(1), CMMC L2 IA.L2-3.5.3, and SOC 2 CC6.6.

For pure sandbox testing (no real Partner Central data flowing yet), the bootstrap supports a time-boxed override:

```hcl
# terraform/bootstrap/terraform.tfvars
require_mfa_to_assume_deployer      = false
acknowledge_no_mfa_for_sandbox_only = true
acknowledge_no_mfa_justification    = "Sandbox account 123456789012 - pre-production smoke testing only; no AWS catalog data flows yet. MFA enforced post 2026-06-15."
acknowledge_no_mfa_expires_at       = "2026-06-15"
```

The bootstrap will fail to apply if:
- `acknowledge_no_mfa_for_sandbox_only = true` but `acknowledge_no_mfa_justification` is empty or under 20 characters.
- `acknowledge_no_mfa_expires_at` is empty or in the past.

The deployer role is also tagged with `compliance:RiskMode = "sandbox-no-mfa"` and `compliance:NoMFAExceptionExpiry = <date>` so AWS Config / CloudTrail Lake queries can surface accounts left in this state.

**Before any real Partner Central data lands in the account**, set `acknowledge_no_mfa_for_sandbox_only = false` and `require_mfa_to_assume_deployer = true`, and reapply the bootstrap. Day-to-day deployers must then use an MFA-stamped session.

## Step-by-step

### 1. Clone and configure

```bash
git clone https://github.com/<org>/govwin-hubspot-integration.git
cd govwin-hubspot-integration
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
$EDITOR terraform/terraform.tfvars
```

Set:

```hcl
# Required
govwin_client_id          = "..."
govwin_client_secret      = "..."
govwin_username           = "..."
govwin_password           = "..."
hubspot_private_app_token = "..."
aws_profile               = "your-mfa-profile"
aws_region                = "us-east-1"
environment               = "prod"   # use "sandbox" or "dev" if you want a non-prod resource prefix

# Sandbox testing (until you flip to AWS catalog)
ace_catalog                  = "Sandbox"
ace_default_solution_id      = ""    # empty until support provisions S-1234567
ace_default_involvement_type = "Co-Sell"
ace_default_visibility       = "Full"

# HubSpot dev-platform app you created with `hs project create`
hubspot_webhook_app_id        = "..."
hubspot_webhook_client_secret = "..."

# Stage in HubSpot that triggers ACE submission. Map to your pipeline's
# "Submit to AWS" stage internalId after running setup_hubspot.
ace_trigger_stages = "..."
```

### 2. Bootstrap the AWS account (one time)

```bash
cd terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars   # Set deployer_principal_arns, MFA flags
terraform init
terraform apply
```

This creates the S3 backend bucket and the deployer IAM role. After apply, capture the deployer role ARN from the outputs and put it in `terraform/terraform.tfvars`:

```hcl
deployer_role_arn = "arn:aws:iam::ACCOUNT:role/govwin-hubspot-prod-deployer"
```

### 3. Deploy the integration

```bash
cd terraform
terraform init
make package          # one-time: builds lambda-layer.zip
terraform apply
```

Capture the outputs:

```bash
terraform output hubspot_webhook_target_url
terraform output govwin_orchestrator_arn
terraform output govwin_sync_queue_url
terraform output govwin_sync_schedule
```

### 4. Wire up the HubSpot webhook

```bash
cd hubspot-app
$EDITOR webhooks-hsmeta.json    # set targetUrl to the value from step 3
hs project upload
```

HubSpot will start delivering signed webhooks to your API Gateway URL within seconds.

### 5. Run the sandbox smoke matrix

The `scripts/sandbox_smoke.py` script exercises 10 of the 11 documented scenarios end-to-end against your deployed sandbox stack:

```bash
AWS_PROFILE=your-mfa-profile \
ACE_DEFAULT_SOLUTION_ID="" \
HUBSPOT_WEBHOOK_TARGET_URL=$(terraform -chdir=terraform output -raw hubspot_webhook_target_url) \
HANDLE_ACE_EVENT_FUNCTION=govwin-hubspot-prod-handle-ace-event \
HUBSPOT_WEBHOOK_SECRET_NAME=govwin-hubspot-prod/hubspot-webhook \
.venv/bin/python scripts/sandbox_smoke.py
```

Expected output:

```
Scenario 1: CreateOpportunity in Sandbox                              [OK]
Scenario 2: AssociateOpportunity (AwsProducts)                         [OK]
Scenario 3: StartEngagementFromOpportunityTask                         [OK]
Scenario 4: UpdateOpportunity (positive optimistic lock)               [OK]
Scenario 5: UpdateOpportunity (stale lock -> ConflictException)        [OK]
Scenario 6: EventBridge Opportunity Updated -> handle_ace_event        [OK]
Scenario 7: EventBridge Engagement Invitation Accepted                 [OK]
Scenario 8: EventBridge Engagement Invitation Rejected                 [OK]
Scenario 9: HubSpot webhook signature validation (positive)            [OK]
Scenario 10: HubSpot webhook signature validation (negative, forged)   [OK]

ALL RUN SCENARIOS PASSED
```

Each scenario is independently runnable; rerun is idempotent.

### Sandbox state-machine constraints (read before running scenario 11)

AWS Sandbox enforces a few non-obvious rules that scripted state walks will hit:

- **`ReviewStatus` is partially server-managed.** Partners can `UpdateOpportunity` to set `Approved`, `Rejected`, or `Action Required`. They **cannot** set `In review` (server-only) or `Submitted` (AWS auto-applies after `StartEngagementFromOpportunityTask` validates and requires `Project.SalesActivities` to be populated; the mapper seeds a default).
- **`Approved` is terminal.** Once an opportunity reaches `ReviewStatus=Approved`, AWS Sandbox refuses any further `ReviewStatus` change with `reviewStatus is not editable if status is Approved`. To exercise the rejection path, use a fresh opportunity.
- **`Stage` cannot move while `ReviewStatus=Pending Submission`.** This blocks "mark this opp Closed Lost as cleanup" until you've at least called `StartEngagementFromOpportunityTask`.
- **No `DeleteOpportunity` API.** Cleanup is best-effort: move the opp to `Stage=Closed Lost` (after advancing past `Pending Submission`). AWS Sandbox auto-wipes annually.

Practical implication for scenario 11: drive the opp `Pending Submission → Approved` directly to confirm the EventBridge → handle_ace_event → HubSpot stage path. The `Submitted` and `In review` intermediate states are observable only through the AWS reviewer's actual workflow in production catalog.

### 6. Run scenario 11 manually (the one the script can't automate)

Scenario 11 is the full pipeline path: GovWin marked -> HubSpot synced -> BD edits -> dealstage transition -> ACE submission. The script can't automate it because it requires an interactive HubSpot stage transition.

1. Mark a real low-stakes opportunity in GovWin IQ for "Web Services Download".
2. Wait for the next orchestrator tick (default `rate(1 hour)`), or manually invoke:
   ```bash
   aws lambda invoke --function-name govwin-hubspot-prod-govwin-orchestrator \
     --region us-east-1 /tmp/orch.json && cat /tmp/orch.json
   ```
3. Confirm the deal appears in HubSpot's GovWin Pipeline.
4. As the BD user would: fill in the three manual ACE fields on the deal (`govwin_ace_partner_need`, `govwin_ace_delivery_model`, `govwin_ace_use_case`).
5. Move the deal to your "Submit to AWS" stage. The webhook receiver fires, `submit_to_ace` runs, and your AWS Sandbox catalog gets a new opportunity within seconds.
6. Verify in CloudWatch logs that all three calls (`CreateOpportunity`, `AssociateOpportunity`, `StartEngagementFromOpportunityTask`) succeeded.
7. Verify in the Partner Central Sandbox UI that the opportunity is visible and has the fields you expect.

### 7. Stress and failure tests (recommended)

Before flipping to the AWS catalog, exercise the failure paths:

| Test | How | Expected |
|---|---|---|
| GovWin rate limit | Set `MAX_CONCURRENCY=5` and trigger many syncs | Rate-limited messages return as `batchItemFailures`; SQS redelivers |
| HubSpot 5xx | Block egress to `api.hubapi.com` for 1 minute, trigger a sync | Worker reports sync_failed=true, SQS redelivers, message lands in DLQ after 5 receives |
| DLQ replay | Inspect the DLQ; redrive a message via the SQS console | Worker reprocesses the same batch successfully |
| Webhook replay | Capture a real signed delivery, replay within 5 minutes | Receiver returns 409 with `replay detected` |
| EventBridge dedup | Send the same `aws.partnercentral-selling` event id twice | Second delivery returns `status=duplicate` |

### 8. Criteria for flipping `ace_catalog = "AWS"`

Only flip to production when ALL of these are true:

- [ ] All 10 automated sandbox scenarios pass.
- [ ] Scenario 11 has been run manually with at least one real GovWin opportunity end-to-end.
- [ ] Failure tests in step 7 have all been verified.
- [ ] Your Partner Central account has at least one Approved Solution registered in the AWS catalog (not Draft, not Limited-but-not-yet-co-sell-approved).
- [ ] `ace_default_solution_id` in tfvars is set to that Approved Solution's `S-` ID.
- [ ] MFA on the deployer role is enabled (`require_mfa_to_assume_deployer = true`, `acknowledge_no_mfa_for_sandbox_only = false`).
- [ ] Email notifications are wired (`enable_notifications = true`, `notification_email` set).
- [ ] The SNS topic subscription is confirmed (you've clicked the confirmation link).
- [ ] CloudWatch alarms on the DLQ depth and on the orchestrator/worker error count exist (the `monitoring` module ships these by default).
- [ ] An on-call engineer has acknowledged the runbook in `docs/phase4-runbook.md`.

After flipping, run scenario 11 once more in production catalog with a single real low-stakes opportunity, then withdraw or let AWS process it normally.

## Cost expectations

For a partner with ~1,000 opportunities flowing through HubSpot and ~10 ACE submissions per month, the steady-state AWS bill runs ~$6/month: most of it Lambda invocations, DynamoDB reads/writes, and Secrets Manager API calls. EventBridge Scheduler, SNS, SQS, and API Gateway HTTP API all sit inside their free tiers at this scale. Lambda runs on ARM64 (Graviton2) for the 20% cost reduction.

If your volume is materially higher (say, 50+ opportunities synced per orchestrator tick), the dominant new line item is GovWin API calls inside your existing Deltek contract, not AWS.

## When something breaks

- **Look at SNS**: every terminal sync failure publishes to `arn:aws:sns:us-east-1:ACCOUNT:govwin-hubspot-prod-notifications`. Subscribe an email or PagerDuty integration.
- **Look at the DLQs**: `govwin-hubspot-prod-govwin-sync-dlq` (sync), `govwin-hubspot-prod-ace-submit-dlq` (ACE submission), `govwin-hubspot-prod-ace-update-dlq` (ACE update). Anything in there is a message that failed all retries.
- **Look at X-Ray**: every Lambda has X-Ray Active tracing on. The Service Map shows the full GovWin -> SQS -> Worker -> HubSpot -> Webhook -> SQS -> ACE -> EventBridge chain end to end.
- **Look at CloudWatch logs**: each Lambda has a dedicated log group at `/aws/lambda/govwin-hubspot-prod-<function-name>` with retention 30 days.

## Test layers and how to run each

The full test pyramid has four layers:

1. **Hermetic unit tests** (no network, no AWS, no GovWin/HubSpot): `make test`. 293 tests across models, mappers, dedup, rate limiters, both API clients, the orchestrator, and every Lambda handler. Should run in under a minute.
2. **Static checks**: `make lint` (ruff), `make typecheck` (mypy with the pydantic plugin enabled). CI runs both on every push.
3. **LocalStack integration tests**: `make local-up && make local-test && make local-down`. The 6 tests in `tests/integration/test_localstack_state.py` exercise the DynamoDB state manager and Secrets Manager paths against a real boto3 client talking to LocalStack 3.8 (community-licensed; no paid token required). They auto-skip when `AWS_ENDPOINT_URL` is not set so `make test` stays hermetic.
4. **Pre-deployment validation** (real but read-only credentials): `cp .env.example .env && make validate`. The script exchanges your GovWin credentials for an OAuth token, calls `/opportunities?max=1` and HubSpot `/crm/v3/objects/deals?limit=1`, and confirms the configured AWS profile can reach Secrets Manager. Use `--skip-hubspot` or `--skip-govwin` if you only have one set of credentials at hand.
5. **Dry run** (real GovWin reads, no HubSpot writes): `make dry-run` runs `scripts/dry_run.py --limit 5` against real GovWin data, fetches up to N opportunities, runs them through the mapper, and prints the resulting payload without writing anything. Use this after `make validate` and before the first real sync.
6. **Sandbox smoke matrix**: see Step 5 above; runs against your deployed Sandbox catalog.
7. **End-to-end production smoke** (Step 6 above) plus the 10-scenario GovWin -> HubSpot matrix below: a one-time human-driven check after deploying.

## End-to-end GovWin -> HubSpot smoke matrix

Run by the integration owner (typically your BD lead) once the pipeline is live. These tests cannot be automated because they require interactive marking/unmarking inside GovWin IQ and visual inspection inside HubSpot.

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

## ACE sandbox smoke matrix (Phase 4.1)

Run before flipping `ace_catalog` from `Sandbox` to `AWS`. Each test is scriptable and self-cleans by archiving the sandbox opportunities afterward. `scripts/sandbox_smoke.py` automates scenarios 1-10; scenario 11 is the manual one-shot in Step 6 above.

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

### Sandbox findings (from the maintainer's initial rollout)

These observations from the first end-to-end smoke run are baked into the mapper and the smoke script. They're recorded here so a downstream reader knows what AWS validation idiosyncrasies the integration is already handling, and what to expect if AWS changes them:

- `Customer.Account.CountryCode` is nested under `Address`, not flat on `Account`.
- `Customer.Account.WebsiteUrl`, `Address.PostalCode`, and `Address.StateOrRegion` are required by Sandbox business validation.
- `StateOrRegion` uses an enum of full state names ("Dist. of Columbia"), not 2-letter abbreviations. The mapper now normalizes via a `_STATE_ABBR_TO_FULL` lookup.
- `Project.CustomerUseCase` is an AWS-published enum (38 service categories), not a free-text field. The mapper enforces a published default and a HubSpot override property `govwin_ace_use_case`.
- `Project.CustomerBusinessProblem` requires 20-2000 characters; deals with very short descriptions get padded with the title.
- `Origin = "AWS Referral"` puts opportunities in the incoming-referral inbox (not visible to GetOpportunity until accepted). Always use `"Partner Referral"` when we are originating.
- `LifeCycle.Stage = "Closed Lost"` cannot be set while `LifeCycle.ReviewStatus = "Pending Submission"`. Cleanup is best-effort; sandbox state is auto-purged.
- AWS `UpdateOpportunity` is **PUT, not PATCH**. Omitted fields are treated as cleared. The production `update_in_ace.py` and the smoke script both fetch the current opportunity, whitelist to the Update input schema (`PrimaryNeedsFromAws`, `NationalSecurity`, `Customer`, `Project`, `OpportunityType`, `Marketing`, `SoftwareRevenue`, `LifeCycle`), apply the delta, and send the full payload. `ACEClient.scrub_for_update` is the helper.
- AWS Partner Central is eventually consistent: `GetOpportunity` immediately after `CreateOpportunity` can return `ResourceNotFoundException` for several seconds. The script retries with backoff (5s, 10s, 15s, 20s, 25s, 30s).

## Reference: results from the maintainer's initial production rollout

These numbers reflect what "passing" looks like for an established federal AWS partner running this against a real GovWin tenant and a real HubSpot account. Your numbers will differ; what matters is that the test categories all show PASS.

### Sync tests

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

### Dedup and incremental sync

| # | Test | Result | Notes |
|---|---|---|---|
| 16 | Incremental skip (no changes) | PASS | 0 opps synced, 1 API call |
| 17 | Repeat incremental skip | PASS | Confirmed idempotent on second run |
| 18 | Company dedup across opps | PASS | 3 GSA opps share 1 company record |
| 19 | Contact dedup across opps | PASS | 10 unique contacts, 0 duplicates |

### Infrastructure

| # | Test | Result | Notes |
|---|---|---|---|
| 20 | EventBridge schedule | PASS | rate(1 hour), ENABLED |
| 21 | SNS notifications | PASS | Email subscription confirmed |
| 22 | SQS dead letter queue | PASS | 0 messages (no unhandled errors) |
| 23 | 10 consecutive executions | PASS | All SUCCEEDED |
| 24 | API call efficiency | PASS | 1 call for "no changes" check |
| 25 | ARM64 (Graviton2) Lambda | PASS | All Lambdas on arm64 |

## Reference docs

- `docs/architecture.md`: pipeline diagrams, DynamoDB schema, rate-limit strategy.
- `docs/phase4-runbook.md`: the original 11-scenario smoke matrix and Phase 4.2 production smoke.
- `docs/operations.md`: alarms, stuck-deal recovery, fault-injection, DR notes.
- `docs/reference/aws-partner-central/`: API references, EventBridge event types, sandbox notes.
- `docs/reference/hubspot/private-app-webhooks.md`: HubSpot signature validation deep dive.
- `terraform/bootstrap/README.md`: bootstrap operator vs. deployer role split, MFA gate rationale.
