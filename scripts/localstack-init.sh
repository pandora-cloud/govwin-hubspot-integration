#!/bin/bash
# Initialize LocalStack with AWS resources matching Terraform definitions.
# This script runs automatically when LocalStack is ready (mounted in /etc/localstack/init/ready.d/).

set -euo pipefail

echo "=== Initializing LocalStack resources ==="

# --- DynamoDB Tables ---
echo "Creating DynamoDB tables..."

awslocal dynamodb create-table \
  --table-name govwin-hubspot-dev-sync-state \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1

awslocal dynamodb create-table \
  --table-name govwin-hubspot-dev-entity-mappings \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1

echo "DynamoDB tables created."

# --- Secrets Manager ---
echo "Creating Secrets Manager secrets..."

awslocal secretsmanager create-secret \
  --name govwin-hubspot-dev/govwin \
  --secret-string '{"client_id":"PLACEHOLDER","client_secret":"PLACEHOLDER","username":"PLACEHOLDER","password":"PLACEHOLDER"}' \
  --region us-east-1

awslocal secretsmanager create-secret \
  --name govwin-hubspot-dev/hubspot \
  --secret-string '{"private_app_token":"PLACEHOLDER"}' \
  --region us-east-1

awslocal secretsmanager create-secret \
  --name govwin-hubspot-dev/govwin-tokens \
  --secret-string '{"access_token":"","refresh_token":"","expires_at":0}' \
  --region us-east-1

echo "Secrets Manager secrets created."

# --- SNS Topic ---
echo "Creating SNS topic..."
awslocal sns create-topic \
  --name govwin-hubspot-dev-notifications \
  --region us-east-1

# --- SQS Queue ---
echo "Creating SQS DLQ..."
awslocal sqs create-queue \
  --queue-name govwin-hubspot-dev-dlq \
  --region us-east-1

echo ""
echo "=== LocalStack initialization complete ==="
echo ""
echo "Resources created:"
echo "  DynamoDB:  govwin-hubspot-dev-sync-state"
echo "  DynamoDB:  govwin-hubspot-dev-entity-mappings"
echo "  Secrets:   govwin-hubspot-dev/govwin"
echo "  Secrets:   govwin-hubspot-dev/hubspot"
echo "  Secrets:   govwin-hubspot-dev/govwin-tokens"
echo "  SNS:       govwin-hubspot-dev-notifications"
echo "  SQS:       govwin-hubspot-dev-dlq"
echo ""
echo "To populate secrets with real credentials, run:"
echo "  awslocal secretsmanager put-secret-value --secret-id govwin-hubspot-dev/govwin --secret-string '{...}'"
