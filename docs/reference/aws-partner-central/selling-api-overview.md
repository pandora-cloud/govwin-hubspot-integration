# AWS Partner Central Selling API — Overview

> Reference snapshot captured 2026-04-28 from the AWS docs site. The official docs are the source of truth; this file exists so contributors can read the integration plan without bouncing between tabs.

## What it is

The AWS Partner Central Selling API is a public, REST-based AWS service that lets partners create and manage ACE opportunities, engagements, and solutions programmatically. It is the official replacement path for partners who don't use the no-code Salesforce CRM Connector or third-party tools (Commercient, SaaSify, Tackle, etc.).

- **Service name (boto3 / SDK):** `partnercentral-selling`
- **API version:** `2022-07-26`
- **Endpoint:** `https://partnercentral-selling.us-east-1.api.aws`
- **Region availability:** `us-east-1` only (as of 2026-04-28)
- **Authentication:** standard AWS SigV4 with IAM credentials. Lambdas can use their execution role directly. No IAM Roles Anywhere required for AWS-hosted callers.
- **Required IAM managed policy:** `AWSPartnerCentralOpportunityManagement` (or a tighter custom policy scoped to the actions needed)

## Three integration routes AWS publishes

| Route | Audience | Cost | Notes |
|---|---|---|---|
| **AWS Partner CRM Connector for Salesforce** | Salesforce-only orgs | Free package, configuration costs apply | No-code, AWS-managed AppExchange package |
| **Third-party connector** (Zoho, Microsoft Dynamics, SaaSify, Tackle, Commercient) | Anyone using these CRMs | Vendor subscription | Quality and feature breadth varies wildly |
| **Custom integration via Selling API** | Anyone | AWS API costs are minimal; dev cost varies | This is the route this project uses |

AWS estimates "3-12 weeks of initial development" for a custom integration, *which assumes solo human engineering*. With Claude Code that compresses meaningfully — see the project plan for actual estimates.

## Core entity model

| Entity | Purpose | ID format |
|---|---|---|
| **Opportunity** | A potential AWS-related deal. Includes customer, project, lifecycle, marketing, and revenue details | `O[0-9]{1,19}` |
| **Engagement** | A collaboration record linking AWS and one or more partners on an opportunity | `eng-[0-9a-z]{14}` |
| **Engagement Invitation** | AWS's formal request for a partner to collaborate on a referral | `engi-[0-9a-z]{13}` |
| **Solution** | A partner offering (software or consulting) associated with an opportunity | `S-[0-9]+` |
| **Resource Snapshot** | Point-in-time capture of opportunity state for a given engagement | scoped per snapshot job |
| **AWS Marketplace Private Offer** | Custom pricing terms attachable to an opportunity | external ID |

## Operations grouped by use case

### Opportunity CRUD
- `CreateOpportunity` — partner-originated opportunity
- `UpdateOpportunity` — requires `LastModifiedDate` for optimistic locking
- `GetOpportunity`
- `ListOpportunities` — supports `AfterLastModifiedDate` filter and pagination
- `AssignOpportunity` — reassign internal owner

### Engagement orchestration
- `StartEngagementFromOpportunityTask` — async; bundles GetOpportunity + CreateEngagement + CreateResourceSnapshot + CreateResourceSnapshotJob + CreateEngagementInvitation + SubmitOpportunity into one call. **This is the call that "submits the deal to AWS".**
- `StartEngagementByAcceptingInvitationTask` — async; the partner-side accept flow for AWS-originated referrals
- `RejectEngagementInvitation`
- `GetEngagementInvitation`
- `ListEngagementInvitations`

### Linking
- `AssociateOpportunity` — link an opportunity to a Solution, AWS Product, or Marketplace Private Offer
- `DisassociateOpportunity`

### AWS-side metadata
- `GetAwsOpportunitySummary` — read AWS's view of a shared opportunity
- `ListSolutions` — partner's own catalog of registered solutions

## Authentication summary

For Lambda-hosted integrations (this project's deployment target), the simplest path:

1. Each Lambda's execution role gets an IAM policy that allows `partnercentral:*` on `Resource: "*"` (or scoped to a single catalog via the `partnercentral:Catalog` condition key)
2. The boto3 SDK picks up credentials from the execution role automatically
3. SigV4 signing happens transparently inside boto3
4. No keys to rotate, no certs to manage, no IAM Roles Anywhere setup

For non-AWS hosts (a customer's on-prem CRM hitting the API directly), AWS recommends IAM Roles Anywhere with a private-CA-issued certificate. Out of scope for this project.

## Two recommended sync strategies

Per the [Best Practices doc](https://docs.aws.amazon.com/partner-central/latest/selling-api/best-practices.html):

**Option A — Event-driven (recommended).** Subscribe to EventBridge events on the `aws.partnercentral-selling` source. Use `ListOpportunities` once at startup to load the world, then react to events. Keeps AWS API calls minimal.

**Option B — Polling.** Periodically call `ListOpportunities` with `FilterList=[{Name: AfterLastModifiedDate, ValueList: [<last seen>]}]`. Simpler, no EventBridge wiring needed, but burns more of the daily quota.

The govwin-hubspot-integration design will combine both: outbound sync (HubSpot → ACE) is push-driven from HubSpot webhooks; inbound sync (ACE status → HubSpot) is event-driven from EventBridge.

## Important behavioral notes

- **Partner-originated opportunities** must use `Origin: "Partner Referral"` when `Catalog: "AWS"`.
- **`StartEngagementFromOpportunityTask` is one-way.** Once invoked, the opportunity is locked from edits until AWS completes review. Plan UX accordingly.
- **`ClientToken` must be unique per request.** Reusing one returns a `ConflictException`. UUIDs are the recommended approach.
- **Optimistic locking on updates.** Every `UpdateOpportunity` call must carry the most recent `LastModifiedDate`. Stale dates trigger `ConflictException`; fetch fresh and retry.
- **Idempotency on event handlers is required.** EventBridge can deliver duplicates.
- **Catalog is case-sensitive:** `AWS` for production, `Sandbox` for testing.

## Source URLs (for re-fetching when refreshing this doc)

- API reference index: https://docs.aws.amazon.com/partner-central/latest/APIReference/aws-partner-central-api-reference-guide.html
- Routes for CRM integration: https://docs.aws.amazon.com/partner-central/latest/crm/routes-for-crm-integration.html
- Best practices: https://docs.aws.amazon.com/partner-central/latest/selling-api/best-practices.html
- Quotas: https://docs.aws.amazon.com/partner-central/latest/selling-api/quotas.html
- Events: https://docs.aws.amazon.com/partner-central/latest/APIReference/selling-api-events.html
- Sandbox: https://docs.aws.amazon.com/partner-central/latest/selling-api/testing-sandbox.html
- AWS blog post (Nov 2024, updated Jan 2025): https://aws.amazon.com/blogs/awsmarketplace/integrate-crm-system-aws-partner-central-using-api-for-selling/
