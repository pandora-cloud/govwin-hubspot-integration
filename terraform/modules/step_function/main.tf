variable "name_prefix" {
  type = string
}

variable "sync_schedule" {
  type    = string
  default = "rate(4 hours)"
}

variable "max_concurrency" {
  type    = number
  default = 2
}

variable "authenticate_arn" {
  type = string
}

variable "discover_changes_arn" {
  type = string
}

variable "fetch_opp_details_arn" {
  type = string
}

variable "sync_to_hubspot_arn" {
  type = string
}

variable "update_sync_state_arn" {
  type = string
}

variable "handle_error_arn" {
  type = string
}

variable "lambda_role_arns" {
  type = list(string)
}

# --- IAM Role for Step Function ---

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${var.name_prefix}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "sfn_permissions" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = var.lambda_role_arns
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "${var.name_prefix}-sfn-policy"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn_permissions.json
}

# --- State Machine ---

resource "aws_sfn_state_machine" "sync" {
  name     = "${var.name_prefix}-sync"
  role_arn = aws_iam_role.sfn.arn

  definition = templatefile("${path.module}/definition.json", {
    authenticate_arn      = var.authenticate_arn
    discover_changes_arn  = var.discover_changes_arn
    fetch_opp_details_arn = var.fetch_opp_details_arn
    sync_to_hubspot_arn   = var.sync_to_hubspot_arn
    update_sync_state_arn = var.update_sync_state_arn
    handle_error_arn      = var.handle_error_arn
    max_concurrency       = var.max_concurrency
  })
}

# --- EventBridge Schedule ---

data "aws_iam_policy_document" "eventbridge_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge" {
  name               = "${var.name_prefix}-eventbridge-role"
  assume_role_policy = data.aws_iam_policy_document.eventbridge_assume.json
}

data "aws_iam_policy_document" "eventbridge_permissions" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.sync.arn]
  }
}

resource "aws_iam_role_policy" "eventbridge" {
  name   = "${var.name_prefix}-eventbridge-policy"
  role   = aws_iam_role.eventbridge.id
  policy = data.aws_iam_policy_document.eventbridge_permissions.json
}

resource "aws_cloudwatch_event_rule" "sync_schedule" {
  name                = "${var.name_prefix}-sync-schedule"
  description         = "Triggers GovWin-HubSpot sync on schedule"
  schedule_expression = var.sync_schedule
}

resource "aws_cloudwatch_event_target" "sync_sfn" {
  rule     = aws_cloudwatch_event_rule.sync_schedule.name
  arn      = aws_sfn_state_machine.sync.arn
  role_arn = aws_iam_role.eventbridge.arn
}

# --- Outputs ---

output "state_machine_arn" {
  value = aws_sfn_state_machine.sync.arn
}

output "state_machine_name" {
  value = aws_sfn_state_machine.sync.name
}

output "eventbridge_rule_name" {
  value = aws_cloudwatch_event_rule.sync_schedule.name
}
