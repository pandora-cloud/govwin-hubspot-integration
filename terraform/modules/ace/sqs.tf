# SQS queues for the HubSpot -> ACE async pipeline.

resource "aws_sqs_queue" "submit_dlq" {
  name                       = "${var.name_prefix}-ace-submit-dlq"
  message_retention_seconds  = 14 * 24 * 3600 # 14 days
  visibility_timeout_seconds = 60
}

resource "aws_sqs_queue" "submit" {
  name                       = "${var.name_prefix}-ace-submit"
  visibility_timeout_seconds = 360           # > submit_to_ace Lambda timeout (300s) + buffer
  message_retention_seconds  = 4 * 24 * 3600 # 4 days
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.submit_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "update_dlq" {
  name                      = "${var.name_prefix}-ace-update-dlq"
  message_retention_seconds = 14 * 24 * 3600
}

resource "aws_sqs_queue" "update" {
  name                       = "${var.name_prefix}-ace-update"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 4 * 24 * 3600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.update_dlq.arn
    maxReceiveCount     = 5
  })
}
