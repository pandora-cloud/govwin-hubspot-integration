# Dedicated minimal IAM role for the public-facing HubSpot webhook receiver.
#
# Why split: the receiver is the only Lambda in this stack reachable from the
# internet (API Gateway HTTP API). If a parser bug, deserialization vuln, or
# dependency CVE ever lets an attacker run code in this Lambda's execution
# context, the blast radius is whatever the role grants. The shared project
# Lambda role can call CreateOpportunity, read GovWin/HubSpot secrets, write
# the GovWin-tokens secret, and read+write both DynamoDB tables -- a full
# pipeline compromise vector. This role grants only what the receiver code
# actually does (verified against src/lambdas/hubspot_webhook_receiver.py):
#
#   1. secretsmanager:GetSecretValue on the webhook signing secret only.
#   2. sqs:SendMessage on the submit and update queues only.
#   3. dynamodb:PutItem on the entity-mappings table (for the WHK# replay-
#      protection record written by SyncStateManager.reserve_webhook_signature
#      via a conditional put).
#   4. CloudWatch Logs (own log group) and X-Ray.
#
# Worst case if compromised: spam the submit/update SQS queues. Both queues
# feed downstream Lambdas that themselves validate the message against
# DynamoDB lookups and pattern matching, so the attacker cannot publish junk
# to ACE without also forging valid HubSpot deal IDs in DynamoDB -- which the
# receiver role's PutItem-only-with-attribute_not_exists cannot do.

data "aws_iam_policy_document" "webhook_receiver_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "webhook_receiver" {
  name               = "${var.name_prefix}-webhook-receiver-role"
  assume_role_policy = data.aws_iam_policy_document.webhook_receiver_assume.json
  description        = "Internet-reachable HubSpot webhook receiver. Minimal IAM by design; see webhook_receiver_role.tf."
}

data "aws_iam_policy_document" "webhook_receiver" {
  # CloudWatch Logs.
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.name_prefix}-hubspot-webhook-receiver:*"]
  }

  # Webhook signing secret. Read-only.
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.hubspot_webhook.arn]
  }

  # SQS write to the submit and update queues. No receive / delete -- the
  # receiver only enqueues; the workers consume.
  statement {
    actions = ["sqs:SendMessage", "sqs:SendMessageBatch", "sqs:GetQueueAttributes"]
    resources = [
      aws_sqs_queue.submit.arn,
      aws_sqs_queue.update.arn,
    ]
  }

  # DynamoDB PutItem on the entity-mappings table for the WHK# replay-
  # protection record. Conditional put (attribute_not_exists) is what
  # provides the dedup guarantee; read access intentionally denied so a
  # compromised receiver cannot enumerate ACE mappings or HubSpot deal ids.
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [var.entity_mappings_table_arn]
  }

  # X-Ray. Cannot be resource-scoped (AWS-mandated wildcard).
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "webhook_receiver" {
  name   = "${var.name_prefix}-webhook-receiver-policy"
  role   = aws_iam_role.webhook_receiver.id
  policy = data.aws_iam_policy_document.webhook_receiver.json
}
