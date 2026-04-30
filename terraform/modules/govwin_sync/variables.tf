variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "sync_schedule" {
  description = "EventBridge Scheduler expression for the GovWin sync orchestrator."
  type        = string
  default     = "rate(1 hour)"
}

variable "lambda_role_arn" {
  description = "ARN of the shared Lambda execution role from the lambda module."
  type        = string
}

variable "lambda_role_name" {
  description = "Name of the shared Lambda execution role (for attaching extra policies)."
  type        = string
}

variable "lambda_layer_arn" {
  type = string
}

variable "lambda_source_zip" {
  type = string
}

variable "lambda_source_hash" {
  type = string
}

variable "lambda_env" {
  description = "Common environment variables (DynamoDB tables, secret names, GovWin config) shared with the rest of the project."
  type        = map(string)
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "worker_concurrency" {
  description = "reservedConcurrentExecutions for the worker Lambda. Replaces the Step Function Map maxConcurrency knob."
  type        = number
  default     = 2
}
