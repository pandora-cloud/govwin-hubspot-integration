# HubSpot webhook signing secret (separate from the existing private-app
# token because the new developer-platform app has its own client secret
# used for X-HubSpot-Signature-v3 validation).

resource "aws_secretsmanager_secret" "hubspot_webhook" {
  name        = "${var.name_prefix}/hubspot-webhook"
  description = "HubSpot webhook client secret for X-HubSpot-Signature-v3 validation and the app id used for subscription registration"
}

resource "aws_secretsmanager_secret_version" "hubspot_webhook" {
  secret_id = aws_secretsmanager_secret.hubspot_webhook.id
  secret_string = jsonencode({
    app_id        = var.hubspot_webhook_app_id
    client_secret = var.hubspot_webhook_client_secret
  })
}
