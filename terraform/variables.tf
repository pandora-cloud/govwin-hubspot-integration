###############################################################################
# Required Variables — deployer must provide
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
# Optional Variables — sensible defaults provided
###############################################################################

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
  description = "EventBridge schedule expression for sync frequency"
  type        = string
  default     = "rate(4 hours)"
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
  description = "Optional GovWin saved search ID to use instead of broad search"
  type        = string
  default     = ""
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
