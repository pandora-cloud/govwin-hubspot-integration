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

## Step 2: Create HubSpot API Token

HubSpot offers two methods for API authentication. Use **Service Keys** (recommended) or Private Apps (legacy).

### Option A: Service Key (Recommended — 2026+)

Service Keys are HubSpot's modern replacement for Private Apps. They provide a non-expiring bearer token for API-only integrations.

1. Log in to HubSpot as a **Super Admin**
2. Go to **Settings > Integrations > Service Keys**
3. Click **"Create service key"**
4. Name it `GovWin Integration`
5. Select these scopes:
   - `crm.objects.deals.read` and `crm.objects.deals.write`
   - `crm.objects.companies.read` and `crm.objects.companies.write`
   - `crm.objects.contacts.read` and `crm.objects.contacts.write`
   - `crm.schemas.deals.read` and `crm.schemas.deals.write`
   - `crm.schemas.companies.read` and `crm.schemas.companies.write`
   - `crm.schemas.contacts.read` and `crm.schemas.contacts.write`
6. Click **Create** and copy the token (starts with `pat-na1-` or `pat-na2-`)

> **Note:** Service Keys are in public beta (as of February 2026). If you don't see "Service Keys" in your HubSpot settings, use Option B below.

### Option B: Private App (Legacy — still works)

1. Log in to HubSpot as a **Super Admin**
2. Go to **Settings > Integrations > Private Apps**
3. Click **"Create a private app"**
4. Name it `GovWin Integration`
5. Under the **Scopes** tab, enable the same 12 scopes listed in Option A
6. Click **Create app** and copy the access token

> **Note:** Private Apps are marked as "legacy" by HubSpot. They still work and have no announced sunset date, but new integrations should prefer Service Keys when available.

### Token Format

Both options produce a bearer token in the same format:
```
pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```
This token does not expire. Store it securely — anyone with this token has full read/write access to your CRM data within the granted scopes.

## Step 3: Get GovWin API Credentials

You need 4 values from GovWin: a Client ID, Client Secret, username, and password. The integration uses OAuth2 password grant to authenticate.

### 3a. Get Client ID and Client Secret

Your organization's GovWin administrator provisions API access:

1. Log in to [GovWin IQ](https://iq.govwin.com) as an **administrator**
2. Navigate to **Admin > Web Service API** (or contact your GovWin account manager to enable WSAPI access)
3. In the API management section, create or locate your **Client ID** and **Client Secret**
4. Copy both values — these are organization-level credentials shared across all API users

> **Note:** If you don't see the Web Service API option in Admin, your GovWin subscription may not include WSAPI access. Contact Deltek GovWin support or your account manager to add it.

### 3b. Get Username and Password

The API authenticates as a specific GovWin user:

1. Use an existing GovWin user account, OR create a dedicated API user (recommended for production)
2. The **username** is the user's email address (e.g., `api-user@company.com`)
3. The **password** is the user's GovWin login password

> **Important security notes:**
> - The API user's permissions determine what data is accessible. A user with access to Federal opportunities will only sync Federal data.
> - GovWin accounts **lock for 30 minutes after 5 failed authentication attempts**. Use a dedicated API user to avoid locking out a human user.
> - GovWin passwords may need to be updated periodically (check with your admin). If the password changes, update it in AWS Secrets Manager or redeploy with the new value.
> - The API rate limit of **4,000 calls/hour** is shared across all users in your organization. If other tools also use the WSAPI, coordinate to avoid exhausting the limit.

### 3c. Verify Your Credentials

Before deploying, you can test your credentials locally:

```bash
# Copy and fill in your .env file
cp .env.example .env
# Edit .env with your GovWin credentials

# Load environment and run validation
source .env
make validate --skip-hubspot
```

Or test manually with curl:
```bash
curl -X POST https://services.govwin.com/neo-ws/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET&grant_type=password&username=YOUR_EMAIL&password=YOUR_PASSWORD&scope=read"
```

A successful response returns an `access_token` and `refresh_token`.

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

## Step 6: Mark Opportunities for Sync

By default, only opportunities your BD team explicitly marks in GovWin IQ will sync to HubSpot. This is controlled by the `govwin_marked_version` variable (default: `"2.2"`).

**To mark an opportunity for sync:**
1. Open the opportunity in GovWin IQ
2. Click **"Add to Web Services Download"** on the opportunity detail page
3. The opportunity will be picked up on the next scheduled sync

**Alternative filtering modes** (set in `terraform.tfvars`):
- `govwin_saved_search_id = "12345"` -- sync opps matching a GovWin saved search
- `govwin_bookmarked_only = true` -- sync only bookmarked opps
- `govwin_marked_version = ""` -- disable filtering, sync all opps (not recommended for production)

## Step 7: Verify Deployment

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
