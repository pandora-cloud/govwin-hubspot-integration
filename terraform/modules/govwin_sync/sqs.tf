# SQS fan-out for the GovWin sync. The orchestrator enqueues one message
# per batch of opportunity references; the worker consumes them.
#
# Replaces the Step Function Map state from v2.0. Each redelivered message
# is independent, so partial-batch failures do not block other batches.

resource "aws_sqs_queue" "sync_dlq" {
  name                      = "${var.name_prefix}-govwin-sync-dlq"
  message_retention_seconds = 14 * 24 * 3600
  # Explicit SSE-SQS instead of relying on the AWS default. NIST 800-53
  # SC-28 / CMMC SC.L2-3.13.16 evaluators expect encryption-at-rest to
  # be configured in IaC, not assumed.
  sqs_managed_sse_enabled = true
}

resource "aws_sqs_queue" "sync" {
  name                       = "${var.name_prefix}-govwin-sync"
  visibility_timeout_seconds = 420 # >= worker timeout (300s) + cold-start headroom
  message_retention_seconds  = 4 * 24 * 3600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.sync_dlq.arn
    # 5 receives. HubSpot 5xx incidents have run 15-30 minutes; with
    # visibility 420s that's ~35 min worst case before DLQ, which lets
    # the worker's internal HubSpot retry budget plus 4-5 SQS redeliveries
    # absorb a typical incident without losing data.
    maxReceiveCount = 5
  })
}
