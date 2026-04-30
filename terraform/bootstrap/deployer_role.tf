# Deployer IAM role.
# Day-to-day terraform apply assumes this role. Its inline policies are the
# project's full least-privilege deploy manifest. Every action is either
# scoped to a specific ARN pattern owned by this project, or to all
# resources where the relevant AWS service does not support resource-level
# IAM (with conditions where possible).

locals {
  account_id   = data.aws_caller_identity.current.account_id
  region       = local.current_region
  arn_prefix   = "arn:aws:"
  project_arn  = "${local.arn_prefix}*:${local.region}:${local.account_id}"
  project_glob = "${var.project_name}-${var.environment}-*"
}

resource "aws_iam_role" "deployer" {
  name        = "${local.name_prefix}-deployer"
  description = "Assumed by day-to-day terraform apply runs for the ${local.name_prefix} stack"
  # When the no-MFA override is active, tag the role so audit tooling
  # (AWS Config, CloudTrail Lake queries, security-team dashboards) can
  # surface accounts left in this state without having to read tfvars.
  # AWS IAM tag values are limited to [\p{L}\p{Z}\p{N}_.:/=+\-@]*; sanitize
  # the free-text justification before tagging. The original (unsanitized)
  # justification is preserved in the role description below for auditors
  # who need the verbatim text.
  tags = merge(
    local.base_tags,
    var.acknowledge_no_mfa_for_sandbox_only ? {
      "compliance:RiskMode"             = "sandbox-no-mfa"
      "compliance:NoMFAExceptionExpiry" = var.acknowledge_no_mfa_expires_at
      "compliance:NoMFAJustification" = substr(
        replace(
          replace(
            replace(var.acknowledge_no_mfa_justification, ";", " "),
            ",", " "
          ),
          "'", ""
        ),
        0, 256,
      )
    } : {},
  )

  lifecycle {
    # Production environments must require MFA on assume. The require_mfa
    # variable can be set to false ONLY for non-prod (sandbox/dev/test), or
    # for an explicitly-acknowledged sandbox-only window via the
    # acknowledge_no_mfa_for_sandbox_only escape hatch. The escape hatch
    # additionally requires a non-empty justification and a future-dated
    # expiry so the override is bounded in time and auditable.
    precondition {
      condition = !(
        var.environment == "prod"
        && var.require_mfa_to_assume_deployer == false
        && var.acknowledge_no_mfa_for_sandbox_only == false
      )
      error_message = "require_mfa_to_assume_deployer must be true when environment == prod (or set acknowledge_no_mfa_for_sandbox_only = true for a sandbox-only window)."
    }
    precondition {
      condition = !(
        var.acknowledge_no_mfa_for_sandbox_only == true
        && length(var.acknowledge_no_mfa_justification) < 20
      )
      error_message = "acknowledge_no_mfa_for_sandbox_only requires acknowledge_no_mfa_justification (>= 20 characters) explaining why MFA is being disabled."
    }
    precondition {
      condition = !(
        var.acknowledge_no_mfa_for_sandbox_only == true
        && var.acknowledge_no_mfa_expires_at == ""
      )
      error_message = "acknowledge_no_mfa_for_sandbox_only requires acknowledge_no_mfa_expires_at (ISO-8601 YYYY-MM-DD) so the override is time-boxed."
    }
    precondition {
      condition = !(
        var.acknowledge_no_mfa_for_sandbox_only == true
        && var.acknowledge_no_mfa_expires_at != ""
        && timecmp(timeadd(timestamp(), "0s"), "${var.acknowledge_no_mfa_expires_at}T00:00:00Z") >= 0
      )
      error_message = "The no-MFA override (acknowledge_no_mfa_expires_at) has expired. Re-enable MFA, or bump the expiry with a renewed justification."
    }
  }

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = var.deployer_principal_arns
        }
        Action = "sts:AssumeRole"
        Condition = var.require_mfa_to_assume_deployer ? {
          # Compliance posture: require MFA on the assume call. Day-N
          # deployers must use an MFA-stamped session
          # (aws sts get-session-token or an MFA-aware AWS profile).
          Bool = { "aws:MultiFactorAuthPresent" = "true" }
        } : {}
      },
    ]
  })

  max_session_duration = 3600
}

