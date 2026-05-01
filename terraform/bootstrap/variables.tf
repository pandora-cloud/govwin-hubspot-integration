variable "project_name" {
  description = "Project prefix for all bootstrap resources (e.g. govwin-hubspot)"
  type        = string
  default     = "govwin-hubspot"
}

variable "environment" {
  description = "Environment name (prod, dev, staging)"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region. Must be us-east-1 because partnercentral-selling is us-east-1 only."
  type        = string
  default     = "us-east-1"
  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "Partner Central Selling API is only in us-east-1; this project must run there."
  }
}

variable "deployer_principal_arns" {
  description = <<-EOT
    IAM principals (users, roles) that may assume the deployer role for
    day-to-day terraform apply. Each entry is a full ARN. Empty list is
    rejected because that produces an unusable role.

    Examples:
      - arn:aws:iam::123456789012:user/jane
      - arn:aws:iam::123456789012:role/AdminRole
      - arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdminAccess_xxxxx
  EOT
  type        = list(string)
  validation {
    condition     = length(var.deployer_principal_arns) > 0
    error_message = "deployer_principal_arns must contain at least one ARN."
  }
}

variable "require_mfa_to_assume_deployer" {
  description = <<-EOT
    Whether the deployer role's trust policy requires MFA on the assume call.
    Default true for compliance posture. Set to false ONLY when bootstrapping
    against an account where the deployer principals do not have MFA-stamped
    credentials yet (e.g. early sandbox testing with regular access keys).
    Production must keep this true.
  EOT
  type        = bool
  default     = true
}

variable "acknowledge_no_mfa_for_sandbox_only" {
  description = <<-EOT
    Explicit override that lets `environment == "prod"` apply without MFA on
    the deployer role's trust policy. Only acceptable when the account is
    being used purely for sandbox testing of the integration before any real
    AWS Partner Central data exists. Flip to false (or delete the variable)
    before any real production traffic reaches the account.

    Use of this override requires both `acknowledge_no_mfa_justification`
    (a non-empty written reason) and `acknowledge_no_mfa_expires_at` (an
    ISO-8601 date in the future). The bootstrap precondition fails if the
    justification is empty or the expiry is in the past.
  EOT
  type        = bool
  default     = false
}

variable "acknowledge_no_mfa_justification" {
  description = <<-EOT
    Free-text justification for using the no-MFA override. Stored as a tag
    on the deployer role so audit tooling (Config rules, CloudTrail Lake)
    can surface why MFA was disabled. Required when
    acknowledge_no_mfa_for_sandbox_only is true. Example:
    "Sandbox account 123456789012 - pre-production smoke testing only;
    no AWS catalog data; MFA enforced post 2026-06-01."
  EOT
  type        = string
  default     = ""
}

variable "acknowledge_no_mfa_expires_at" {
  description = <<-EOT
    ISO-8601 date (YYYY-MM-DD) after which the no-MFA override expires.
    Past this date the bootstrap precondition fails and the next
    `terraform apply` cannot run until either MFA is re-enabled or the
    expiry is bumped (with a renewed justification). Recommended ceiling:
    14 days. Required when acknowledge_no_mfa_for_sandbox_only is true.
  EOT
  type        = string
  default     = ""
  validation {
    condition = (
      var.acknowledge_no_mfa_expires_at == ""
      || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", var.acknowledge_no_mfa_expires_at))
    )
    error_message = "acknowledge_no_mfa_expires_at must be empty or an ISO-8601 date (YYYY-MM-DD)."
  }
}

variable "state_bucket_force_destroy" {
  description = "Allow terraform destroy to delete a non-empty state bucket. Default false; flip only for tear-down testing."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional tags applied to every resource"
  type        = map(string)
  default     = {}
}
