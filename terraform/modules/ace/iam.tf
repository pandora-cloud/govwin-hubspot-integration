# Additional IAM permissions added to the existing Lambda execution role
# for the ACE submission path.
#
# The partnercentral:Catalog condition is the cross-environment safety net:
# Sandbox roles can only touch Sandbox; production roles can only touch AWS.
# Even if code accidentally passes the wrong Catalog string, the API rejects
# with AccessDeniedException.
#
# resources = ["*"] is unavoidable for partnercentral actions: the AWS
# Partner Central Selling API does not support resource-level IAM (no
# opportunity ARNs to scope to). The Catalog condition is the closest
# equivalent and is enforced regardless of catalog choice.

data "aws_iam_policy_document" "ace_permissions" {
  # AWS Partner Central Selling API.
  statement {
    actions = [
      "partnercentral:CreateOpportunity",
      "partnercentral:UpdateOpportunity",
      "partnercentral:GetOpportunity",
      "partnercentral:ListOpportunities",
      "partnercentral:ListSolutions",
      "partnercentral:AssociateOpportunity",
      "partnercentral:DisassociateOpportunity",
      "partnercentral:StartEngagementFromOpportunityTask",
      "partnercentral:StartEngagementByAcceptingInvitationTask",
      "partnercentral:GetEngagementInvitation",
      "partnercentral:ListEngagementInvitations",
      "partnercentral:RejectEngagementInvitation",
      "partnercentral:GetAwsOpportunitySummary",
    ]
    resources = ["*"] # see file header; mitigated by the Catalog condition below.
    condition {
      test     = "StringEquals"
      variable = "partnercentral:Catalog"
      values   = [var.ace_catalog]
    }
  }

  # SQS for the submission and update queues.
  statement {
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [
      aws_sqs_queue.submit.arn,
      aws_sqs_queue.submit_dlq.arn,
      aws_sqs_queue.update.arn,
      aws_sqs_queue.update_dlq.arn,
    ]
  }

  # Webhook signing secret.
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.hubspot_webhook.arn]
  }

  # DynamoDB scan is needed for the invitation / hubspot-deal lookup
  # helpers in src/sync/state.py. v1 uses a Scan with a filter; a GSI
  # upgrade is tracked for higher-volume deployments.
  statement {
    actions   = ["dynamodb:Scan"]
    resources = [var.entity_mappings_table_arn]
  }
}

resource "aws_iam_role_policy" "ace" {
  name   = "${var.name_prefix}-ace-policy"
  role   = var.lambda_role_name
  policy = data.aws_iam_policy_document.ace_permissions.json
}
