locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# -----------------------------------------------------------------------------
# Secrets
# -----------------------------------------------------------------------------

module "secrets" {
  source = "./modules/secrets"

  name_prefix               = local.name_prefix
  govwin_client_id          = var.govwin_client_id
  govwin_client_secret      = var.govwin_client_secret
  govwin_username           = var.govwin_username
  govwin_password           = var.govwin_password
  hubspot_private_app_token = var.hubspot_private_app_token
}

# -----------------------------------------------------------------------------
# DynamoDB
# -----------------------------------------------------------------------------

module "dynamodb" {
  source = "./modules/dynamodb"

  name_prefix = local.name_prefix
}

# -----------------------------------------------------------------------------
# Monitoring
# -----------------------------------------------------------------------------

module "monitoring" {
  source = "./modules/monitoring"

  name_prefix          = local.name_prefix
  enable_notifications = var.enable_notifications
  notification_email   = var.notification_email
}

# -----------------------------------------------------------------------------
# Lambda
# -----------------------------------------------------------------------------

module "lambda" {
  source = "./modules/lambda"

  name_prefix                = local.name_prefix
  aws_profile                = var.aws_profile
  aws_region                 = var.aws_region
  sync_state_table_name      = module.dynamodb.sync_state_table_name
  sync_state_table_arn       = module.dynamodb.sync_state_table_arn
  entity_mappings_table_name = module.dynamodb.entity_mappings_table_name
  entity_mappings_table_arn  = module.dynamodb.entity_mappings_table_arn
  govwin_secret_arn          = module.secrets.govwin_secret_arn
  hubspot_secret_arn         = module.secrets.hubspot_secret_arn
  govwin_tokens_secret_arn   = module.secrets.govwin_tokens_secret_arn
  govwin_secret_name         = module.secrets.govwin_secret_name
  hubspot_secret_name        = module.secrets.hubspot_secret_name
  govwin_tokens_secret_name  = module.secrets.govwin_tokens_secret_name
  sns_topic_arn              = module.monitoring.sns_topic_arn
  dlq_url                    = module.monitoring.dlq_url
  dlq_arn                    = module.monitoring.dlq_arn
  govwin_opp_types           = var.govwin_opp_types
  govwin_market              = var.govwin_market
  govwin_saved_search_id     = var.govwin_saved_search_id
  govwin_bookmarked_only     = var.govwin_bookmarked_only
  govwin_marked_version      = var.govwin_marked_version
  initial_lookback_days      = var.initial_lookback_days
  batch_size                 = var.batch_size
  max_concurrency            = var.max_concurrency
  log_retention_days         = var.log_retention_days
}

# -----------------------------------------------------------------------------
# ACE (AWS Partner Central) submission half
# -----------------------------------------------------------------------------

module "ace" {
  source = "./modules/ace"

  name_prefix                   = local.name_prefix
  aws_region                    = var.aws_region
  lambda_role_arn               = module.lambda.lambda_role_arn
  lambda_role_name              = module.lambda.lambda_role_name
  lambda_layer_arn              = module.lambda.lambda_layer_arn
  lambda_source_zip             = module.lambda.lambda_source_zip
  lambda_source_hash            = module.lambda.lambda_source_hash
  sync_state_table_arn          = module.dynamodb.sync_state_table_arn
  sync_state_table_name         = module.dynamodb.sync_state_table_name
  entity_mappings_table_arn     = module.dynamodb.entity_mappings_table_arn
  entity_mappings_table_name    = module.dynamodb.entity_mappings_table_name
  hubspot_secret_arn            = module.secrets.hubspot_secret_arn
  hubspot_secret_name           = module.secrets.hubspot_secret_name
  log_retention_days            = var.log_retention_days
  ace_catalog                   = var.ace_catalog
  ace_default_solution_id       = var.ace_default_solution_id
  ace_default_involvement_type  = var.ace_default_involvement_type
  ace_default_visibility        = var.ace_default_visibility
  ace_trigger_stages            = var.ace_trigger_stages
  hubspot_webhook_app_id        = var.hubspot_webhook_app_id
  hubspot_webhook_client_secret = var.hubspot_webhook_client_secret
}

# -----------------------------------------------------------------------------
# Step Function
# -----------------------------------------------------------------------------

module "step_function" {
  source = "./modules/step_function"

  name_prefix           = local.name_prefix
  sync_schedule         = var.sync_schedule
  max_concurrency       = var.max_concurrency
  authenticate_arn      = module.lambda.authenticate_arn
  discover_changes_arn  = module.lambda.discover_changes_arn
  fetch_opp_details_arn = module.lambda.fetch_opp_details_arn
  sync_to_hubspot_arn   = module.lambda.sync_to_hubspot_arn
  update_sync_state_arn = module.lambda.update_sync_state_arn
  handle_error_arn      = module.lambda.handle_error_arn
  lambda_role_arns      = module.lambda.all_lambda_arns
}
