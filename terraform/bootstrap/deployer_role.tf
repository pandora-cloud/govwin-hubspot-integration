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
  tags        = local.base_tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = var.deployer_principal_arns
        }
        Action = "sts:AssumeRole"
        Condition = {
          # Require MFA when assuming the deployer role for human deployments.
          # Service-linked principals (e.g. CI roles) can bypass via
          # session tokens; document this in the README.
          Bool = { "aws:MultiFactorAuthPresent" = "true" }
        }
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
        Sid    = "LogsGroups"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy",
          "logs:DeleteRetentionPolicy",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsForResource",
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${local.project_glob}*"
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
# Policy 9: Step Functions (v1 sync state machine)
# --------------------------------------------------------------------------

resource "aws_iam_role_policy" "deployer_states" {
  name = "states"
  role = aws_iam_role.deployer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StatesManage"
        Effect = "Allow"
        Action = [
          "states:CreateStateMachine",
          "states:DeleteStateMachine",
          "states:DescribeStateMachine",
          "states:UpdateStateMachine",
          "states:ListTagsForResource",
          "states:TagResource",
          "states:UntagResource",
          "states:StartExecution",
        ]
        Resource = "arn:aws:states:${local.region}:${local.account_id}:stateMachine:${local.project_glob}"
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
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/${local.project_glob}"
      },
      {
        # PassRole specifically scoped to the project's runtime roles. This
        # is what lets terraform attach the Lambda execution role to a
        # function and the Step Functions execution role to a state machine
        # without granting broader PassRole.
        Sid      = "IamPassRoleProject"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${local.account_id}:role/${local.project_glob}"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "lambda.amazonaws.com",
              "states.amazonaws.com",
              "events.amazonaws.com",
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
