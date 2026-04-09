# GovWin-HubSpot Integration

Sync government contracting opportunities from Deltek GovWin IQ into HubSpot CRM, with fields pre-populated for AWS Partner Central co-selling.

Built and maintained by [Pandora Cloud](https://pandoracloud.net). Free to use under the MIT license.

## What This Does

This integration connects Deltek GovWin IQ to HubSpot CRM. Government opportunities tracked in GovWin - including their associated agencies, contacts, and contract details - are automatically synced into HubSpot as deals, companies, and contacts. Your business development team marks opportunities in GovWin, and they appear in HubSpot within hours, fully populated with 30 custom properties.

The full pipeline runs from GovWin through HubSpot and on to AWS Partner Central. GovWin is the source of truth for opportunity data. This integration moves that data into HubSpot, where BD teams review and enrich it. The SaaSify ACE Connector (installed separately in HubSpot) then submits qualified deals to AWS Partner Central for co-selling with AWS field teams.

The sync runs incrementally - only opportunities that changed since the last run are processed. Built-in rate limiting respects both GovWin's 4,000 calls/hour cap and HubSpot's 100 requests/10 seconds limit. Nine of the twelve mandatory AWS ACE fields are auto-populated from GovWin data, leaving only three for manual entry before submission.

![Pipeline Overview](docs/diagrams/pipeline-overview.svg)

## How It Works

### For your BD team

1. **Find an opportunity in GovWin IQ** and click "Add to Web Services Download" on the opportunity detail page.
2. **The integration syncs it to HubSpot** on the next scheduled run (default: every 4 hours). A deal appears in the GovWin Pipeline with the opportunity details, agency, and contacts already filled in.
3. **Review the deal in HubSpot**, fill in 3 fields for ACE, and submit to AWS Partner Central via the SaaSify connector.

### Under the hood

![Architecture](docs/diagrams/architecture.svg)

- **AWS Step Functions** - Orchestrates the multi-step sync workflow, handling pagination, batching, and error recovery.
- **AWS Lambda (x7)** - Python 3.12 functions running on ARM64 (Graviton2) for each step: authenticate, discover changes, fetch details, sync to HubSpot, update state, setup properties, and handle errors.
- **Amazon DynamoDB** - Two tables track sync cursors, per-opportunity update timestamps, and GovWin-to-HubSpot ID mappings.
- **AWS Secrets Manager** - Stores GovWin credentials, OAuth tokens, and the HubSpot API token. Tokens are refreshed automatically before expiry.
- **Amazon EventBridge** - Triggers the Step Function on a configurable schedule.
- **Amazon SNS** - Sends email notifications with sync summaries and error alerts.
- **Amazon SQS** - Dead letter queue captures failed operations for later inspection.

## ACE-Ready Deals

The integration auto-populates 9 of the 12 mandatory fields required by AWS Partner Central (ACE). After a deal syncs to HubSpot, your team only needs to fill in three fields before submitting through the SaaSify ACE Connector.

| # | ACE Mandatory Field | HubSpot Property | Source | Auto-populated |
|---|---|---|---|---|
| 1 | Project Title | `dealname` | GovWin `title` | Yes |
| 2 | Project Description | `description` | GovWin `description` (sanitized) | Yes |
| 3 | Customer Company Name | Associated Company `name` | GovWin `govEntity.title` | Yes |
| 4 | Industry Vertical | `govwin_industry` | NAICS code mapped to AWS industry | Yes |
| 5 | Country | `govwin_country` | GovWin `country` | Yes |
| 6 | Target Close Date | `closedate` | GovWin `pAwardDateTo` or `responseDate` | Yes |
| 7 | Expected AWS Monthly Revenue | `amount` | GovWin `oppValue` x 1000 | Yes |
| 8 | Opportunity Type | `govwin_ace_opportunity_type` | Default: "Net New Business" | Yes |
| 9 | Stage | `dealstage` | Mapped from GovWin `status` | Yes |
| 10 | Delivery Model | `govwin_ace_delivery_model` | -- | **Manual** |
| 11 | Solution Offered | `govwin_ace_solution` | -- | **Manual** |
| 12 | Partner Primary Need from AWS | `govwin_ace_partner_need` | -- | **Manual** |

For the full end-to-end ACE submission workflow, see the [ACE Integration Guide](docs/ace-integration.md).

## Prerequisites

- [ ] **Deltek GovWin IQ** subscription with WSAPI V3 access (Client ID, Client Secret, username, password)
- [ ] **HubSpot** account (Professional or Enterprise) with a Service Key or Private App token
- [ ] **AWS** account with permissions for Lambda, Step Functions, DynamoDB, Secrets Manager, EventBridge, SNS, SQS, IAM, and CloudWatch
- [ ] **Terraform** >= 1.5 ([install guide](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli))
- [ ] **AWS CLI** configured with credentials (`aws configure`)
- [ ] **Python** >= 3.12 for building the Lambda layer
- [ ] (Optional) **Docker** for local testing with LocalStack
- [ ] (Optional) **SaaSify AWS ACE Connector** installed in HubSpot for AWS Partner Central submission

## Quick Start

### 1. Clone the repository

```bash
git clone https://gitlab.com/pandora-cloud/internal/govwin-hubspot-integration.git
cd govwin-hubspot-integration
```

### 2. Create a HubSpot API token

Log in to HubSpot as a Super Admin and go to **Settings > Integrations > Service Keys**. Create a key named "GovWin Integration" with these scopes:

- `crm.objects.deals.read` / `crm.objects.deals.write`
- `crm.objects.companies.read` / `crm.objects.companies.write`
- `crm.objects.contacts.read` / `crm.objects.contacts.write`
- `crm.schemas.deals.read` / `crm.schemas.deals.write`
- `crm.schemas.companies.read` / `crm.schemas.companies.write`
- `crm.schemas.contacts.read` / `crm.schemas.contacts.write`

Copy the token (starts with `pat-na1-` or `pat-na2-`). If Service Keys are not available in your HubSpot account, create a Private App instead under **Settings > Integrations > Private Apps** with the same scopes. See the [Deployment Guide](docs/deployment-guide.md#step-2-create-hubspot-api-token) for details on both options.

### 3. Get GovWin API credentials

You need four values: Client ID, Client Secret, username (email), and password. Your GovWin administrator provisions API access under **Admin > Web Service API** in the GovWin IQ portal. The username is the email address of a GovWin user account - a dedicated API user is recommended for production. See the [Deployment Guide](docs/deployment-guide.md#step-3-get-govwin-api-credentials) for step-by-step instructions and security considerations.

### 4. Configure Terraform variables

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars` with your credentials and preferred settings:

```hcl
# Required
govwin_client_id          = "your-client-id"
govwin_client_secret      = "your-client-secret"
govwin_username           = "your-email@company.com"
govwin_password           = "your-password"
hubspot_private_app_token = "pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# Optional
aws_region         = "us-east-1"
sync_schedule      = "rate(4 hours)"
notification_email = "alerts@company.com"
```

This file is gitignored and will not be committed.

### 5. Build and deploy

```bash
# Package Python dependencies into a Lambda layer (cross-compiled for ARM64)
make package

# Deploy infrastructure
cd terraform
terraform init
terraform plan    # Review what will be created
terraform apply   # Deploy (type "yes" when prompted)
```

Terraform creates all AWS resources, stores credentials in Secrets Manager, sets up HubSpot custom properties and the GovWin Pipeline, and schedules the first sync.

### 6. Mark opportunities and verify

In GovWin IQ, open any opportunity and click **"Add to Web Services Download"**. The next scheduled sync (or a manual trigger) picks it up and creates the deal in HubSpot.

To trigger a sync immediately:

```bash
terraform output step_function_arn

aws stepfunctions start-execution \
  --state-machine-arn <arn-from-above> \
  --name "manual-first-sync-$(date +%s)"
```

Verify in HubSpot under **Settings > Objects > Deals > Pipelines** that the "GovWin Pipeline" exists, and check the deals list for your synced opportunities.

## Configuration

All configuration is managed through Terraform variables in `terraform/terraform.tfvars`.

| Variable | Default | Description |
|---|---|---|
| `govwin_client_id` | (required) | GovWin WSAPI client ID |
| `govwin_client_secret` | (required) | GovWin WSAPI client secret |
| `govwin_username` | (required) | GovWin user email for API access |
| `govwin_password` | (required) | GovWin user password for API access |
| `hubspot_private_app_token` | (required) | HubSpot Service Key or Private App access token |
| `aws_profile` | `default` | AWS CLI profile name for authentication |
| `aws_region` | `us-east-1` | AWS region for deployment |
| `environment` | `prod` | Environment name: `prod`, `staging`, or `dev` |
| `project_name` | `govwin-hubspot` | Project name prefix for resource naming |
| `sync_schedule` | `rate(4 hours)` | EventBridge schedule expression for sync frequency |
| `govwin_opp_types` | `ALL` | Opportunity types to sync: `OPP`, `BID`, `TNS`, `FBO`, `OPN`, `TOP`, or `ALL` |
| `govwin_market` | `""` (both) | Market filter: `Federal`, `SLED`, or `""` for both |
| `govwin_marked_version` | `2.2` | Marked-for-download filter: `2.2` (Web Services), `2` (Deltek CRM), `""` (disabled) |
| `govwin_saved_search_id` | `""` | GovWin saved search ID to filter opportunities |
| `govwin_bookmarked_only` | `false` | Only sync bookmarked opportunities |
| `initial_lookback_days` | `365` | Days to look back on first sync |
| `max_concurrency` | `2` | Parallel batches in Step Function Map state (1-5) |
| `batch_size` | `10` | Opportunities per batch (1-25) |
| `enable_notifications` | `true` | Enable SNS email notifications for sync events |
| `notification_email` | `""` | Email address for sync notifications |
| `log_retention_days` | `30` | CloudWatch log retention in days |
| `tags` | `{}` | Additional tags applied to all resources |

## Opportunity Filtering

By default, only opportunities your BD team explicitly marks in GovWin IQ are synced. This keeps your HubSpot pipeline focused on opportunities that matter.

| Mode | Variable | How It Works |
|---|---|---|
| **Marked for Sync** (default) | `govwin_marked_version = "2.2"` | Only syncs opps where your team clicked "Add to Web Services Download" in GovWin IQ |
| Saved Search | `govwin_saved_search_id = "12345"` | Syncs opps matching a saved search you configured in GovWin |
| Bookmarked Only | `govwin_bookmarked_only = true` | Syncs opps your team bookmarked in GovWin |

These modes can be combined. For example, setting both `govwin_marked_version = "2.2"` and `govwin_bookmarked_only = true` syncs only bookmarked opps that are also marked for download.

To disable filtering entirely and sync all opportunities:

```hcl
govwin_marked_version = ""
```

This is not recommended for production - GovWin contains hundreds of thousands of opportunities, and syncing all of them would overwhelm your HubSpot pipeline.

## Data Mapping

The integration creates 30 custom deal properties, 5 company properties, and 3 contact properties in HubSpot, all under the `govwin_` prefix. It also creates a "GovWin Pipeline" with stages mapped from GovWin statuses.

### Key field mappings

| GovWin Field | HubSpot Property | Transform |
|---|---|---|
| `title` | `dealname` | Direct |
| `oppValue` | `amount` | Multiplied by 1,000 (GovWin stores in thousands) |
| `description` | `description` | HTML stripped, truncated to 65,536 chars |
| `pAwardDateTo` / `responseDate` | `closedate` | Converted to HubSpot epoch milliseconds |
| `id` (e.g., OPP12345) | `govwin_opp_id` | Deduplication key |
| `status` | Deal stage | Mapped to pipeline stages (Pre-RFP, RFP Released, etc.) |
| `govEntity.title` | Associated Company `name` | Creates/updates HubSpot company |
| `primaryNAICS` | `govwin_industry` | NAICS code mapped to AWS ACE industry values |
| `solicitationNumber` | `govwin_solicitation_number` | Direct |
| `country` | `govwin_country` | USA or CAN |
| `competitionTypes[0].title` | `govwin_competition_type` | Direct |
| `contractTypes[0].title` | `govwin_contract_type` | Direct |

### Pipeline stages

| GovWin Status | HubSpot Stage | Probability |
|---|---|---|
| Pre-RFP | Pre-RFP | 10% |
| RFP Released | RFP Released | 20% |
| Proposal Submitted | Proposal Submitted | 40% |
| Under Evaluation | Under Evaluation | 50% |
| Awarded | Awarded (Won) | 100% |
| Cancelled | Cancelled (Lost) | 0% |

### Associations

Deals are linked to their government agency (Company) and agency contacts (Contacts). Companies and contacts are deduplicated across opportunities - if three deals reference GSA, a single GSA company record is shared.

For the complete mapping of all 38 properties, NAICS-to-industry codes, and association logic, see the [Field Mapping Reference](docs/field-mapping.md).

## Pre-deployment Testing

Before deploying to AWS, you can validate credentials and preview the sync locally.

```bash
# Copy and fill in your credentials
cp .env.example .env

# Validate connectivity to GovWin, HubSpot, and AWS
make validate

# Preview what would sync without writing to HubSpot (fetches up to 5 opps)
make dry-run
```

For testing against real AWS services locally using Docker and LocalStack:

```bash
make local-up       # Start LocalStack with DynamoDB, Secrets Manager, SNS, SQS
make local-test     # Run integration tests against LocalStack
make local-down     # Stop and clean up
```

## Project Structure

```
src/
  config.py                  # Configuration from environment variables
  models.py                  # Pydantic models for GovWin and HubSpot data
  govwin/
    auth.py                  # OAuth2 token acquire/refresh via Secrets Manager
    client.py                # GovWin WSAPI V3 client (all endpoints)
    rate_limiter.py          # Token bucket rate limiter (4,000/hr)
  hubspot/
    client.py                # HubSpot CRM API client (batch upsert, associations)
    properties.py            # Custom property and pipeline definitions
    rate_limiter.py          # Sliding window rate limiter (100/10s)
  sync/
    mapper.py                # GovWin-to-HubSpot field transformation, NAICS mapping
    state.py                 # DynamoDB state management (sync cursors, ID mappings)
    dedup.py                 # Change detection via updateDate comparison
    orchestrator.py          # High-level sync coordination
  lambdas/
    authenticate.py          # Get/refresh GovWin OAuth token
    discover_changes.py      # Search for updated opportunities
    fetch_opp_details.py     # Fetch full opportunity data
    sync_to_hubspot.py       # Push to HubSpot via batch APIs
    update_sync_state.py     # Persist sync cursor to DynamoDB
    setup_hubspot.py         # One-time property/pipeline creation
    handle_error.py          # Error notification (SNS + SQS DLQ)
terraform/
  main.tf                    # Root module wiring
  variables.tf               # All configurable inputs
  outputs.tf                 # Terraform outputs (ARNs, URLs)
  provider.tf                # AWS provider configuration
  modules/
    lambda/                  # Lambda functions and shared layer
    step_function/           # Step Function state machine definition
    dynamodb/                # DynamoDB tables
    secrets/                 # Secrets Manager secrets
    monitoring/              # SNS, SQS, CloudWatch
tests/
  unit/                      # 92 unit tests (17 test files)
  integration/               # Integration tests (LocalStack)
  conftest.py                # Shared pytest fixtures
scripts/
  validate.py                # Pre-deployment credential validation
  dry_run.py                 # Preview sync without writing to HubSpot
  localstack-init.sh         # LocalStack resource initialization
docs/
  architecture.md            # System design and AWS resource details
  field-mapping.md           # Complete GovWin-to-HubSpot field mapping
  deployment-guide.md        # Step-by-step deployment instructions
  ace-integration.md         # ACE submission workflow
  testing.md                 # Testing guide and production test results
  diagrams/                  # Architecture and pipeline diagrams (SVG + drawio)
```

## Documentation

- [Architecture Overview](docs/architecture.md) - System design, Step Function workflow, DynamoDB schema, rate limiting strategy
- [Field Mapping Reference](docs/field-mapping.md) - All 38 mapped properties, NAICS-to-industry codes, pipeline stages, associations
- [Deployment Guide](docs/deployment-guide.md) - Full deployment walkthrough, credential setup, troubleshooting
- [ACE Integration Guide](docs/ace-integration.md) - End-to-end workflow for submitting deals to AWS Partner Central
- [Testing Guide](docs/testing.md) - Unit tests, validation scripts, LocalStack setup, production test results

## Security

- All API credentials (GovWin Client ID/Secret, username/password, HubSpot token) are stored in AWS Secrets Manager and never passed as plaintext environment variables.
- GovWin OAuth tokens are cached in Secrets Manager and refreshed automatically before expiry. The refresh flow avoids the 5-attempt lockout on the password grant.
- Lambda execution roles follow least-privilege principles - each function can only access the specific Secrets Manager keys and DynamoDB tables it needs.
- `terraform.tfvars` and `.env` are gitignored. Secret detection runs in the GitLab CI pipeline to catch accidental credential commits.
- DynamoDB tables use encryption at rest (AWS-managed keys). Secrets Manager encrypts all stored values with KMS.
- No VPC is required since the integration only calls external APIs, reducing attack surface and eliminating NAT Gateway costs.

## Estimated Cost

Running this integration on AWS costs approximately **$6/month** at moderate volume (around 1,000 opportunities). The main cost drivers are Lambda invocations, DynamoDB reads/writes, and Secrets Manager API calls. Step Functions, EventBridge, SNS, and SQS all fall within their free tiers at this scale. Lambda runs on ARM64 (Graviton2) for a 20% cost reduction over x86.

## Development

```bash
make install-dev    # Install development dependencies (ruff, mypy, pytest, etc.)
make test           # Run 92 unit tests
make test-all       # Run all tests including integration
make lint           # Check code with ruff
make format         # Auto-format code with ruff
make typecheck      # Run mypy type checking
```

## License

MIT License. Copyright (c) 2026 [Pandora Cloud](https://pandoracloud.net). See [LICENSE](LICENSE) for the full text.
