# Extra IAM permissions added to the shared Lambda execution role for the
# orchestrator/worker pair: SQS access on the sync queue and DLQ.

data "aws_iam_policy_document" "sync_permissions" {
  statement {
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [
      aws_sqs_queue.sync.arn,
      aws_sqs_queue.sync_dlq.arn,
    ]
  }
}

resource "aws_iam_role_policy" "sync" {
  name   = "${var.name_prefix}-govwin-sync-policy"
  role   = var.lambda_role_name
  policy = data.aws_iam_policy_document.sync_permissions.json
}
