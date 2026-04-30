# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

End-to-end pipeline from Deltek GovWin IQ through HubSpot CRM into AWS Partner Central, deployed on AWS via Terraform. v2 ships its own AWS Partner Central Selling-API client (no SaaSify dependency) on top of the v1 GovWin-to-HubSpot sync.

- **Public repo**: `github.com/pandora-cloud-llc/govwin-hubspot-integration` (also mirrored to a private GitLab; both `.gitlab-ci.yml` and `.github/workflows/ci.yml` run on every push)
- **CI**: lint + types + unit tests + secret scan
- **Language**: Python 3.12
- **AWS Services**: Lambda, Step Functions, DynamoDB, Secrets Manager, EventBridge, SNS, SQS
- **IaC**: Terraform (modular, in `terraform/`)

## Pipeline

```
GovWin IQ -> [Step Function: GovWin sync] -> HubSpot CRM
                                                  |
                              dealstage transition (HubSpot webhook)
                                                  v
       API Gateway -> Lambda receiver -> SQS -> [submit_to_ace Lambda]
                                                  |
              CreateOpportunity -> AssociateOpportunity -> StartEngagement
                                                  v
                                       AWS Partner Central
                                                  |
                                  EventBridge events back to us
                                                  v
                              [handle_ace_event Lambda] -> HubSpot stage
```

## Build & Test Commands

- `make install-dev` - Install dev dependencies
- `make test` - Run unit tests (`pytest tests/unit -v`)
- `make test-all` - Run all tests including integration
- `make lint` - Run ruff linter
- `make format` - Auto-format code
- `make typecheck` - Run mypy
- `make deploy` - Deploy via Terraform
- `make package` - Package Lambda layer

## Code Structure

```
src/
  config.py              - Configuration from environment variables
  models.py              - Pydantic models for GovWin and HubSpot data
  govwin/
    auth.py              - OAuth2 token acquire/refresh via Secrets Manager
    client.py            - GovWin WSAPI V3 client (all endpoints)
    rate_limiter.py      - Token bucket rate limiter (4,000/hr)
  hubspot/
    client.py            - HubSpot CRM API client (batch upsert, associations, webhook subscriptions)
    properties.py        - Custom property/pipeline definitions (declarative)
    rate_limiter.py      - Sliding window rate limiter (100/10s)
  ace/
    __init__.py          - Re-exports
    client.py            - boto3 partnercentral-selling wrapper, optimistic locking, tenacity retries
    rate_limiter.py      - Token-bucket limiter (1 write/sec, 10 reads/sec)
    mapper.py            - HubSpot deal -> ACE CreateOpportunity payload, with manual-field validation
    validators.py        - ID format guards (HubSpot objectId, GovWin id, AWS opportunity id)
  sync/
    mapper.py            - GovWin -> HubSpot field transformation + NAICS -> industry mapping
    state.py             - DynamoDB state management (sync cursors, ID mappings, ACE# / EVT# patterns)
    dedup.py             - Change detection: filter by updateDate (timezone-aware)
    orchestrator.py      - High-level sync coordination
  lambdas/
    authenticate.py             - Get/refresh GovWin OAuth token
    discover_changes.py         - Discover opps to sync (marked/saved search/bookmarked/all)
    fetch_opp_details.py        - Fetch full opportunity data (bundle)
    sync_to_hubspot.py          - Push to HubSpot via batch APIs
    update_sync_state.py        - Persist sync cursor to DynamoDB
    setup_hubspot.py            - One-time property/pipeline creation
    setup_hubspot_webhooks.py   - One-time webhook subscription registration
    handle_error.py             - Error notification (SNS + SQS DLQ)
    hubspot_webhook_receiver.py - API Gateway -> validate signature -> SQS routing
    submit_to_ace.py            - SQS -> 3-call ACE submission with resume-from-step idempotency
    update_in_ace.py            - SQS -> UpdateOpportunity with optimistic locking
    handle_ace_event.py         - EventBridge -> mirror AWS state changes to HubSpot
hubspot-app/                    - HubSpot developer-platform (2025.2+) project; webhook subscriptions
terraform/
  provider.tf            - AWS provider config with profile
  backend.tf             - S3 backend (gitignored, deployer-specific)
  main.tf                - Root module wiring
  variables.tf           - All configurable inputs (sensitive marked)
  modules/               - lambda, step_function, dynamodb, secrets, monitoring, ace
scripts/
  validate.py            - Pre-deployment credential and connectivity checks
  dry_run.py             - Preview sync results without writing to HubSpot
  localstack-init.sh     - Create AWS resources in LocalStack for local testing
```

