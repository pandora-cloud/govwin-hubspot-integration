output "govwin_orchestrator_arn" {
  description = "ARN of the GovWin sync orchestrator Lambda (replaces the v2.0 Step Function)"
  value       = module.govwin_sync.orchestrator_arn
}

output "govwin_worker_arn" {
  description = "ARN of the GovWin sync worker Lambda"
  value       = module.govwin_sync.worker_arn
}

output "govwin_sync_queue_url" {
  description = "SQS queue URL the orchestrator fans batches into; the worker drains it"
  value       = module.govwin_sync.sync_queue_url
}

output "govwin_sync_schedule" {
  description = "EventBridge Scheduler name driving the orchestrator"
  value       = module.govwin_sync.scheduler_name
}

output "sync_state_table" {
  description = "DynamoDB table name for sync state"
  value       = module.dynamodb.sync_state_table_name
}

output "entity_mappings_table" {
  description = "DynamoDB table name for entity mappings"
  value       = module.dynamodb.entity_mappings_table_name
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
