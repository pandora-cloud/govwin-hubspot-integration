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

## Reference docs

- `docs/architecture.md`: pipeline diagrams, DynamoDB schema, rate-limit strategy.
- `docs/phase4-runbook.md`: the original 11-scenario smoke matrix and Phase 4.2 production smoke.
- `docs/testing.md`: complete test inventory plus sandbox-status table.
- `docs/reference/aws-partner-central/`: API references, EventBridge event types, sandbox notes.
- `docs/reference/hubspot/private-app-webhooks.md`: HubSpot signature validation deep dive.
- `terraform/bootstrap/README.md`: bootstrap operator vs. deployer role split, MFA gate rationale.
