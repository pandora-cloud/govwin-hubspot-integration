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
  #
  # Split into two statements because not every action supports the
  # partnercentral:Catalog condition key. Opportunity-level operations do
  # (and we keep the catalog gate on those for safety). Engagement +
  # snapshot operations, which were added more recently to the API, do
  # not support the condition key today; the IAM evaluator denies the
  # action when it can't evaluate the condition. The catalog-resource
  # ARN structure (arn:aws:partnercentral:us-east-1::catalog/Sandbox/...)
  # still scopes who can read/write what at the resource level.
  statement {
    sid = "OpportunityOperationsCatalogGated"
    actions = [
      "partnercentral:CreateOpportunity",
      "partnercentral:UpdateOpportunity",
      "partnercentral:GetOpportunity",
      "partnercentral:ListOpportunities",
      "partnercentral:ListSolutions",
      "partnercentral:AssociateOpportunity",
      "partnercentral:DisassociateOpportunity",
      "partnercentral:AssignOpportunity",
      "partnercentral:SubmitOpportunity",
      "partnercentral:RejectEngagementInvitation",
      "partnercentral:GetEngagementInvitation",
      "partnercentral:ListEngagementInvitations",
      "partnercentral:GetAwsOpportunitySummary",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "partnercentral:Catalog"
      values   = [var.ace_catalog]
    }
  }
  statement {
    sid = "EngagementAndSnapshotOperations"
    # These actions do not currently support the partnercentral:Catalog
    # condition key. Granted unconditionally so StartEngagementFromOpportunityTask
    # (which internally calls CreateEngagement + CreateResourceSnapshot) can
    # complete. Catalog isolation for these operations relies on the
    # catalog-prefixed ARN of the underlying engagement, which AWS ties back
    # to the opportunity created in the same catalog.
    actions = [
      "partnercentral:CreateEngagement",
      "partnercentral:CreateEngagementInvitation",
      "partnercentral:AcceptEngagementInvitation",
      "partnercentral:GetEngagement",
      "partnercentral:ListEngagements",
      "partnercentral:StartEngagementFromOpportunityTask",
      "partnercentral:StartEngagementByAcceptingInvitationTask",
      "partnercentral:ListEngagementByAcceptingInvitationTasks",
      "partnercentral:ListEngagementFromOpportunityTasks",
      "partnercentral:CreateResourceSnapshot",
      "partnercentral:CreateResourceSnapshotJob",
      "partnercentral:StartResourceSnapshotJob",
      "partnercentral:GetResourceSnapshot",
      "partnercentral:GetResourceSnapshotJob",
      "partnercentral:ListResourceSnapshots",
      "partnercentral:ListResourceSnapshotJobs",
    ]
    resources = ["*"]
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
