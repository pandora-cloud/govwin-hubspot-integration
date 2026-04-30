# Two Lambdas replace the v2.0 chain of authenticate / discover_changes /
# fetch_opp_details / sync_to_hubspot / update_sync_state. The orchestrator
# does discovery and SQS fan-out; the worker does per-batch fetch + sync.

locals {
  sync_env = merge(var.lambda_env, {
    GOVWIN_SYNC_QUEUE_URL = aws_sqs_queue.sync.url
  })
}

resource "aws_lambda_function" "orchestrator" {
  function_name                  = "${var.name_prefix}-govwin-orchestrator"
  role                           = var.lambda_role_arn
  handler                        = "src.lambdas.govwin_orchestrator.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 600 # discovery can take a few minutes on first run
  memory_size                    = 512
  reserved_concurrent_executions = 1
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  environment {
    variables = local.sync_env
  }
}

resource "aws_lambda_function" "worker" {
  function_name                  = "${var.name_prefix}-govwin-worker"
  role                           = var.lambda_role_arn
  handler                        = "src.lambdas.govwin_worker.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 300
  memory_size                    = 512
  reserved_concurrent_executions = var.worker_concurrency
  filename                       = var.lambda_source_zip
  source_code_hash               = var.lambda_source_hash
  layers                         = [var.lambda_layer_arn]

  environment {
    variables = local.sync_env
  }
}

resource "aws_cloudwatch_log_group" "logs" {
  for_each = toset([
    aws_lambda_function.orchestrator.function_name,
    aws_lambda_function.worker.function_name,
  ])
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn                   = aws_sqs_queue.sync.arn
  function_name                      = aws_lambda_function.worker.arn
  batch_size                         = 1 # one batch-of-opportunities per invoke
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}
