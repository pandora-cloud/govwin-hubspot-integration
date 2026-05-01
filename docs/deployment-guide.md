# Deployment Guide

Step-by-step instructions for deploying the GovWin-to-HubSpot integration on AWS.

## Prerequisites checklist

### AWS-side (upstream of this project)

These are AWS account-level prerequisites that this project does **not** automate. They depend on Pandora's relationship with AWS Partner Network and need to be in place before you deploy.

- [ ] **AWS Partner Central account** in good standing. See the [AWS Partner Network onboarding guide](https://aws.amazon.com/partners/welcome/) for the broader registration flow.
- [ ] **At least one Approved Solution** registered in Partner Central. Verify with:
  ```
  aws partnercentral-selling list-solutions --catalog AWS --region us-east-1 \
    --query 'SolutionSummaries[?Status==`Active`].{Id:Id,Name:Name}'
  ```
  If this is empty, register a Solution in the Partner Central UI under **Sell -> My Solutions** before continuing. Approval typically takes 24-72 hours.
- [ ] **AWS Marketplace seller linking** is **not required** for this project. We submit co-sell engagements via `partnercentral-selling`, which does not transact through Marketplace. Set this up only if you separately need Marketplace functionality.

### Tooling on your machine

- [ ] **Terraform** >= 1.11 (we use the native S3 lockfile, `use_lockfile = true`)
- [ ] **AWS CLI** v2 configured
- [ ] **Python** >= 3.12 for the Lambda layer build
- [ ] **HubSpot CLI** for the developer-platform app: `npm install -g @hubspot/cli`

### Credentials and accounts

- [ ] **Deltek GovWin IQ** subscription with WSAPI V3 access (Client ID, Client Secret, username, password)
- [ ] **HubSpot Professional or Enterprise** with two app-style integrations:
  - **Existing private-app token** for REST API calls (`crm.objects.deals/companies/contacts.read+write`, schemas read+write)
  - **New developer-platform app** (`hs project create`) for webhook delivery; you'll get an `appId` and `clientSecret` after `hs project upload` completes
- [ ] **AWS account** with **two distinct IAM identities** (see [IAM model](#iam-model) below for details):
  - A **bootstrap operator** identity, used once, with a small scoped policy ([`terraform/bootstrap/policies/bootstrap-operator.json`](../terraform/bootstrap/policies/bootstrap-operator.json))
  - A **deployer identity** that day-to-day deployers use (with `sts:AssumeRole` on the project-scoped deployer role, created by the bootstrap)

> **No identity in this project requires AWS administrator access.** The bootstrap-operator policy is ~30 IAM actions, all scoped to `arn:aws:s3:::govwin-hubspot-*-tfstate-*` and `arn:aws:iam::*:role/govwin-hubspot-*-deployer`. The deployer role's policy is the project's full deploy manifest, scoped to `${name_prefix}-*` resource ARNs.

## IAM model

This project follows the principle of least privilege. Three identities are involved, each with a documented and version-controlled policy:

| Identity | Used by | When | Permissions |
|---|---|---|---|
| **Bootstrap operator** | Security team / one-time setup | Once per environment | `terraform/bootstrap/policies/bootstrap-operator.json` (S3 state bucket + deployer role creation only) |
| **Deployer role** | `terraform apply` for the main module | Every deploy | Created by bootstrap; inline policies in `terraform/bootstrap/deployer_role.tf`. Scoped to `govwin-hubspot-${env}-*` resources. |
| **Lambda execution role** | The deployed Lambdas at runtime | Continuous | Created by `terraform/modules/lambda` and `terraform/modules/ace`. Scoped to specific table / queue / secret ARNs and `partnercentral:Catalog: ${env}` condition. |

The day-to-day deployer's personal IAM identity needs only `sts:AssumeRole` on the deployer role's ARN. CloudTrail records every assumption, so audit logs show "Alice assumed govwin-hubspot-prod-deployer at T1, applied 12 changes."

## Step 1: Clone the Repository

```bash
git clone https://github.com/pandora-cloud-llc/govwin-hubspot-integration.git
cd govwin-hubspot-integration
```

## Step 1a: Run the bootstrap (one-time per environment)

This creates the Terraform state bucket and the project's least-privilege deployer role. After this completes once, the security team deletes the bootstrap-operator credentials and all subsequent deploys go through `sts:AssumeRole`. See [`terraform/bootstrap/README.md`](../terraform/bootstrap/README.md) for the full workflow; the short version:

1. Have your security team create a one-time IAM user with the policy in `terraform/bootstrap/policies/bootstrap-operator.json`. Generate access keys and hand them to the deployer.
2. As the deployer, run:
   ```bash
   cd terraform/bootstrap
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars: set deployer_principal_arns to the IAM users/roles
   # that should be allowed to assume the deployer role for day-N applies.
   AWS_PROFILE=govwin-hubspot-bootstrap terraform init
   AWS_PROFILE=govwin-hubspot-bootstrap terraform apply
   ```
3. Capture the outputs (`state_bucket_name`, `deployer_role_arn`).
4. Have the security team delete the bootstrap-operator user.

You will not need the bootstrap operator again unless you change the list of `deployer_principal_arns` later.

## Step 1b: Prepare HubSpot

Before deploying, the integration expects an existing pipeline named **"Government"** in HubSpot. The integration does not create a pipeline (HubSpot Professional accounts are limited to two custom pipelines, so creating one for every deployer is unsafe).

1. Go to **Settings > Objects > Deals > Pipelines**.
2. Either create a new pipeline named exactly `Government` or rename an existing one.
3. Add stages with these labels (or the labels you prefer; if you change them, update `GOVWIN_STATUS_TO_STAGE` in `src/hubspot/properties.py` to match):
   - Opportunity Identified
   - Reviewing Requirements
   - Preparing Response
   - Submitted
   - Closed Won
   - Closed Lost
   - Declined
   - Other

If you want a different pipeline name, set `PIPELINE_NAME` in `src/hubspot/properties.py` before building the Lambda layer.

## Step 2: Create HubSpot API Token

HubSpot offers two methods for API authentication. Use **Service Keys** (recommended) or Private Apps (legacy).

### Option A: Service Key (Recommended, 2026+)

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

Service Keys are in public beta (as of February 2026). If you don't see "Service Keys" in your HubSpot settings, use Option B below.

### Option B: Private App (Legacy, still works)

1. Log in to HubSpot as a **Super Admin**
2. Go to **Settings > Integrations > Private Apps**
3. Click **"Create a private app"**
4. Name it `GovWin Integration`
5. Under the **Scopes** tab, enable the same 12 scopes listed in Option A
6. Click **Create app** and copy the access token

Heads up: Private Apps are marked as "legacy" by HubSpot. They still work and have no announced sunset date, but new integrations should prefer Service Keys when available.

### Token Format

Both options produce a bearer token in the same format:
```
pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```
This token does not expire. Store it securely. Anyone with this token has full read/write access to your CRM data within the granted scopes.

## Step 3: Get GovWin API Credentials

You need 4 values from GovWin: a Client ID, Client Secret, username, and password. The integration uses OAuth2 password grant to authenticate.

### 3a. Get Client ID and Client Secret

Your organization's GovWin administrator provisions API access:

1. Log in to [GovWin IQ](https://iq.govwin.com) as an **administrator**
2. Navigate to **Admin > Web Service API** (or contact your GovWin account manager to enable WSAPI access)
3. In the API management section, create or locate your **Client ID** and **Client Secret**
4. Copy both values. These are organization-level credentials shared across all API users

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

# Run validation against GovWin only
set -a && source .env && set +a
python scripts/validate.py --skip-hubspot
```

Or test manually with curl:
```bash
curl -X POST https://services.govwin.com/neo-ws/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET&grant_type=password&username=YOUR_EMAIL&password=YOUR_PASSWORD&scope=read"
```

A successful response returns an `access_token` and `refresh_token`.

## Step 4: Configure the main module

### 4a. Wire the bootstrap outputs into the backend

Copy the example backend file and fill in the values from `terraform output` in the bootstrap directory:

```bash
cp terraform/backend.tf.example terraform/backend.tf
```

Edit `terraform/backend.tf`:

```hcl
terraform {
  backend "s3" {
    bucket   = "govwin-hubspot-prod-tfstate-XXXXXXXX"     # from bootstrap output
    key      = "govwin-hubspot/terraform.tfstate"
    region   = "us-east-1"
    encrypt  = true
    use_lockfile = true
    profile  = "default"                                   # local profile with sts:AssumeRole on the deployer role
    role_arn = "arn:aws:iam::ACCOUNT:role/govwin-hubspot-prod-deployer"  # from bootstrap output
  }
}
```

### 4b. Set the variable values

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars`:

```hcl
# Required - tells the provider which role to assume for resource operations
deployer_role_arn = "arn:aws:iam::ACCOUNT:role/govwin-hubspot-prod-deployer"

# Required - GovWin credentials
govwin_client_id     = "your-client-id"
govwin_client_secret = "your-client-secret"
govwin_username      = "your-email@company.com"
govwin_password      = "your-password"

# Required - HubSpot credentials (existing private-app token)
hubspot_private_app_token = "pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Required for v2 (HubSpot to AWS Partner Central submission)
ace_default_solution_id       = "S-0051246"          # from `aws partnercentral-selling list-solutions`
hubspot_webhook_app_id        = "12345678"           # from `hs project upload`
hubspot_webhook_client_secret = "<from HubSpot dev portal>"

# Optional - keep defaults unless you need to override
ace_catalog        = "Sandbox"                        # flip to "AWS" only after sandbox smoke passes
aws_region         = "us-east-1"
sync_schedule      = "rate(4 hours)"
notification_email = "alerts@company.com"
```

> **Security:** `terraform.tfvars` and `terraform/backend.tf` are both in `.gitignore` and will never be committed.

## Step 5: Build the Lambda Layer

Before deploying, you need to package the Python dependencies into a Lambda layer zip. The Lambdas run on ARM64 (Graviton2) for cost savings, so the layer must be built for that architecture even if your dev machine is x86_64 or Apple Silicon:

```bash
make package
```

This runs:
```bash
pip install \
  --platform manylinux2014_aarch64 \
  --only-binary=:all: \
  --implementation cp \
  --python-version 3.12 \
  -r requirements.txt \
  -t package/python/
```

The result is `lambda-layer.zip` (~21MB) in the project root. Terraform references this file when creating the Lambda layer. Rebuild it whenever you change `requirements.txt`.

## Step 6: Deploy

```bash
cd terraform

# Initialize Terraform (downloads providers and configures backend)
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

## Step 7: Mark Opportunities for Sync

By default, only opportunities your BD team explicitly marks in GovWin IQ will sync to HubSpot. This is controlled by the `govwin_marked_version` variable (default: `"2.2"`).

**To mark an opportunity for sync:**
1. Open the opportunity in GovWin IQ
2. Click **"Add to Web Services Download"** on the opportunity detail page
3. The opportunity will be picked up on the next scheduled sync

**Alternative filtering modes** (set in `terraform.tfvars`):
- `govwin_saved_search_id = "12345"` -- sync opps matching a GovWin saved search
- `govwin_bookmarked_only = true` -- sync only bookmarked opps
- `govwin_marked_version = ""` -- disable filtering, sync all opps (not recommended for production)

## Step 8: Verify Deployment

### Check HubSpot Setup

The `setup_hubspot` Lambda runs automatically during deployment and creates the custom properties (it does not create a pipeline). Verify in HubSpot:
- Go to **Settings > Properties > Deal properties** -- you should see `govwin_*` properties
- Go to **Settings > Objects > Deals > Pipelines** -- the **"Government"** pipeline you prepared in Step 1a is where new deals will appear

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

## Step 9: Wire up the AWS Partner Central submission half (v2)

The GovWin to HubSpot half is now running. To submit deals onward to AWS Partner Central via this project's own Selling-API client:

### 9a. Confirm AWS Partner Central prerequisites

```bash
# Confirm sandbox catalog access (should return an empty list, not AccessDenied)
aws partnercentral-selling list-opportunities --catalog Sandbox --region us-east-1

# Discover your Approved Solutions and pick one to set as ace_default_solution_id
aws partnercentral-selling list-solutions --catalog AWS --region us-east-1 \
  --query 'SolutionSummaries[].{Id:Id,Name:Name,Status:Status,Category:Category}'
```

If `list-solutions` returns nothing, register one in the Partner Central UI under **Sell -> My Solutions** before continuing.

### 9b. Create the HubSpot developer-platform app

The legacy private-app UI is gone in HubSpot 2025.2+; the new path is the developer-platform projects framework:

```bash
npm install -g @hubspot/cli
hs init                   # authenticates against your HubSpot account
hs project upload         # uploads the bundled hubspot-app/ project
```

The project (`hubspot-app/`) is committed to the repo with the right scopes and webhook subscriptions pre-declared (deal-stage, amount, closedate, dealname, govwin_ace_delivery_model, govwin_ace_partner_need). Subscriptions ship inactive; we activate them in step 9d after the API Gateway URL is known.

After upload, copy the **App ID** and **client secret** from the HubSpot developer portal.

### 9c. Set the v2 Terraform variables

```hcl
ace_catalog                   = "Sandbox"             # flip to "AWS" only after sandbox tests pass
ace_default_solution_id       = "S-0051246"           # from list-solutions output above
hubspot_webhook_app_id        = "12345678"            # from HubSpot dev portal
hubspot_webhook_client_secret = "client-secret-from-hubspot"
```

Then re-run `terraform apply`. The output `hubspot_webhook_target_url` is the public URL HubSpot should POST to.

### 9d. Activate the webhook subscriptions

Paste the `hubspot_webhook_target_url` value into `hubspot-app/src/app/webhooks/webhooks-hsmeta.json` (replacing the placeholder), flip every `"active": false` to `"active": true`, and re-run:

```bash
hs project upload
```

HubSpot now delivers deal property changes to the API Gateway. The receiver Lambda validates the signature, routes events to the appropriate SQS queue, and the `submit_to_ace` / `update_in_ace` Lambdas drain them.

### 9e. Smoke test

Run the sandbox smoke matrix (see [Testing Guide](testing.md#ace-sandbox-smoke-matrix)) before flipping `ace_catalog` to `AWS`. Once green, change to production:

```hcl
ace_catalog = "AWS"
```

`terraform apply` rebuilds the IAM policy without the `Catalog: Sandbox` condition. Production smoke is a single low-stakes opportunity end-to-end (Phase 4.2 of the rollout plan).

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
