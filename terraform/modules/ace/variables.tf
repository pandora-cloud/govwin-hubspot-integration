# Variables for the ACE (AWS Partner Central) module.

variable "name_prefix" {
  type        = string
  description = "Project + environment prefix used for all resource names"
}

variable "aws_region" {
  type        = string
  description = "AWS region (must be us-east-1 for partnercentral-selling)"
  default     = "us-east-1"
}

variable "lambda_role_arn" {
  type        = string
  description = "Existing Lambda execution role from the lambda module; gets ACE permissions attached"
}

variable "lambda_role_name" {
  type        = string
  description = "Name of the existing Lambda execution role (for attaching policies)"
}

variable "lambda_layer_arn" {
  type        = string
  description = "Shared Python dependencies layer ARN from the lambda module"
}

variable "lambda_source_zip" {
  type        = string
  description = "Path to the source zip produced by the lambda module"
}

variable "lambda_source_hash" {
  type        = string
  description = "Source code hash from the lambda module (for change detection)"
}

variable "sync_state_table_arn" {
  type        = string
  description = "ARN of the sync state DynamoDB table"
}

variable "sync_state_table_name" {
  type = string
}

variable "entity_mappings_table_arn" {
  type = string
}

variable "entity_mappings_table_name" {
  type = string
}

variable "hubspot_secret_arn" {
  type        = string
  description = "Existing HubSpot REST-API token secret (for the deal lookup calls)"
}

variable "hubspot_secret_name" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# -- ACE configuration ---

variable "ace_catalog" {
  type        = string
  description = "AWS Partner Central catalog: Sandbox (testing) or AWS (production)"
  default     = "Sandbox"
  validation {
    condition     = contains(["Sandbox", "AWS"], var.ace_catalog)
    error_message = "ace_catalog must be Sandbox or AWS."
  }
}

variable "ace_default_solution_id" {
  type        = string
  description = "Default Partner Central Solution ID (e.g. S-1234567)"
}

variable "ace_default_involvement_type" {
  type    = string
  default = "Co-Sell"
}

variable "ace_default_visibility" {
  type    = string
  default = "Full"
}

variable "ace_partner_company_name" {
  type        = string
  description = <<-EOT
    Partner company legal name surfaced as ExpectedCustomerSpend.TargetCompany in
    AWS Partner Central. Set per deployment to the deploying partner's legal name
    (e.g. "Acme Cloud LLC"). Defaults to a placeholder so unconfigured deploys
    do not write someone else's company name to AWS.
  EOT
  default     = "Partner Company"
}

variable "ace_trigger_stages" {
  type        = string
  description = <<-EOT
    Comma-separated HubSpot deal stage internal IDs (numeric, HubSpot-assigned)
    that trigger ACE submission. Production deployments must override the
    label-style default with the numeric stage id from the HubSpot pipeline
    editor (e.g. "3590200042"). See docs/ace-integration.md.
  EOT
  default     = "submit_to_aws,submitted_to_aws"
}

# -- HubSpot webhook configuration ---

variable "hubspot_webhook_app_id" {
  type        = string
  description = "HubSpot developer-platform app id (numeric, from hs project upload)"
}

variable "hubspot_webhook_client_secret" {
  type        = string
  description = "HubSpot client secret used for X-HubSpot-Signature-v3 validation"
  sensitive   = true
}

variable "sns_topic_arn" {
  description = "SNS topic ARN for mapping-error and terminal-failure alerts."
  type        = string
}
