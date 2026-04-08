variable "name_prefix" { type = string }
variable "aws_profile" { type = string }
variable "aws_region" { type = string }
variable "sync_state_table_name" { type = string }
variable "sync_state_table_arn" { type = string }
variable "entity_mappings_table_name" { type = string }
variable "entity_mappings_table_arn" { type = string }
variable "govwin_secret_arn" { type = string }
variable "hubspot_secret_arn" { type = string }
variable "govwin_tokens_secret_arn" { type = string }
variable "govwin_secret_name" { type = string }
variable "hubspot_secret_name" { type = string }
variable "govwin_tokens_secret_name" { type = string }
variable "sns_topic_arn" { type = string }
variable "dlq_url" { type = string }
variable "dlq_arn" { type = string }
variable "govwin_opp_types" {
  type    = string
  default = "ALL"
}
variable "govwin_market" {
  type    = string
  default = ""
}
variable "govwin_saved_search_id" {
  type    = string
  default = ""
}
variable "govwin_bookmarked_only" {
  type    = bool
  default = false
}
variable "govwin_marked_version" {
  type    = string
  default = "2.2"
}
variable "initial_lookback_days" {
  type    = number
  default = 365
}
variable "batch_size" {
  type    = number
  default = 10
}
variable "max_concurrency" {
  type    = number
  default = 2
}
variable "log_retention_days" {
  type    = number
  default = 30
}

# --- IAM Role ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name_prefix}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_permissions" {
  # CloudWatch Logs - scoped to this project's log groups
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.name_prefix}-*:*"]
  }

  # DynamoDB
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:Query",
    ]
    resources = [
      var.sync_state_table_arn,
      var.entity_mappings_table_arn,
    ]
  }

  # Secrets Manager
  statement {
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
    ]
    resources = [
      var.govwin_secret_arn,
      var.hubspot_secret_arn,
      var.govwin_tokens_secret_arn,
    ]
  }

  # SNS
  statement {
    actions   = ["sns:Publish"]
    resources = [var.sns_topic_arn]
  }

  # SQS (DLQ) - scoped to the specific dead letter queue
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.dlq_arn]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name_prefix}-lambda-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# --- Lambda Layer (shared dependencies) ---

resource "aws_lambda_layer_version" "deps" {
  filename            = "${path.module}/../../../lambda-layer.zip"
  layer_name          = "${var.name_prefix}-deps"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  description         = "Shared Python dependencies for GovWin-HubSpot integration"
  source_code_hash    = fileexists("${path.module}/../../../lambda-layer.zip") ? filebase64sha256("${path.module}/../../../lambda-layer.zip") : ""

  lifecycle {
    create_before_destroy = true
  }
}

# --- Source Code Archive ---

data "archive_file" "source" {
  type        = "zip"
  source_dir  = "${path.module}/../../.."
  output_path = "${path.module}/../../../dist/source.zip"
  excludes = [
    "terraform", ".venv", ".git", "tests", "docs", "dist", "package",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".claude",
    "lambda-layer.zip", ".gitignore", ".gitlab-ci.yml",
    "Makefile", "README.md", "CLAUDE.md", "LICENSE",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    "uv.lock", ".python-version", "CHANGELOG.md",
  ]
}

# --- Common Environment Variables ---

locals {
  common_env = {
    SYNC_STATE_TABLE        = var.sync_state_table_name
    ENTITY_MAPPINGS_TABLE   = var.entity_mappings_table_name
    GOVWIN_SECRET_NAME      = var.govwin_secret_name
    HUBSPOT_SECRET_NAME     = var.hubspot_secret_name
    GOVWIN_TOKENS_SECRET_NAME = var.govwin_tokens_secret_name
    SNS_TOPIC_ARN           = var.sns_topic_arn
    DLQ_URL                 = var.dlq_url
    GOVWIN_OPP_TYPES        = var.govwin_opp_types
    GOVWIN_MARKET           = var.govwin_market
    GOVWIN_SAVED_SEARCH_ID  = var.govwin_saved_search_id
    GOVWIN_BOOKMARKED_ONLY  = tostring(var.govwin_bookmarked_only)
    GOVWIN_MARKED_VERSION   = var.govwin_marked_version
    INITIAL_LOOKBACK_DAYS   = tostring(var.initial_lookback_days)
    BATCH_SIZE              = tostring(var.batch_size)
    MAX_CONCURRENCY         = tostring(var.max_concurrency)
  }
}

