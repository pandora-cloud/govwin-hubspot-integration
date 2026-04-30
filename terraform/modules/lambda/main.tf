variable "name_prefix" {
  type = string
}

variable "aws_profile" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "sync_state_table_name" {
  type = string
}

variable "sync_state_table_arn" {
  type = string
}

variable "entity_mappings_table_name" {
  type = string
}

variable "entity_mappings_table_arn" {
  type = string
}

variable "govwin_secret_arn" {
  type = string
}

variable "hubspot_secret_arn" {
  type = string
}

variable "govwin_tokens_secret_arn" {
  type = string
}

variable "govwin_secret_name" {
  type = string
}

variable "hubspot_secret_name" {
  type = string
}

variable "govwin_tokens_secret_name" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}

variable "dlq_url" {
  type = string
}

variable "dlq_arn" {
  type = string
}
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

  # Secrets Manager: read-only on credentials secrets.
  statement {
    actions = [
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      var.govwin_secret_arn,
      var.hubspot_secret_arn,
      var.govwin_tokens_secret_arn,
    ]
  }

  # Secrets Manager: PutSecretValue only on the OAuth-token cache. The
  # GovWin auth helper writes the refreshed access/refresh token back so
  # subsequent invocations can reuse them; the long-lived credentials in
  # govwin_secret_arn and the HubSpot token in hubspot_secret_arn stay
  # read-only from the Lambda role.
  statement {
    actions = [
      "secretsmanager:PutSecretValue",
    ]
    resources = [
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

  # X-Ray. Both actions are list-style and do not support resource-level
  # filtering on the call; AWS requires "*". They only let the caller emit
  # trace data attributed to its own role, so the wildcard is industry-
  # standard for this pair.
  statement {
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name_prefix}-lambda-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# --- Lambda Layer (shared dependencies) ---

resource "aws_lambda_layer_version" "deps" {
  filename                 = "${path.module}/../../../lambda-layer.zip"
  layer_name               = "${var.name_prefix}-deps"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  description              = "Shared Python dependencies for GovWin-HubSpot integration"
  source_code_hash         = fileexists("${path.module}/../../../lambda-layer.zip") ? filebase64sha256("${path.module}/../../../lambda-layer.zip") : ""

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
    "hubspot-app", ".github", "scripts",
    "lambda-layer.zip", ".gitignore", ".gitlab-ci.yml",
    "Makefile", "README.md", "CLAUDE.md", "LICENSE",
    "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "AGENTS.md",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    "uv.lock", ".python-version", "CHANGELOG.md",
    "docker-compose.yml", "Dockerfile",
  ]
}

# --- Common Environment Variables ---
#
# Exposed to dependent modules (govwin_sync, ace) so every Lambda gets the
# same DynamoDB/Secrets/GovWin discovery configuration without duplication.

locals {
  common_env = {
    SYNC_STATE_TABLE          = var.sync_state_table_name
    ENTITY_MAPPINGS_TABLE     = var.entity_mappings_table_name
    GOVWIN_SECRET_NAME        = var.govwin_secret_name
    HUBSPOT_SECRET_NAME       = var.hubspot_secret_name
    GOVWIN_TOKENS_SECRET_NAME = var.govwin_tokens_secret_name
    SNS_TOPIC_ARN             = var.sns_topic_arn
    DLQ_URL                   = var.dlq_url
    GOVWIN_OPP_TYPES          = var.govwin_opp_types
    GOVWIN_MARKET             = var.govwin_market
    GOVWIN_SAVED_SEARCH_ID    = var.govwin_saved_search_id
    GOVWIN_BOOKMARKED_ONLY    = tostring(var.govwin_bookmarked_only)
    GOVWIN_MARKED_VERSION     = var.govwin_marked_version
    INITIAL_LOOKBACK_DAYS     = tostring(var.initial_lookback_days)
    BATCH_SIZE                = tostring(var.batch_size)
  }
}

# --- One-time setup Lambda ---
#
# Creates HubSpot pipeline + custom properties on first deploy. Invoked by
# Terraform (terraform_data resource below) after every source-code change.

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
  layers                         = [aws_lambda_layer_version.deps.arn]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.common_env
  }
}

resource "aws_cloudwatch_log_group" "setup_hubspot_logs" {
  name              = "/aws/lambda/${aws_lambda_function.setup_hubspot.function_name}"
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

output "setup_hubspot_arn" {
  value = aws_lambda_function.setup_hubspot.arn
}

output "setup_hubspot_function_name" {
  value = aws_lambda_function.setup_hubspot.function_name
}

# Exposed so the govwin_sync and ace modules can reuse the same role / layer / zip.

output "lambda_role_arn" {
  value = aws_iam_role.lambda.arn
}

output "lambda_role_name" {
  value = aws_iam_role.lambda.name
}

output "lambda_layer_arn" {
  value = aws_lambda_layer_version.deps.arn
}

output "lambda_source_zip" {
  value = data.archive_file.source.output_path
}

output "lambda_source_hash" {
  value = data.archive_file.source.output_base64sha256
}

output "common_env" {
  value = local.common_env
}
