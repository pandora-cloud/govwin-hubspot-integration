output "orchestrator_arn" {
  value = aws_lambda_function.orchestrator.arn
}

output "worker_arn" {
  value = aws_lambda_function.worker.arn
}

output "sync_queue_url" {
  value = aws_sqs_queue.sync.url
}

output "sync_queue_arn" {
  value = aws_sqs_queue.sync.arn
}

output "scheduler_name" {
  value = aws_scheduler_schedule.sync.name
}
