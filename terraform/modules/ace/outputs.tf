output "webhook_target_url" {
  description = "Public URL HubSpot should POST webhooks to"
  value       = "https://${aws_apigatewayv2_api.webhook.id}.execute-api.${var.aws_region}.amazonaws.com/hubspot"
}

output "submit_queue_url" {
  value = aws_sqs_queue.submit.url
}

output "update_queue_url" {
  value = aws_sqs_queue.update.url
}

output "submit_dlq_url" {
  value = aws_sqs_queue.submit_dlq.url
}

output "submit_dlq_arn" {
  value = aws_sqs_queue.submit_dlq.arn
}

output "update_dlq_url" {
  value = aws_sqs_queue.update_dlq.url
}

output "hubspot_webhook_secret_arn" {
  value = aws_secretsmanager_secret.hubspot_webhook.arn
}

output "hubspot_webhook_secret_name" {
  value = aws_secretsmanager_secret.hubspot_webhook.name
}

output "hubspot_webhook_receiver_arn" {
  value = aws_lambda_function.hubspot_webhook_receiver.arn
}

output "submit_to_ace_arn" {
  value = aws_lambda_function.submit_to_ace.arn
}

output "update_in_ace_arn" {
  value = aws_lambda_function.update_in_ace.arn
}

output "handle_ace_event_arn" {
  value = aws_lambda_function.handle_ace_event.arn
}

output "setup_hubspot_webhooks_arn" {
  value = aws_lambda_function.setup_hubspot_webhooks.arn
}
