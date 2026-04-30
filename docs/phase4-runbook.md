# Phase 4 runbook: smoke testing the v2 ACE submission half

End-to-end verification that the GovWin -> HubSpot -> AWS Partner Central pipeline works against a real Partner Central Sandbox catalog (4.1) and one production opportunity (4.2).

## Pre-flight (before any AWS calls)

- [ ] On the active feature branch
- [ ] `make test` (248+ unit tests) and `make lint` clean
- [ ] `terraform validate` clean
- [ ] HubSpot project uploaded once via `hs project upload` so we have an `appId` and `clientSecret`
- [ ] `terraform.tfvars` has the new v2 variables filled (`ace_default_solution_id`, `hubspot_webhook_app_id`, `hubspot_webhook_client_secret`)
- [ ] `ace_catalog = "Sandbox"` in `terraform.tfvars`
- [ ] AWS credentials in scope have Sandbox-only IAM (`partnercentral:Catalog: Sandbox` condition)
- [ ] `make package` produced a fresh `lambda-layer.zip`

### Sandbox Solutions: known gap and workaround

AWS docs claim a default Solution `S-1234567` ships with every Sandbox catalog. In practice newly onboarded partner orgs see an empty `list_solutions(Catalog="Sandbox")` response. AWS support is the only path to provision one for an org.

**Fix:** open a Partner Central support case (Type: AWS Partner Central -> CRM Integration) requesting that the default Sandbox Solution be provisioned for your org. Until then:

- The deployed Lambda already does the right thing: when `resolve_solution_id` returns empty, `submit_to_ace` skips `AssociateOpportunity` and relies on `OtherSolutionDescription` on the original `CreateOpportunity` payload. AWS accepts this. See `submit_to_ace.py` step 3.
- For smoke testing of the three-call flow without a real Sandbox Solution, `scripts/sandbox_smoke.py` falls back to `AssociateOpportunity(RelatedEntityType="AwsProducts")` against an entry from the canonical `aws_products.json` reference list (default `AmazonEC2Linux`). This keeps every step exercised end-to-end.

For Sandbox-catalog deployments the `ace_default_solution_id` Terraform variable should be `""` (empty) unless and until AWS provisions a Solution for your org. An AWS-catalog Solution ID like `S-0051246` will fail validation against the Sandbox catalog.

## Phase 4.1 - Sandbox smoke matrix

### Step 1: Deploy the v2 stack to Sandbox

```bash
cd terraform
terraform plan -out=v2-sandbox.tfplan
# Review carefully: should be ~30 new resources (5 Lambdas, 2 SQS + 2 DLQs,
# 1 API Gateway HTTP API + integration + route + stage + permission,
# 2 EventBridge rules + 2 targets + 2 permissions, 1 secret + 1 secret version,
# 1 IAM role policy, 5 log groups, 2 event source mappings).
terraform apply v2-sandbox.tfplan
```

Capture the outputs:

```bash
terraform output hubspot_webhook_target_url
terraform output ace_submit_queue_url
terraform output ace_update_queue_url
terraform output ace_submit_dlq_url
```

The webhook URL is the value HubSpot needs.

### Step 2: Activate HubSpot webhook subscriptions

Two options - pick one:

**Option A (manual):** edit `hubspot-app/src/app/webhooks/webhooks-hsmeta.json`, paste the `hubspot_webhook_target_url` value into `targetUrl`, flip every `"active": false` to `"active": true`, then:

```bash
cd hubspot-app && hs project upload
```

**Option B (Lambda):** invoke the setup Lambda:

```bash
aws lambda invoke \
  --function-name govwin-hubspot-prod-setup-hubspot-webhooks \
  --region us-east-1 \
  --payload "$(jq -n --arg url "$(cd terraform && terraform output -raw hubspot_webhook_target_url)" '{targetUrl: $url}')" \
  --cli-binary-format raw-in-base64-out \
  /tmp/setup-webhooks.json && cat /tmp/setup-webhooks.json
```

### Step 3: Run the automated scenarios (1-5, 10)

```bash
python scripts/sandbox_smoke.py \
  --solution-id S-0051246 \
  --api-url "$(cd terraform && terraform output -raw hubspot_webhook_target_url)"
```

Expected output: `ALL AUTOMATED SCENARIOS PASSED`. The script:

1. Creates a sandbox opportunity (verifies `Id` + `LastModifiedDate`)
2. Associates the configured Solution
3. Starts an engagement task and polls for completion
4. Creates a second opportunity and updates it with optimistic locking
5. Tries to update with a stale `LastModifiedDate` (expects `ConflictException`), then refetches and retries
10. POSTs a forged `X-HubSpot-Signature-v3` to the API Gateway URL (expects 401)

Cleanup: marks both sandbox opportunities `Closed Lost` so they drop out of active queries.

### Step 4: Manual scenario 6 - EventBridge `Opportunity Updated`

