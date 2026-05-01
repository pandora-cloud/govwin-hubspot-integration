# Operations runbook

This is the day-2 reference for operating a deployed instance of the integration. Pair it with [docs/testing-in-your-account.md](testing-in-your-account.md) for the deployment-time playbook and [docs/phase4-runbook.md](phase4-runbook.md) for the sandbox -> production cutover.

Assumed `name_prefix`: `govwin-hubspot-prod`. Substitute your project's name prefix where noted.

## CloudWatch alarms

The `monitoring` Terraform module ships these alarms wired to the same SNS topic as terminal sync failures. Subscribe at least one email or PagerDuty integration to that topic. Alarm names use the resource name they monitor as the prefix so they sort together in the CloudWatch console.

| Alarm | Threshold | What it means | First action |
|---|---|---|---|
| `<lambda-name>-errors` (per Lambda) | `Sum(Errors) >= 1` over 5 min | The Lambda threw at least one uncaught exception. | Tail the function's log group: `aws logs tail /aws/lambda/<lambda-name> --follow`. Look for the most recent stack trace. |
| `<lambda-name>-throttles` (per Lambda) | `Sum(Throttles) >= 1` over 5 min | Reserved concurrency or account concurrency limit hit. | Check the function's `ReservedConcurrentExecutions` against current concurrent-invocation rate. Raise `worker_concurrency` (Terraform variable) if you have headroom against the GovWin 4k/hr budget. |
| `<dlq-name>-depth` (per DLQ) | `ApproximateNumberOfMessagesVisible >= 1` | A message exhausted SQS retries. | Inspect the DLQ; see [Stuck deal recovery](#stuck-deal-recovery) below. |
| `<name-prefix>-scheduler-target-errors` | `Sum(TargetErrorCount) >= 1` over 5 min | EventBridge Scheduler failed to invoke the orchestrator. | Check the Scheduler's role can still assume the orchestrator's role; confirm the orchestrator function exists. |
| `<name-prefix>-webhook-5xx-burst` | `Sum(5XXError) >= 5` over 5 min | The webhook receiver API Gateway returned 5xx repeatedly. | Tail the webhook receiver Lambda log group; usual cause is Secrets Manager unreachable or upstream SQS throttling. |

To list alarms in a console-friendly way:

```bash
aws cloudwatch describe-alarms \
  --alarm-name-prefix govwin-hubspot-prod \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}' \
  --output table
```

## DLQs and queues

Three operational SQS DLQs hold messages that have exhausted retries:

- `govwin-hubspot-prod-govwin-sync-dlq` - GovWin worker batch failed all 5 redeliveries.
- `govwin-hubspot-prod-ace-submit-dlq` - ACE submission failed all retries (typically permanent ValidationException).
- `govwin-hubspot-prod-ace-update-dlq` - ACE update failed all retries.

The general project DLQ (`govwin-hubspot-prod-dlq`) catches anything else.

```bash
# Peek at the next message without removing it
aws sqs receive-message \
  --queue-url $(terraform -chdir=terraform output -raw dlq_url) \
  --max-number-of-messages 1 \
  --visibility-timeout 30

# Drain a DLQ back into its source queue (idempotent if your handlers are)
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:us-east-1:ACCOUNT:govwin-hubspot-prod-ace-submit-dlq \
  --destination-arn arn:aws:sqs:us-east-1:ACCOUNT:govwin-hubspot-prod-ace-submit
```

## Stuck deal recovery

A deal is "stuck" when:

- BD has moved it to a `ace_trigger_stages` stage.
- The webhook fired (`<name-prefix>-hubspot-webhook-receiver` log shows a 200 for the event).
- But `submit_to_ace` never created the AWS Partner Central opportunity (no `Created opportunity Id=O-...` log line, and `ACE#{govwin_id}` in DynamoDB has no `ace_opportunity_id`).

Common causes and recovery:

### Scenario 1: the SQS message landed in the DLQ

Identify it:

```bash
aws sqs receive-message \
  --queue-url $(aws sqs get-queue-url --queue-name govwin-hubspot-prod-ace-submit-dlq --query QueueUrl --output text) \
  --max-number-of-messages 10 \
  --message-attribute-names All \
  --visibility-timeout 60
```

Each message body contains the original HubSpot event. Read the `submit_to_ace` log group around the time the message was first delivered to find the rejection reason. Typical reasons:

- `ValidationException` for a missing or malformed required field. **Fix the deal in HubSpot, then redrive the DLQ.**
- `AccessDeniedException` because the Lambda role lost its `partnercentral:*` actions. **Fix the IAM, then redrive.**

After fixing the cause, redrive the DLQ back into the submit queue (see SQS commands above).

### Scenario 2: the trigger stage doesn't match `ace_trigger_stages`

Symptom: webhook receiver returned 200 with `dropped=1` in the log. The deal moved into a stage that isn't in `ace_trigger_stages`.

Fix: either move the deal into a configured trigger stage, or update `ace_trigger_stages` and `terraform apply`. See `docs/deployment-guide.md#9b.i-find-your-numeric-stage-ids`.

### Scenario 3: DynamoDB has stale state from a prior failed attempt

Sometimes a partial submission leaves `ACE#{govwin_id}` in an intermediate state (e.g. `ace_opportunity_id` set but `ace_engagement_id` missing). The `submit_to_ace` Lambda detects this and resumes from the appropriate step on the next SQS delivery, but if you need to force a clean retry:

```bash
# Inspect the current mapping
aws dynamodb get-item \
  --table-name govwin-hubspot-prod-entity-mappings \
  --key '{"pk":{"S":"ACE#OPP12345"},"sk":{"S":"MAPPING"}}'

# Delete the stale mapping (will cause the next submission to start fresh)
aws dynamodb delete-item \
  --table-name govwin-hubspot-prod-entity-mappings \
  --key '{"pk":{"S":"ACE#OPP12345"},"sk":{"S":"MAPPING"}}'
```

After deleting, toggle the deal's stage off and back on in HubSpot to re-trigger the webhook.

### Scenario 4: an EventBridge event got skipped

If the AWS-side state changed (Approved, Rejected, etc.) but the HubSpot deal stage didn't update, the EventBridge dedup table may have a stale entry. Inspect:

```bash
aws dynamodb get-item \
  --table-name govwin-hubspot-prod-entity-mappings \
  --key '{"pk":{"S":"EVT#<event-id>"},"sk":{"S":"SEEN"}}'
```

If you need to force re-processing, delete the entry. The TTL is 24h so this is rarely needed in steady state.

## DynamoDB backup and restore

Both DynamoDB tables use on-demand billing and PITR (point-in-time recovery) is enabled by default in the production module.

```bash
# Verify PITR is on (should return PointInTimeRecoveryStatus=ENABLED)
aws dynamodb describe-continuous-backups \
  --table-name govwin-hubspot-prod-sync-state

# Take an on-demand backup before a risky migration or schema change
aws dynamodb create-backup \
  --table-name govwin-hubspot-prod-sync-state \
  --backup-name "pre-migration-$(date +%Y%m%d-%H%M%S)"

# List backups
aws dynamodb list-backups --table-name govwin-hubspot-prod-sync-state

# Restore PITR to a specific point (creates a new table; you migrate over)
aws dynamodb restore-table-to-point-in-time \
  --source-table-name govwin-hubspot-prod-sync-state \
  --target-table-name govwin-hubspot-prod-sync-state-restored \
  --restore-date-time 2026-05-01T12:00:00
```

## Lambda code-deploy procedure

For a code-only change (no Terraform infrastructure changes):

```bash
make package
cd terraform
terraform apply
```

Lambdas pick up the new code immediately. In-flight SQS messages already being processed by the previous version's containers complete on the old code; new messages run on the new code. There is no rolling deploy gate; the system tolerates a brief mixed-version window because every Lambda is idempotent.

For a Terraform-only change (no code change), `terraform apply` from the repo root is sufficient.

For a coordinated change that affects both code and infrastructure (e.g. adding a new env var that the code reads), do these in order:

1. Update the code first to read the new env var with a safe default.
2. `make package`.
3. `terraform apply` (introduces the new env var alongside the new code).
4. Once verified, in a follow-up commit, remove the safe default if the var is now mandatory.

## FIPS verification

The Lambdas should always resolve AWS service endpoints to FIPS-suffixed hostnames. Verify:

```bash
PYTHONPATH=. .venv/bin/python scripts/verify_fips.py
```

Expected output: `OK` for every service. If any line shows `FAIL`, that environment has been misconfigured (likely `AWS_USE_FIPS_ENDPOINT=false` was inherited from somewhere).

For an in-cluster sanity check (run from inside a Lambda or a workstation with the same env), the script also reads from boto3, so it sees what the Lambdas see.

## Fault-injection

`scripts/fault_inject.py` exercises the failure paths end-to-end so you can verify that DLQs and SNS alerts actually fire. Run it before flipping `ace_catalog` to `AWS` and after any change to the monitoring/alerting stack.

```bash
PYTHONPATH=. .venv/bin/python scripts/fault_inject.py --suite all
```

The script:

1. Publishes a malformed message to the GovWin sync queue and confirms it lands in the DLQ after retries.
2. Sends an HTTP request with a forged `X-HubSpot-Signature-v3` header and confirms the receiver returns 401.
3. Synthesizes an `Engagement Invitation Expired` EventBridge event and confirms the dedup table records it (run twice to verify the second is a no-op).
4. Confirms the SNS topic publishes a notification on terminal sync failure (uses a no-op subscription that records the message).

Run individual checks with `--suite dlq`, `--suite webhook`, `--suite eventbridge`, or `--suite sns`.

## Disaster recovery

Recovery time objective: 1 hour. Recovery point objective: zero data loss for state that lives in DynamoDB (PITR), at most one orchestrator tick (default 1 hour) for in-flight GovWin discoveries.

Procedure:

1. Re-bootstrap the AWS account with `terraform/bootstrap/` if the account itself was lost.
2. Restore DynamoDB from PITR or the most recent on-demand backup.
3. Re-run `terraform apply` to recreate Lambdas, queues, and IAM.
4. `make package && terraform apply` to push the same code version.
5. Re-run `setup_hubspot_webhooks` to re-register webhook subscriptions on the existing HubSpot dev-platform app.
6. Verify with `scripts/verify_fips.py` and a manual orchestrator invocation.

The HubSpot side (deals, properties, pipelines) is untouched by this procedure: HubSpot is the system of record, not us.
