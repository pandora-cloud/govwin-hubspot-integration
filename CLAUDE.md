# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Integration between Deltek GovWin IQ and HubSpot CRM, deployed on AWS via Terraform. Syncs government contracting opportunity data from GovWin into HubSpot, with fields pre-populated for downstream AWS Partner Central submission via SaaSify ACE Connector.

- **GitLab repo**: `gitlab.com/pandora-cloud/internal/govwin-hubspot-integration`
- **CI**: GitLab CI with secret detection enabled (`.gitlab-ci.yml`)
- **Language**: Python 3.12
- **AWS Services**: Lambda, Step Functions, DynamoDB, Secrets Manager, EventBridge, SNS, SQS
- **IaC**: Terraform (modular, in `terraform/`)

## Pipeline

```
GovWin IQ → (this integration) → HubSpot CRM → (SaaSify ACE Connector) → AWS Partner Central
```

## Build & Test Commands

- `make install-dev` — Install dev dependencies
- `make test` — Run unit tests (`pytest tests/unit -v`)
- `make test-all` — Run all tests including integration
- `make lint` — Run ruff linter
- `make format` — Auto-format code
- `make typecheck` — Run mypy
- `make deploy` — Deploy via Terraform
- `make package` — Package Lambda layer

## Code Structure

```
src/
  config.py              — Configuration from environment variables
  models.py              — Pydantic models for GovWin and HubSpot data
  govwin/
    auth.py              — OAuth2 token acquire/refresh via Secrets Manager
    client.py            — GovWin WSAPI V3 client (all endpoints)
    rate_limiter.py      — Token bucket rate limiter (4,000/hr)
  hubspot/
    client.py            — HubSpot CRM API client (batch upsert, associations)
    properties.py        — Custom property/pipeline definitions (declarative)
    rate_limiter.py      — Sliding window rate limiter (100/10s)
  sync/
    mapper.py            — GovWin → HubSpot field transformation + NAICS→industry mapping
    state.py             — DynamoDB state management (sync cursors, ID mappings)
    dedup.py             — Change detection: filter by updateDate (timezone-aware)
    orchestrator.py      — High-level sync coordination
  lambdas/
    authenticate.py      — Get/refresh GovWin OAuth token
    discover_changes.py  — Discover opps to sync (marked/saved search/bookmarked/all)
    fetch_opp_details.py — Fetch full opportunity data (bundle)
    sync_to_hubspot.py   — Push to HubSpot via batch APIs
    update_sync_state.py — Persist sync cursor to DynamoDB
    setup_hubspot.py     — One-time property/pipeline creation
    handle_error.py      — Error notification (SNS + SQS DLQ)
terraform/
  main.tf                — Root module wiring
  variables.tf           — All configurable inputs (sensitive marked)
  modules/               — lambda, step_function, dynamodb, secrets, monitoring
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
- **Marked for download**: `GET /opportunities/?markedVersion=2.2` — BD team marks opps for sync.
- **Bookmarked**: `GET /opportunities/?markedOpps=true` — user's bookmarked opps.

### HubSpot CRM API v3

- **Auth**: Private App token (Bearer header)
- **Rate limit**: 100 requests/10 seconds
- **Batch endpoints**: `/batch/upsert` with `idProperty` for deduplication
- **Custom properties**: All under `govwin_` prefix in `govwin` group
- **Pipeline**: "GovWin Pipeline" with stages mapped from GovWin statuses

### SaaSify ACE Connector (existing)

Already installed in HubSpot. Reads deal properties and submits to AWS Partner Central. Our sync auto-populates 9 of 12 ACE mandatory fields. Three require manual entry: delivery model, AWS solution, partner need from AWS.

## Key Design Decisions

- **Step Functions over single Lambda**: Handles multi-step sync within rate limits, avoids 15-min timeout
- **DynamoDB for state**: Serverless, pay-per-request, perfect for key-value sync tracking
- **Secrets Manager over SSM**: Automatic rotation support, audit trail
- **HubSpot batch upsert with idProperty**: Eliminates search-before-upsert, reducing API calls by ~50%
- **NAICS→AWS industry mapping**: Configurable lookup in `src/sync/mapper.py`
- **Marked-for-sync default**: Only opps BD team marks in GovWin sync to HubSpot (prevents bulk sync of irrelevant data)
- **Three discovery modes**: Marked (default), saved search, or bookmarked — configurable via Terraform variables
