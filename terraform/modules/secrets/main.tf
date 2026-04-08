variable "name_prefix" {
  type = string
}
variable "govwin_client_id" {
  type      = string
  sensitive = true
}
variable "govwin_client_secret" {
  type      = string
  sensitive = true
}
variable "govwin_username" {
  type      = string
  sensitive = true
}
variable "govwin_password" {
  type      = string
  sensitive = true
}
variable "hubspot_private_app_token" {
  type      = string
  sensitive = true
}

resource "aws_secretsmanager_secret" "govwin" {
  name                    = "${var.name_prefix}/govwin"
  description             = "GovWin API credentials"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "govwin" {
  secret_id = aws_secretsmanager_secret.govwin.id
  secret_string = jsonencode({
    client_id     = var.govwin_client_id
    client_secret = var.govwin_client_secret
    username      = var.govwin_username
    password      = var.govwin_password
  })
}

resource "aws_secretsmanager_secret" "hubspot" {
  name                    = "${var.name_prefix}/hubspot"
  description             = "HubSpot private app token"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "hubspot" {
  secret_id = aws_secretsmanager_secret.hubspot.id
  secret_string = jsonencode({
    private_app_token = var.hubspot_private_app_token
  })
}

resource "aws_secretsmanager_secret" "govwin_tokens" {
  name                    = "${var.name_prefix}/govwin-tokens"
  description             = "GovWin OAuth tokens (managed at runtime by Lambda)"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "govwin_tokens" {
  secret_id = aws_secretsmanager_secret.govwin_tokens.id
  secret_string = jsonencode({
    access_token  = ""
    refresh_token = ""
    expires_at    = 0
  })
}

output "govwin_secret_arn" { value = aws_secretsmanager_secret.govwin.arn }
output "govwin_secret_name" { value = aws_secretsmanager_secret.govwin.name }
output "hubspot_secret_arn" { value = aws_secretsmanager_secret.hubspot.arn }
output "hubspot_secret_name" { value = aws_secretsmanager_secret.hubspot.name }
output "govwin_tokens_secret_arn" { value = aws_secretsmanager_secret.govwin_tokens.arn }
output "govwin_tokens_secret_name" { value = aws_secretsmanager_secret.govwin_tokens.name }
