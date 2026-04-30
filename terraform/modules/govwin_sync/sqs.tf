# SQS fan-out for the GovWin sync. The orchestrator enqueues one message
# per batch of opportunity references; the worker consumes them.
#
# Replaces the Step Function Map state from v2.0. Each redelivered message
# is independent, so partial-batch failures do not block other batches.

resource "aws_sqs_queue" "sync_dlq" {
  name                      = "${var.name_prefix}-govwin-sync-dlq"
  message_retention_seconds = 14 * 24 * 3600
}

resource "aws_sqs_queue" "sync" {
  name                       = "${var.name_prefix}-govwin-sync"
  visibility_timeout_seconds = 360 # > worker timeout (300s) + buffer
  message_retention_seconds  = 4 * 24 * 3600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.sync_dlq.arn
    maxReceiveCount     = 3
  })
}
