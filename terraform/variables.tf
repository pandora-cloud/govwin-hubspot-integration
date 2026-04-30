###############################################################################
# Required Variables - deployer must provide
###############################################################################

variable "govwin_client_id" {
  description = "GovWin WSAPI client ID"
  type        = string
  sensitive   = true
}

variable "govwin_client_secret" {
  description = "GovWin WSAPI client secret"
  type        = string
  sensitive   = true
}

variable "govwin_username" {
  description = "GovWin user email for API access"
  type        = string
  sensitive   = true
}

variable "govwin_password" {
  description = "GovWin user password for API access"
  type        = string
  sensitive   = true
}

variable "hubspot_private_app_token" {
  description = "HubSpot private app access token"
  type        = string
  sensitive   = true
}

###############################################################################
# Optional Variables - sensible defaults provided
###############################################################################

variable "aws_profile" {
  description = "AWS CLI profile name for authentication"
  type        = string
  default     = "default"
}

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (prod, staging, dev)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "environment must be one of: prod, staging, dev."
  }
}

variable "project_name" {
  description = "Project name prefix for resource naming"
  type        = string
  default     = "govwin-hubspot"
}

variable "sync_schedule" {
  description = "EventBridge schedule expression for the GovWin -> HubSpot sync frequency. Defaults to hourly."
  type        = string
  default     = "rate(1 hour)"
}

variable "govwin_opp_types" {
  description = "GovWin opportunity types to sync (OPP, BID, TNS, FBO, OPN, TOP, ALL)"
  type        = string
  default     = "ALL"

  validation {
    condition     = contains(["OPP", "BID", "TNS", "FBO", "OPN", "TOP", "ALL"], var.govwin_opp_types)
    error_message = "govwin_opp_types must be one of: OPP, BID, TNS, FBO, OPN, TOP, ALL."
  }
}

variable "govwin_market" {
  description = "Market filter: Federal, SLED, or empty string for both"
  type        = string
  default     = ""

  validation {
    condition     = contains(["", "Federal", "SLED"], var.govwin_market)
    error_message = "govwin_market must be 'Federal', 'SLED', or empty string for both."
  }
}

variable "govwin_saved_search_id" {
  description = "Optional GovWin saved search ID - only sync opps matching this search"
  type        = string
  default     = ""
}

variable "govwin_bookmarked_only" {
  description = "Only sync opportunities the user has bookmarked in GovWin"
  type        = bool
  default     = false
}

variable "govwin_marked_version" {
  description = "Only sync opps marked for download in GovWin: '2.2' (Web Services), '2' (Deltek CRM), or '' (disabled, sync all)"
  type        = string
  default     = "2.2"

  validation {
    condition     = contains(["", "2", "2.2"], var.govwin_marked_version)
    error_message = "govwin_marked_version must be '2.2' (Web Services), '2' (Deltek CRM), or '' (disabled)."
  }
}

variable "initial_lookback_days" {
  description = "How many days to look back on first sync"
  type        = number
  default     = 365
}

variable "max_concurrency" {
  description = "Max parallel batches in Step Function Map state"
  type        = number
  default     = 2

  validation {
    condition     = var.max_concurrency >= 1 && var.max_concurrency <= 5
    error_message = "max_concurrency must be between 1 and 5."
  }
}

variable "batch_size" {
  description = "Number of opportunities per batch in Map state (max 25 to stay within Step Function 256KB payload limit)"
  type        = number
  default     = 10

  validation {
    condition     = var.batch_size >= 1 && var.batch_size <= 25
    error_message = "batch_size must be between 1 and 25 to stay within Step Function payload limits."
  }
}

variable "enable_notifications" {
  description = "Enable SNS email notifications for sync events"
  type        = bool
  default     = true
}

variable "notification_email" {
  description = "Email address for sync notifications (required if enable_notifications is true)"
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "tags" {
  description = "Additional tags for all resources"
  type        = map(string)
  default     = {}
}

variable "deployer_role_arn" {
  description = <<-EOT
    ARN of the deployer IAM role created by terraform/bootstrap. When set,
    the provider assumes this role for all resource operations, so the
    terraform CLI session itself only needs sts:AssumeRole on the deployer
    role's ARN. Leave empty to use the configured aws_profile directly
    (e.g. during the bootstrap phase, or for ad-hoc local development).
  EOT
  type        = string
  default     = ""
}

# -----------------------------------------------------------------------------
# ACE (AWS Partner Central) configuration
# -----------------------------------------------------------------------------

variable "ace_catalog" {
  description = "AWS Partner Central catalog: Sandbox (testing) or AWS (production)"
  type        = string
  default     = "Sandbox"
  validation {
    condition     = contains(["Sandbox", "AWS"], var.ace_catalog)
    error_message = "ace_catalog must be Sandbox or AWS."
  }
}

variable "ace_default_solution_id" {
  description = "Default Partner Central Solution ID (e.g. S-0051246 for Pandora Cloud Professional Services)"
  type        = string
}

variable "ace_default_involvement_type" {
  description = "AWS involvement type for engagement submissions"
  type        = string
  default     = "Co-Sell"
}

variable "ace_default_visibility" {
  description = "Visibility level for engagements"
  type        = string
  default     = "Full"
}

variable "ace_trigger_stages" {
  description = <<-EOT
    Comma-separated HubSpot deal stage internal IDs (numeric, HubSpot-assigned)
    that trigger ACE submission. Production deployments MUST override this with
    the numeric stage id from the HubSpot pipeline editor (e.g. "3590200042"
    for a "Submit to AWS" stage in the Government pipeline). The default below
    uses label-style placeholders so a first-deploy plan/apply succeeds before
    the operator has created the stages; the override step is documented in
    docs/ace-integration.md and docs/phase4-runbook.md.
  EOT
  type        = string
  default     = "submit_to_aws,submitted_to_aws"
}

variable "hubspot_webhook_app_id" {
  description = "HubSpot developer-platform app id (numeric string from hs project upload)"
  type        = string
}

variable "hubspot_webhook_client_secret" {
  description = "HubSpot client secret used for X-HubSpot-Signature-v3 validation"
  type        = string
  sensitive   = true
}
