# Five new Lambdas for the ACE submission path. They reuse the existing
# Lambda execution role + dependency layer + source archive produced by
# the lambda module so we do not duplicate packaging.

locals {
  ace_env = {
    SYNC_STATE_TABLE             = var.sync_state_table_name
    ENTITY_MAPPINGS_TABLE        = var.entity_mappings_table_name
    HUBSPOT_SECRET_NAME          = var.hubspot_secret_name
    HUBSPOT_WEBHOOK_SECRET_NAME  = aws_secretsmanager_secret.hubspot_webhook.name
    ACE_SUBMISSION_QUEUE_URL     = aws_sqs_queue.submit.url
    ACE_UPDATE_QUEUE_URL         = aws_sqs_queue.update.url
    ACE_CATALOG                  = var.ace_catalog
    ACE_DEFAULT_SOLUTION_ID      = var.ace_default_solution_id
    ACE_DEFAULT_INVOLVEMENT_TYPE = var.ace_default_involvement_type
    ACE_DEFAULT_VISIBILITY       = var.ace_default_visibility
    ACE_TRIGGER_STAGES           = var.ace_trigger_stages
    HUBSPOT_WEBHOOK_TARGET_URL   = "https://${aws_apigatewayv2_api.webhook.id}.execute-api.${var.aws_region}.amazonaws.com/hubspot"
    # SNS topic for mapping-error and terminal-failure alerts. Without this
    # the ACE Lambdas log "sns: no topic configured" and silently drop
    # the alert -- a stuck deal becomes invisible to BD until someone
    # tails CloudWatch.
    SNS_TOPIC_ARN = var.sns_topic_arn
  }
}

resource "aws_lambda_function" "hubspot_webhook_receiver" {
  function_name                  = "${var.name_prefix}-hubspot-webhook-receiver"
  role                           = aws_iam_role.webhook_receiver.arn
  handler                        = "src.lambdas.hubspot_webhook_receiver.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 5
  memory_size                    = 256
  reserved_concurrent_executions = 20
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.ace_env
  }
}

resource "aws_lambda_function" "submit_to_ace" {
  function_name                  = "${var.name_prefix}-submit-to-ace"
  role                           = var.lambda_role_arn
  handler                        = "src.lambdas.submit_to_ace.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 300
  memory_size                    = 512
  reserved_concurrent_executions = 5
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.ace_env
  }
}

resource "aws_lambda_function" "update_in_ace" {
  function_name                  = "${var.name_prefix}-update-in-ace"
  role                           = var.lambda_role_arn
  handler                        = "src.lambdas.update_in_ace.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 120
  memory_size                    = 256
  reserved_concurrent_executions = 5
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.ace_env
  }
}

resource "aws_lambda_function" "handle_ace_event" {
  function_name                  = "${var.name_prefix}-handle-ace-event"
  role                           = var.lambda_role_arn
  handler                        = "src.lambdas.handle_ace_event.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 60
  memory_size                    = 256
  reserved_concurrent_executions = 5
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.ace_env
  }
}

resource "aws_lambda_function" "setup_hubspot_webhooks" {
  function_name                  = "${var.name_prefix}-setup-hubspot-webhooks"
  role                           = var.lambda_role_arn
  handler                        = "src.lambdas.setup_hubspot_webhooks.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 60
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.ace_env
  }
}

# CloudWatch log groups with explicit retention.
resource "aws_cloudwatch_log_group" "ace_logs" {
  for_each = toset([
    aws_lambda_function.hubspot_webhook_receiver.function_name,
    aws_lambda_function.submit_to_ace.function_name,
    aws_lambda_function.update_in_ace.function_name,
    aws_lambda_function.handle_ace_event.function_name,
    aws_lambda_function.setup_hubspot_webhooks.function_name,
  ])
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

# SQS event source mappings. The webhook receiver routes events between the
# submit queue (dealstage transitions) and the update queue (content-property
# changes), and each Lambda consumes its own queue.
resource "aws_lambda_event_source_mapping" "submit" {
  event_source_arn                   = aws_sqs_queue.submit.arn
  function_name                      = aws_lambda_function.submit_to_ace.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}

resource "aws_lambda_event_source_mapping" "update" {
  event_source_arn                   = aws_sqs_queue.update.arn
  function_name                      = aws_lambda_function.update_in_ace.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}
