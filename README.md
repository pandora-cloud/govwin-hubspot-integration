# GovWin-to-HubSpot Integration

Automatically sync government contracting opportunities from [Deltek GovWin IQ](https://iq.govwin.com) into [HubSpot CRM](https://www.hubspot.com/), with fields pre-populated for downstream submission to [AWS Partner Central](https://partnercentral.awspartner.com/) via the SaaSify ACE Connector.

## Pipeline Overview

```
Deltek GovWin IQ ──(this integration)──> HubSpot CRM ──(SaaSify ACE)──> AWS Partner Central
     [auto sync]                          [review]          [submit]
```

1. **GovWin -> HubSpot** (automated): Opportunities, agencies, and contacts sync on a schedule
2. **HubSpot -> AWS Partner Central** (manual): Review deal in HubSpot, fill 3 fields, submit via SaaSify ACE Connector

## What It Does

- Syncs GovWin opportunities as HubSpot **Deals** with 25+ custom properties
- Syncs government entities as HubSpot **Companies**
- Syncs opportunity contacts as HubSpot **Contacts**
- Creates **associations** between deals, companies, and contacts
- **Incremental sync** -- only processes opportunities that changed since last run
- Pre-populates **9 of 12 AWS ACE mandatory fields** for co-selling readiness
- Respects rate limits on both GovWin (4,000 calls/hr) and HubSpot (100 req/10s)

## Architecture

Runs on AWS using serverless infrastructure managed by Terraform:

- **AWS Step Functions** orchestrates the multi-step sync workflow
- **AWS Lambda** (Python 3.12) executes each step
- **Amazon DynamoDB** tracks sync state and ID mappings
- **AWS Secrets Manager** stores API credentials securely
- **Amazon EventBridge** triggers sync on a configurable schedule (default: every 4 hours)
- **Amazon SNS** sends sync summary and error notifications
- **Amazon SQS** dead letter queue for failed operations

Estimated AWS cost: **~$6/month** at moderate volume (1,000 opportunities).

## Prerequisites

- **Deltek GovWin IQ** subscription with WSAPI access (client ID + secret + user credentials)
- **HubSpot** account (Professional or Enterprise for custom properties)
- **AWS** account with permissions to create Lambda, Step Functions, DynamoDB, Secrets Manager, EventBridge, SNS, SQS, IAM, and CloudWatch resources
- **Terraform** >= 1.5 installed locally
- **Python** >= 3.12 (for local development)
- (Optional) **SaaSify AWS ACE Connector** installed in HubSpot for AWS Partner Central integration

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-org/govwin-hubspot-integration.git
cd govwin-hubspot-integration
```

### 2. Configure credentials

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars` with your API credentials. This file is gitignored and will never be committed.

### 3. Deploy

```bash
cd terraform
terraform init
terraform plan    # Review what will be created
terraform apply   # Deploy infrastructure
```

Terraform will:
- Create all AWS resources
- Store your credentials in AWS Secrets Manager
- Set up HubSpot custom properties and deal pipeline
- Schedule the first sync

### 4. Verify

- Check the AWS Step Functions console for the first execution
- Verify deals appear in HubSpot under the "GovWin Pipeline"
- Check CloudWatch logs for detailed sync output

## Configuration

All configuration is done via Terraform variables. See [terraform/variables.tf](terraform/variables.tf) for the full list.

| Variable | Required | Default | Description |
|---|---|---|---|
| `govwin_client_id` | Yes | - | GovWin WSAPI client ID |
| `govwin_client_secret` | Yes | - | GovWin WSAPI client secret |
| `govwin_username` | Yes | - | GovWin user email |
| `govwin_password` | Yes | - | GovWin user password |
| `hubspot_private_app_token` | Yes | - | HubSpot private app access token |
| `aws_region` | No | `us-east-1` | AWS region for deployment |
| `sync_schedule` | No | `rate(4 hours)` | How often to sync |
| `govwin_opp_types` | No | `ALL` | Opportunity types to sync (OPP, BID, TNS, FBO, ALL) |
| `govwin_market` | No | (both) | Market filter (Federal, SLED, or both) |
| `notification_email` | No | - | Email for sync notifications |

## Data Mapping

### GovWin Opportunities -> HubSpot Deals

See [docs/field-mapping.md](docs/field-mapping.md) for the complete field mapping reference.

Key mappings:
- `title` -> Deal Name
- `oppValue` (x1000) -> Deal Amount
- `status` -> Deal Stage (custom GovWin pipeline)
- `govEntity.title` -> Associated Company
- `primaryNAICS` -> Industry (mapped to AWS ACE industry values)
- `description` -> Deal Description
- `pAwardDateTo` -> Close Date

### ACE-Ready Fields

When the SaaSify ACE Connector is installed, synced deals are pre-populated with 9 of 12 mandatory ACE fields. Only 3 require manual entry before submission to AWS Partner Central:

1. **Delivery Model** -- how the solution is delivered
2. **Solution Offered** -- which AWS solution
3. **Partner Primary Need from AWS** -- what support you need from AWS

## Project Structure

```
src/
  config.py              # Configuration management
  models.py              # Pydantic data models
  govwin/                # GovWin API client
  hubspot/               # HubSpot API client
  sync/                  # Sync logic (mapper, state, dedup)
  lambdas/               # Lambda function handlers
terraform/               # Infrastructure as Code
  modules/               # Reusable Terraform modules
tests/                   # Unit and integration tests
docs/                    # Documentation
```

## Documentation

- [Architecture Overview](docs/architecture.md)
- [Field Mapping Reference](docs/field-mapping.md)
- [Deployment Guide](docs/deployment-guide.md)
- [ACE Integration Guide](docs/ace-integration.md)

## Development

```bash
# Install dev dependencies
make install-dev

# Run tests
make test

# Lint code
make lint

# Format code
make format

# Type check
make typecheck
```

## Security

- All API credentials are stored in AWS Secrets Manager
- Lambda functions use least-privilege IAM roles
- `terraform.tfvars` and `.env` files are gitignored
- No secrets are ever committed to the repository
- Secret detection is enabled in CI/CD

## License

MIT License. See [LICENSE](LICENSE) for details.