# --- Lambda Functions ---

resource "aws_lambda_function" "authenticate" {
  function_name    = "${var.name_prefix}-authenticate"
  role             = aws_iam_role.lambda.arn
  handler          = "src.lambdas.authenticate.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers                         = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "discover_changes" {
  function_name                  = "${var.name_prefix}-discover-changes"
  role                           = aws_iam_role.lambda.arn
  handler                        = "src.lambdas.discover_changes.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 300
  memory_size                    = 256
  reserved_concurrent_executions = 1
  filename         = data.archive_file.source.output_path
  source_code_hash = data.archive_file.source.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "fetch_opp_details" {
  function_name                  = "${var.name_prefix}-fetch-opp-details"
  role                           = aws_iam_role.lambda.arn
  handler                        = "src.lambdas.fetch_opp_details.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 300
  memory_size                    = 256
  reserved_concurrent_executions = 5
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "sync_to_hubspot" {
  function_name                  = "${var.name_prefix}-sync-to-hubspot"
  role                           = aws_iam_role.lambda.arn
  handler                        = "src.lambdas.sync_to_hubspot.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 300
  memory_size                    = 256
  reserved_concurrent_executions = 5
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "update_sync_state" {
  function_name                  = "${var.name_prefix}-update-sync-state"
  role                           = aws_iam_role.lambda.arn
  handler                        = "src.lambdas.update_sync_state.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "setup_hubspot" {
  function_name                  = "${var.name_prefix}-setup-hubspot"
  role                           = aws_iam_role.lambda.arn
  handler                        = "src.lambdas.setup_hubspot.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 120
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "handle_error" {
  function_name                  = "${var.name_prefix}-handle-error"
  role                           = aws_iam_role.lambda.arn
  handler                        = "src.lambdas.handle_error.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 2
  filename                       = data.archive_file.source.output_path
  source_code_hash               = data.archive_file.source.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = local.common_env
  }
}

# --- CloudWatch Log Groups ---

resource "aws_cloudwatch_log_group" "lambda_logs" {
  for_each = toset([
    aws_lambda_function.authenticate.function_name,
    aws_lambda_function.discover_changes.function_name,
    aws_lambda_function.fetch_opp_details.function_name,
    aws_lambda_function.sync_to_hubspot.function_name,
    aws_lambda_function.update_sync_state.function_name,
    aws_lambda_function.setup_hubspot.function_name,
    aws_lambda_function.handle_error.function_name,
  ])

  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}

# --- Run setup_hubspot once during deployment ---

resource "terraform_data" "setup_hubspot" {
  triggers_replace = [
    aws_lambda_function.setup_hubspot.source_code_hash,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      aws lambda invoke \
        --function-name ${aws_lambda_function.setup_hubspot.function_name} \
        --region ${var.aws_region} \
        /tmp/govwin-setup-response.json && \
      cat /tmp/govwin-setup-response.json && \
      ! grep -q FunctionError /tmp/govwin-setup-response.json
    EOT

    environment = {
      AWS_PROFILE = var.aws_profile
    }
  }

  depends_on = [
    aws_lambda_function.setup_hubspot,
    aws_iam_role_policy.lambda,
  ]
}

# --- Outputs ---

output "authenticate_arn" { value = aws_lambda_function.authenticate.arn }
output "discover_changes_arn" { value = aws_lambda_function.discover_changes.arn }
output "fetch_opp_details_arn" { value = aws_lambda_function.fetch_opp_details.arn }
output "sync_to_hubspot_arn" { value = aws_lambda_function.sync_to_hubspot.arn }
output "update_sync_state_arn" { value = aws_lambda_function.update_sync_state.arn }
output "setup_hubspot_arn" { value = aws_lambda_function.setup_hubspot.arn }
output "handle_error_arn" { value = aws_lambda_function.handle_error.arn }

output "all_lambda_arns" {
  value = [
    aws_lambda_function.authenticate.arn,
    aws_lambda_function.discover_changes.arn,
    aws_lambda_function.fetch_opp_details.arn,
    aws_lambda_function.sync_to_hubspot.arn,
    aws_lambda_function.update_sync_state.arn,
    aws_lambda_function.handle_error.arn,
  ]
}
