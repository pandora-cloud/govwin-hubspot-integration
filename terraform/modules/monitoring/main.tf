variable "name_prefix" {
  type = string
}
variable "enable_notifications" {
  type    = bool
  default = true
}
variable "notification_email" {
  type    = string
  default = ""
}

resource "aws_sns_topic" "sync_notifications" {
  name              = "${var.name_prefix}-notifications"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.enable_notifications && var.notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.sync_notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

resource "aws_sqs_queue" "dlq" {
  name                       = "${var.name_prefix}-dlq"
  message_retention_seconds  = 1209600 # 14 days
  sqs_managed_sse_enabled    = true
}

output "sns_topic_arn" {
  value = aws_sns_topic.sync_notifications.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}
