# EventBridge rules for AWS Partner Central events.
# All rules target the same handler Lambda; the handler dispatches by
# detail-type and idempotently dedups by event id.

resource "aws_cloudwatch_event_rule" "opportunity_changes" {
  name        = "${var.name_prefix}-ace-opportunity-changes"
  description = "Opportunity Created/Updated events for our catalog"
  event_pattern = jsonencode({
    source        = ["aws.partnercentral-selling"]
    "detail-type" = ["Opportunity Created", "Opportunity Updated"]
    detail = {
      catalog = [var.ace_catalog]
    }
  })
}

resource "aws_cloudwatch_event_rule" "invitation_outcomes" {
  name        = "${var.name_prefix}-ace-invitation-outcomes"
  description = "Engagement invitation lifecycle events"
  event_pattern = jsonencode({
    source = ["aws.partnercentral-selling"]
    "detail-type" = [
      "Engagement Invitation Created",
      "Engagement Invitation Accepted",
      "Engagement Invitation Rejected",
      "Engagement Invitation Expired",
    ]
    detail = {
      catalog = [var.ace_catalog]
    }
  })
}

resource "aws_cloudwatch_event_target" "opportunity_changes" {
  rule      = aws_cloudwatch_event_rule.opportunity_changes.name
  target_id = "handle_ace_event"
  arn       = aws_lambda_function.handle_ace_event.arn
}

resource "aws_cloudwatch_event_target" "invitation_outcomes" {
  rule      = aws_cloudwatch_event_rule.invitation_outcomes.name
  target_id = "handle_ace_event"
  arn       = aws_lambda_function.handle_ace_event.arn
}

resource "aws_lambda_permission" "eventbridge_opportunity" {
  statement_id  = "AllowEventBridgeOpportunity"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handle_ace_event.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.opportunity_changes.arn
}

resource "aws_lambda_permission" "eventbridge_invitation" {
  statement_id  = "AllowEventBridgeInvitation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handle_ace_event.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.invitation_outcomes.arn
}