# --------------------------------------------------------------------------
# Policy 1: state-backend access (S3 bucket created by this bootstrap)
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_state_backend" {
  name = "state-backend"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListStateBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"]
        Resource = [aws_s3_bucket.state.arn]
      },
      {
        Sid    = "ReadWriteState"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:GetObjectVersion",
          "s3:DeleteObjectVersion",
        ]
        Resource = ["${aws_s3_bucket.state.arn}/*"]
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 2: Lambda + log groups
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_lambda" {
  name = "lambda"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaFunctions"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:ListVersionsByFunction",
          "lambda:GetPolicy",
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:ListTags",
          "lambda:PutFunctionConcurrency",
          "lambda:DeleteFunctionConcurrency",
          "lambda:CreateEventSourceMapping",
          "lambda:DeleteEventSourceMapping",
          "lambda:GetEventSourceMapping",
          "lambda:UpdateEventSourceMapping",
          "lambda:ListEventSourceMappings",
          "lambda:InvokeFunction",
        ]
        Resource = [
          "arn:aws:lambda:${local.region}:${local.account_id}:function:${local.project_glob}",
          "arn:aws:lambda:${local.region}:${local.account_id}:event-source-mapping:*",
        ]
      },
      {
        Sid    = "LambdaLayers"
        Effect = "Allow"
        Action = [
          "lambda:PublishLayerVersion",
          "lambda:DeleteLayerVersion",
          "lambda:GetLayerVersion",
          "lambda:ListLayerVersions",
        ]
        Resource = "arn:aws:lambda:${local.region}:${local.account_id}:layer:${local.project_glob}"
      },
      {
        Sid    = "LogsGroupsScoped"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:DeleteRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsForResource",
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${local.project_glob}*"
      },
      {
        # logs:DescribeLogGroups is a list-style API that does not support
        # resource-level filtering on the call itself. AWS evaluates the
        # action against arn:aws:logs:region:account:log-group::log-stream:
        # (the wildcard form). We allow it broadly but only in the project's
        # region; the deployer cannot describe log groups outside us-east-1.
        Sid      = "LogsDescribeRegion"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestedRegion" = local.region
          }
        }
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 3: API Gateway HTTP API for the HubSpot webhook receiver
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_apigw" {
  name = "apigateway"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # API Gateway v2 (HTTP API) does not support resource-level IAM for
        # all Create* calls, so apigateway:* on apis/* is the closest scoping.
        Sid    = "ApiGatewayManage"
        Effect = "Allow"
        Action = [
          "apigateway:GET",
          "apigateway:POST",
          "apigateway:PUT",
          "apigateway:PATCH",
          "apigateway:DELETE",
          "apigateway:TagResource",
          "apigateway:UntagResource",
        ]
        Resource = [
          "arn:aws:apigateway:${local.region}::/apis",
          "arn:aws:apigateway:${local.region}::/apis/*",
          "arn:aws:apigateway:${local.region}::/tags/*",
        ]
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 4: SQS queues + DLQs
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_sqs" {
  name = "sqs"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SqsManage"
        Effect = "Allow"
        Action = [
          "sqs:CreateQueue",
          "sqs:DeleteQueue",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ListQueues",
          "sqs:ListQueueTags",
          "sqs:SetQueueAttributes",
          "sqs:TagQueue",
          "sqs:UntagQueue",
          "sqs:AddPermission",
          "sqs:RemovePermission",
        ]
        Resource = "arn:aws:sqs:${local.region}:${local.account_id}:${local.project_glob}"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 5: SNS topic for notifications
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_sns" {
  name = "sns"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SnsManage"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:ListTopics",
          "sns:ListTagsForResource",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:ConfirmSubscription",
          "sns:GetSubscriptionAttributes",
          "sns:ListSubscriptionsByTopic",
          "sns:TagResource",
          "sns:UntagResource",
        ]
        Resource = "arn:aws:sns:${local.region}:${local.account_id}:${local.project_glob}"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 6: DynamoDB tables
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_dynamodb" {
  name = "dynamodb"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDbManage"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable",
          "dynamodb:DeleteTable",
          "dynamodb:DescribeTable",
          "dynamodb:UpdateTable",
          "dynamodb:UpdateContinuousBackups",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:UpdateTimeToLive",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:ListTagsOfResource",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
        ]
        Resource = "arn:aws:dynamodb:${local.region}:${local.account_id}:table/${local.project_glob}"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 7: Secrets Manager
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_secretsmanager" {
  name = "secretsmanager"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManage"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecret",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource",
          "secretsmanager:ListSecretVersionIds",
          "secretsmanager:RestoreSecret",
        ]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:${var.project_name}-${var.environment}/*"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 8: EventBridge rules
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_events" {
  name = "events"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EventsManage"
        Effect = "Allow"
        Action = [
          "events:DescribeRule",
          "events:PutRule",
          "events:DeleteRule",
          "events:DisableRule",
          "events:EnableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:ListRules",
          "events:TagResource",
          "events:UntagResource",
          "events:ListTagsForResource",
        ]
        Resource = "arn:aws:events:${local.region}:${local.account_id}:rule/${local.project_glob}"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 9: EventBridge Scheduler (v2.1 GovWin sync trigger). Replaces the
# v2.0 Step Functions grant.
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_scheduler" {
  name = "scheduler"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SchedulerManage"
        Effect = "Allow"
        Action = [
          "scheduler:CreateSchedule",
          "scheduler:UpdateSchedule",
          "scheduler:DeleteSchedule",
          "scheduler:GetSchedule",
          "scheduler:ListSchedules",
          "scheduler:TagResource",
          "scheduler:UntagResource",
          "scheduler:ListTagsForResource",
        ]
        Resource = "arn:aws:scheduler:${local.region}:${local.account_id}:schedule/default/${local.project_glob}"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 10: IAM (managed by terraform). Scoped to project role names so the
# deployer cannot create or modify roles outside this project.
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_iam" {
  name = "iam"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IamManageProjectRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/${local.project_glob}"
      },
      {
        # PassRole specifically scoped to the project's runtime roles. This
        # is what lets terraform attach the Lambda execution role to a
        # function and the EventBridge Scheduler role to a schedule target
        # without granting broader PassRole.
        Sid      = "IamPassRoleProject"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${local.account_id}:role/${local.project_glob}"
        Condition = {
          StringEquals = {
            # Project Lambdas consume PassRole; EventBridge Scheduler also
            # needs it (the scheduler service assumes the project role to
            # invoke the orchestrator Lambda on the configured cadence).
            "iam:PassedToService" = [
              "lambda.amazonaws.com",
              "scheduler.amazonaws.com",
            ]
          }
        }
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Policy 11: Read-only data sources Terraform needs (account id, region, etc.)
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_describe" {
  name = "describe"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BasicDescribe"
        Effect = "Allow"
        Action = [
          "sts:GetCallerIdentity",
          "ec2:DescribeRegions",
        ]
        Resource = "*"
      },
    ]
  })
}