## External APIs

### Deltek GovWin WSAPI V3

REST/JSON API for retrieving government contracting data. Reference doc: `docs/DeltekGovWinWebServiceAPIQuickReferenceGuide.pdf` (March 2025).

- **Base URL**: `https://services.govwin.com/neo-ws/`
- **Auth**: OAuth2 (client ID + secret + GovWin credentials). Token: 12hr access, 30-day refresh.
- **Rate limit**: 4,000 calls/hour per organization (rolling 60-minute window).
- **Paging**: Default 10 items, max 100. Response includes `meta.paging`.
- **Key entities**: Opportunities (OPP/TNS/BID/FBO/OPN/TOP), GovEntities, Companies
- **Incremental sync**: Track `updateDate` per opportunity; use `oppSelectionDateFrom`.
- **Marked for download**: `GET /opportunities/?markedVersion=2.2` - BD team marks opps for sync.
- **Bookmarked**: `GET /opportunities/?markedOpps=true` - user's bookmarked opps.

### HubSpot CRM API v3

- **Auth**: Private App token (Bearer header)
- **Rate limit**: 100 requests/10 seconds
- **Batch endpoints**: `/batch/upsert` with `idProperty` for deduplication
- **Custom properties**: All under `govwin_` prefix in `govwin` group
- **Pipeline**: "GovWin Pipeline" with stages mapped from GovWin statuses

### AWS Partner Central Selling API (v2)

Direct boto3 calls to `partnercentral-selling` (us-east-1, IAM SigV4 auth) replace SaaSify. Three-call submission flow: `CreateOpportunity` -> `AssociateOpportunity` -> `StartEngagementFromOpportunityTask`. Quotas: 1 write/sec + 10K/24h, 10 reads/sec + 100K/24h. Inbound state changes flow through EventBridge `aws.partnercentral-selling`. Reference docs in `docs/reference/aws-partner-central/`.

## Key Design Decisions

- **Step Functions over single Lambda**: Handles multi-step sync within rate limits, avoids 15-min timeout
- **DynamoDB for state**: Serverless, pay-per-request, perfect for key-value sync tracking
- **Secrets Manager over SSM**: Automatic rotation support, audit trail
- **HubSpot batch upsert with idProperty**: Eliminates search-before-upsert, reducing API calls by ~50%
- **NAICS -> AWS industry mapping**: Configurable lookup in `src/sync/mapper.py`
- **Marked-for-sync default**: Only opps BD team marks in GovWin sync to HubSpot (prevents bulk sync of irrelevant data)
- **Three discovery modes**: Marked (default), saved search, or bookmarked - configurable via Terraform variables
- **Sandbox-first ACE catalog**: `ACE_CATALOG` defaults to `Sandbox`; production deployments must explicitly opt in to `AWS`. The IAM policy adds a `partnercentral:Catalog: Sandbox` condition when running in Sandbox mode so even misconfigured code cannot accidentally write to production.
- **Atomic ClientToken reservation**: Both `CreateOpportunity` and `StartEngagementFromOpportunityTask` use ClientTokens persisted in DynamoDB via conditional writes; concurrent SQS retries cannot mint duplicate ACE opportunities.
- **Two-queue webhook routing**: Webhook receiver routes `dealstage` events to the submit queue and `amount`/`closedate`/`dealname`/`description`/`govwin_ace_*` events to the update queue, so each Lambda consumes its own queue (avoids the load-balancing-vs-fan-out trap of multiple consumers on one SQS queue).
