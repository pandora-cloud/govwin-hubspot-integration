# Deployment Guide

Step-by-step instructions for deploying the GovWin-to-HubSpot integration on AWS.

## Prerequisites Checklist

- [ ] **Deltek GovWin IQ** subscription with WSAPI V3 access
  - Client ID and Client Secret (from GovWin Admin UI)
  - GovWin username (email) and password
- [ ] **HubSpot** account (Professional or Enterprise tier)
  - Private App created with scopes: `crm.objects.deals.read`, `crm.objects.deals.write`, `crm.objects.companies.read`, `crm.objects.companies.write`, `crm.objects.contacts.read`, `crm.objects.contacts.write`
  - Private App access token
- [ ] **AWS** account with administrator access (or specific IAM permissions for Lambda, Step Functions, DynamoDB, Secrets Manager, EventBridge, SNS, SQS, IAM, CloudWatch)
- [ ] **Terraform** >= 1.5 installed ([install guide](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli))
- [ ] **AWS CLI** configured with credentials (`aws configure`)
- [ ] (Optional) **Python** >= 3.12 for local development and testing

## Step 1: Clone the Repository

```bash
git clone https://github.com/your-org/govwin-hubspot-integration.git
cd govwin-hubspot-integration
```

## Step 2: Create HubSpot Private App

1. Log in to HubSpot as a Super Admin
2. Go to **Settings > Integrations > Private Apps**
3. Click **Create a private app**
4. Name it "GovWin Integration"
5. Under **Scopes**, enable:
   - `crm.objects.deals.read` and `crm.objects.deals.write`
   - `crm.objects.companies.read` and `crm.objects.companies.write`
   - `crm.objects.contacts.read` and `crm.objects.contacts.write`
   - `crm.schemas.deals.read` and `crm.schemas.deals.write`
   - `crm.schemas.companies.read` and `crm.schemas.companies.write`
   - `crm.schemas.contacts.read` and `crm.schemas.contacts.write`
6. Click **Create app** and copy the access token

## Step 3: Get GovWin API Credentials

1. Log in to GovWin IQ as an administrator
2. Navigate to **Admin > Web Service API**
3. Note your **Client ID** and **Client Secret**
4. Note the GovWin **username** (email) and **password** for the API user

## Step 4: Configure Terraform Variables

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars`:

```hcl
# Required - GovWin Credentials
govwin_client_id     = "your-client-id"
govwin_client_secret = "your-client-secret"
govwin_username      = "your-email@company.com"
govwin_password      = "your-password"

# Required - HubSpot Credentials
hubspot_private_app_token = "pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Optional - Customize
aws_region         = "us-east-1"
sync_schedule      = "rate(4 hours)"
notification_email = "alerts@company.com"
govwin_opp_types   = "ALL"
```

> **Security**: `terraform.tfvars` is in `.gitignore` and will never be committed.

## Step 5: Deploy

```bash
cd terraform

# Initialize Terraform (downloads providers)
terraform init

# Preview what will be created
terraform plan

# Deploy (type "yes" when prompted)
terraform apply
```

Terraform will create:
- 2 DynamoDB tables
- 3 Secrets Manager secrets
- 7 Lambda functions + shared layer
- 1 Step Function state machine
- 1 EventBridge rule (scheduled trigger)
- 1 SNS topic (notifications)
- 1 SQS queue (dead letter queue)
- IAM roles and policies
- CloudWatch log groups

## Step 6: Verify Deployment

### Check HubSpot Setup

The `setup_hubspot` Lambda runs automatically during deployment. Verify in HubSpot:
- Go to **Settings > Properties > Deal properties** -- you should see `govwin_*` properties
- Go to **Settings > Objects > Deals > Pipelines** -- you should see "GovWin Pipeline"

### Trigger First Sync

The first scheduled sync will run automatically. To trigger it immediately:

```bash
# Get the state machine ARN from Terraform output
terraform output step_function_arn

# Start execution
aws stepfunctions start-execution \
  --state-machine-arn <arn-from-above> \
  --name "manual-first-sync-$(date +%s)"
```

### Monitor

- **Step Functions Console**: See execution status and step-by-step progress
- **CloudWatch Logs**: Detailed logs for each Lambda function
- **SNS Notifications**: Summary email after each sync (if notification_email is set)

## Step 7: (Optional) Configure SaaSify ACE Connector

If you want to submit synced deals to AWS Partner Central:

1. Ensure the SaaSify ACE Connector is installed from the AWS Marketplace
2. Map the GovWin fields to ACE fields in SaaSify settings (see [ACE Integration Guide](ace-integration.md))
3. After sync, review deals in HubSpot and fill the 3 manual ACE fields
4. Submit to AWS Partner Central via the SaaSify connector

## Updating

To update the integration after pulling new code:

```bash
cd terraform
terraform plan    # Review changes
terraform apply   # Apply updates
```

## Uninstalling

```bash
cd terraform
terraform destroy   # Removes all AWS resources
```

This will delete all AWS resources. HubSpot custom properties and deals created by the integration will remain in HubSpot and must be removed manually if desired.

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|---|---|---|
| GovWin auth fails (401) | Bad credentials or locked account | Verify credentials; account locks for 30 min after 5 failed attempts |
| Rate limit errors (403) | Exceeded 4,000 calls/hour | The integration handles this automatically; if persistent, increase `sync_schedule` interval |
| HubSpot 429 errors | Exceeded 100 req/10s | Built-in backoff handles this; check for other integrations consuming rate limit |
| Missing deals in HubSpot | Opportunity type filtered out | Check `govwin_opp_types` variable |
| Step Function timeout | Very large initial sync | Increase `max_concurrency` or run initial sync in stages |

### Checking Logs

```bash
# List recent Lambda invocations
aws logs filter-log-events \
  --log-group-name /aws/lambda/govwin-hubspot-discover-changes \
  --start-time $(date -d '1 hour ago' +%s000)

# Check Step Function execution
aws stepfunctions describe-execution \
  --execution-arn <execution-arn>
```