Trigger an update on a sandbox opportunity that has a HubSpot deal mapping in DynamoDB. Either:
- Re-run `sandbox_smoke.py --keep` so the opportunity persists, then manually update it via the AWS Partner Central UI under the Sandbox catalog
- Or use the AWS CLI: `aws partnercentral-selling update-opportunity --catalog Sandbox --identifier <opp-id> --last-modified-date <lmd> --project '{"Title": "scenario 6"}'`

Watch:

```bash
aws logs tail --follow /aws/lambda/govwin-hubspot-prod-handle-ace-event \
  --region us-east-1
```

Expect a log line containing `ace.event.opportunity_updated` and a follow-up HubSpot deal stage update.

### Step 5: Manual scenarios 7 + 8 - invitation accept / reject

In the Sandbox Partner Central UI, open the engagement invitation created by scenario 3 and accept it (scenario 7) or reject it (scenario 8). Watch the same log group; expect HubSpot stage to move to `approved_by_aws` or `closedlost`.

### Step 6: Manual scenario 9 - real HubSpot webhook delivery

In HubSpot, drag a real test deal (one that has the three manual fields filled and `govwin_opp_id` populated) to the **Submit to AWS** stage. Watch:

```bash
aws logs tail --follow /aws/lambda/govwin-hubspot-prod-hubspot-webhook-receiver \
  --region us-east-1 &
aws logs tail --follow /aws/lambda/govwin-hubspot-prod-submit-to-ace \
  --region us-east-1 &
```

Expect:
- Receiver: `hubspot webhook accepted: submit=1 update=0 dropped=0` and a 200 response
- Submit Lambda: `ace.created opportunity_id=O-...`, then `ace.associated solution=S-0051246 ...`, then `ace.engagement_started task=...`
- DynamoDB: `aws dynamodb get-item --table-name govwin-hubspot-prod-entity-mappings --key '{"pk":{"S":"ACE#<govwin_id>"},"sk":{"S":"MAPPING"}}'` shows the mapping persisted

### Step 7: End-to-end scenario 11

Mark a fresh test opportunity in GovWin IQ (Add to Web Services Download). Wait for the next scheduled sync (or trigger manually via Step Function). When the deal lands in HubSpot:
1. Open it, fill the three manual fields
2. Move to Submit to AWS
3. Watch the AWS Partner Central Sandbox UI - the opportunity should appear under Co-Sell within ~30 seconds
4. Optionally accept the engagement invitation in the Sandbox UI to confirm the back-channel sync

### Sandbox gate: decide go / no-go

All 11 scenarios green -> proceed to Phase 4.2. Any failure -> fix, re-deploy, re-run from the failed step.

## Phase 4.2 - Production smoke

### Pre-flight

- [ ] All 11 sandbox scenarios passed
- [ ] HubSpot subscriptions confirmed `active: true`
- [ ] One **low-stakes** real GovWin opportunity selected for production smoke
- [ ] Decision: opportunity is either acceptable to keep in production ACE or will be withdrawn after the smoke

### Step 1: Flip the catalog

```hcl
# terraform.tfvars
ace_catalog = "AWS"
```

```bash
cd terraform
terraform plan -out=v2-prod.tfplan
# Review: the ACE IAM policy should drop the partnercentral:Catalog: Sandbox
# condition; the EventBridge rules update their detail.catalog filter.
terraform apply v2-prod.tfplan
```

### Step 2: End-to-end production smoke

Repeat scenario 11 against the production catalog with the chosen low-stakes opportunity. Watch the same log groups. Confirm the opportunity appears in the **production** AWS Partner Central UI, not Sandbox.

### Step 3: Decide

- AWS approves -> deal is live; keep going
- AWS rejects with feedback -> fix the data in HubSpot, retry
- Withdraw if the test opportunity should not have been submitted -> use the Partner Central UI to close it

## Rollback

If anything looks wrong in production, the safest rollback is to flip `ace_catalog` back to `Sandbox` in `terraform.tfvars` and re-apply. This rebuilds the IAM policy with the Sandbox-only condition; further submissions will fail with `AccessDeniedException` until the catalog is flipped back. The v1 GovWin -> HubSpot sync is unaffected by any of these changes.

If the rollback also needs to disable the webhook deliveries, flip the subscriptions to `active: false` in `hubspot-app/src/app/webhooks/webhooks-hsmeta.json` and `hs project upload`. HubSpot stops delivering immediately.

## Cleanup after smoke

- Sandbox opportunities: marked Closed Lost by `sandbox_smoke.py`. Sandbox state is wiped periodically by AWS so this is best-effort.
- Production smoke opportunity: keep or withdraw per Step 3 above.
- DynamoDB mappings (`ACE#<govwin_id>` records): leave them; they have a 1-year TTL.
- DLQ messages: should be empty. If non-zero, inspect and discard.

## Tagging the release

Once Phase 4.2 succeeds:

```bash
git tag -a v2.0.0 -m "Initial public release: end-to-end GovWin to AWS Partner Central pipeline"
git push origin v2.0.0
```
