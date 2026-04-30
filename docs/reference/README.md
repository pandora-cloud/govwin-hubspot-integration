# Reference Documents

Snapshots of upstream API and integration documentation captured for offline reference. The original sources are authoritative; this folder exists so contributors can read the integration plan without bouncing between AWS, HubSpot, and Deltek docs sites.

Each file lists the source URL and the date the snapshot was captured. Refresh by re-fetching when working on a related code change.

## AWS Partner Central Selling API

| File | Topic |
|---|---|
| `aws-partner-central/selling-api-overview.md` | High-level: routes, auth, entity model, sync strategies |
| `aws-partner-central/api-create-opportunity.md` | `CreateOpportunity` request/response schema, field mapping |
| `aws-partner-central/api-start-engagement-from-opportunity.md` | `StartEngagementFromOpportunityTask` (the "submit to AWS" call) |
| `aws-partner-central/eventbridge-events.md` | All 10 EventBridge event types and their schemas |
| `aws-partner-central/quotas-and-limits.md` | Read/write rate limits, association limits |
| `aws-partner-central/sandbox-testing.md` | Sandbox catalog, scoped IAM policy, switching environments |
| `aws-partner-central/best-practices.md` | Idempotency, optimistic locking, batching, ClientToken hygiene |

## HubSpot

| File | Topic |
|---|---|
| `hubspot/private-app-webhooks.md` | Webhook subscription types, payload schema, X-HubSpot-Signature-v3 validation, retry/timeout |

## Deltek GovWin

The full WSAPI V3 quick reference is at `docs/DeltekGovWinWebServiceAPIQuickReferenceGuide.pdf` (March 2025 edition). Relevant sections summarized in CLAUDE.md and field-mapping.md.
