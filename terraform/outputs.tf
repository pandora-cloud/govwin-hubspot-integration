output "step_function_arn" {
  description = "ARN of the sync Step Function state machine"
  value       = module.step_function.state_machine_arn
}

output "step_function_name" {
  description = "Name of the sync Step Function state machine"
  value       = module.step_function.state_machine_name
}

output "sync_state_table" {
  description = "DynamoDB table name for sync state"
  value       = module.dynamodb.sync_state_table_name
}

output "entity_mappings_table" {
  description = "DynamoDB table name for entity mappings"
  value       = module.dynamodb.entity_mappings_table_name
}

output "eventbridge_rule" {
  description = "EventBridge rule name for scheduled sync"
  value       = module.step_function.eventbridge_rule_name
}

output "sns_topic_arn" {
  description = "SNS topic ARN for notifications"
  value       = module.monitoring.sns_topic_arn
}

output "dlq_url" {
  description = "SQS dead letter queue URL"
  value       = module.monitoring.dlq_url
}

# -----------------------------------------------------------------------------
# ACE outputs
# -----------------------------------------------------------------------------

output "hubspot_webhook_target_url" {
  description = "Public URL HubSpot should POST webhooks to. Paste this into webhooks-hsmeta.json's targetUrl, then run hs project upload."
  value       = module.ace.webhook_target_url
}

output "ace_submit_queue_url" {
  description = "SQS queue carrying submit-to-AWS events"
  value       = module.ace.submit_queue_url
}

output "ace_update_queue_url" {
  description = "SQS queue carrying update-to-AWS events"
  value       = module.ace.update_queue_url
}

output "ace_submit_dlq_url" {
  description = "DLQ for failed submission attempts"
  value       = module.ace.submit_dlq_url
}
