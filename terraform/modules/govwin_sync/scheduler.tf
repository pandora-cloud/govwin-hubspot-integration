# EventBridge Scheduler triggers the orchestrator Lambda on the configured
# cadence. Replaces the v2.0 EventBridge rule -> Step Function chain.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-govwin-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.orchestrator.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${var.name_prefix}-govwin-scheduler-policy"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule" "sync" {
  name        = "${var.name_prefix}-govwin-sync"
  description = "Triggers GovWin -> HubSpot sync orchestrator on schedule"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.sync_schedule
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_lambda_function.orchestrator.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 0 # The orchestrator runs again on the next tick anyway.
    }
  }
}
