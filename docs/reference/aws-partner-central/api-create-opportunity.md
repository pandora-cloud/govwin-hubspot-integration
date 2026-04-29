# `CreateOpportunity` API reference

> Snapshot from https://docs.aws.amazon.com/partner-central/latest/selling-api/API_CreateOpportunity.html captured 2026-04-28.

## Purpose

Create an `Opportunity` record in AWS Partner Central. After creation, the opportunity is in `Lifecycle.ReviewStatus: "Pending Submission"` and can be edited until `StartEngagementFromOpportunityTask` is called.

## HTTP

- **Method:** `POST`
- **Path:** `/CreateOpportunity` (handled by the AWS SDK; do not construct manually)
- **Service:** `partnercentral-selling`

## Required fields

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `Catalog` | string | matches `[a-zA-Z]+` | `AWS` or `Sandbox` |
| `ClientToken` | string | 1-255 chars | Idempotency key. Use a UUID. |

## Optional but typically required for a real submission

| Field | Type | Notes |
|---|---|---|
| `Customer.Account.CompanyName` | string | The end customer (e.g. "Department of Defense") |
| `Customer.Account.Industry` | string | Enumeration; "Government" is required for federal |
| `Customer.Account.Address.{StreetAddress, City, StateOrRegion, PostalCode, CountryCode}` | strings | |
| `Customer.Contacts[]` | array | `FirstName`, `LastName`, `Email`, `Phone`, `BusinessTitle` per entry |
| `Project.Title` | string | Deal title |
| `Project.CustomerBusinessProblem` | string | Why the customer is buying |
| `Project.CustomerUseCase` | string | The technical AWS use case |
| `Project.ExpectedCustomerSpend[]` | array | At least one entry: `Amount`, `CurrencyCode`, `Frequency` (Annual/Monthly), `TargetCompany` |
| `Project.DeliveryModels[]` | string array | One of: `BYOL or AMI`, `Managed Services`, `Professional Services`, `Resell`, `SaaS or PaaS` |
| `OpportunityType` | string | `Net New Business`, `Flat Renewal`, or `Expansion` |
| `Origin` | string | `Partner Referral` (required when `Catalog: AWS`) |
| `PartnerOpportunityIdentifier` | string | Up to 64 chars; this project sets it to the GovWin global opp ID |
| `PrimaryNeedsFromAws[]` | string array | At least one: see allowed values below |
| `LifeCycle.TargetCloseDate` | string | Date the deal should close |
| `LifeCycle.NextSteps` | string | Sales next steps |
| `NationalSecurity` | string | `Yes` or `No`. Set `Yes` only for Government industry |

### `PrimaryNeedsFromAws` allowed values

- `Co-Sell - Architectural Validation`
- `Co-Sell - Business Presentation`
- `Co-Sell - Competitive Information`
- `Co-Sell - Pricing Assistance`
- `Co-Sell - Technical Consultation`
- `Co-Sell - Total Cost of Ownership Evaluation`
- `Co-Sell - Deal Support`
- `Co-Sell - Support for Public Tender / RFx`

## Response

```json
{
  "Id": "O123456789",
  "LastModifiedDate": "2026-04-28T22:24:33.498Z",
  "PartnerOpportunityIdentifier": "OPP263150"
}
```

`Id` is the AWS-generated opportunity ID; persist it in DynamoDB to enable later updates and submissions. `LastModifiedDate` is needed for optimistic-locking on subsequent `UpdateOpportunity` calls.

## Errors

| Code | HTTP | Common cause | Retry? |
|---|---|---|---|
| `ValidationException` (REQUEST_VALIDATION_FAILED) | 400 | Wrong field type, missing required field | No — fix the payload |
| `ValidationException` (BUSINESS_VALIDATION_FAILED) | 400 | Field value violates business rules (e.g. revenue too small for some programs) | No — fix the payload |
| `ConflictException` | 400 | `ClientToken` already used | No — generate a new token |
| `AccessDeniedException` | 400 | Missing IAM permissions | No — fix policy |
| `ResourceNotFoundException` | 400 | Referenced resource (Solution, etc) doesn't exist | No |
| `InternalServerException` | 500 | AWS-side error | Yes, with backoff |
| `ThrottlingException` | 400 | Hit the 1/s or 10K/24h write quota | Yes, with backoff |

## Three-step submission flow

`CreateOpportunity` alone does NOT submit the deal to AWS. Full submission is three calls:

1. **CreateOpportunity** → returns `Id`
2. **AssociateOpportunity** → link a Solution (`S-...`) so AWS knows what offering this is. Use `ListSolutions` once at startup to discover the partner's solution catalog.
3. **StartEngagementFromOpportunityTask** → async task that creates the engagement, snapshot, invitation, and submits the opportunity. Returns a `TaskId` for polling.

After step 3, the opportunity is locked from edits until AWS finishes its review (typically 24-72 hours).

## Field mapping notes for this project

The govwin-hubspot-integration uses these fields when generating the ACE payload from a HubSpot deal:

| ACE field | Source |
|---|---|
| `Catalog` | Config (env var: `Sandbox` or `AWS`) |
| `ClientToken` | Generated UUID per submission |
| `Customer.Account.CompanyName` | HubSpot associated company `name` |
| `Customer.Account.Industry` | HubSpot company `industry` (`GOVERNMENT_ADMINISTRATION` → ACE `Government`) |
| `Project.Title` | HubSpot deal `dealname` |
| `Project.CustomerBusinessProblem` | HubSpot deal `description` (sanitized) |
| `Project.ExpectedCustomerSpend[0].Amount` | HubSpot deal `amount` |
| `Project.DeliveryModels[]` | HubSpot custom property `govwin_ace_delivery_model` (manual entry) |
| `OpportunityType` | HubSpot custom property `govwin_ace_opportunity_type` (default "Net New Business") |
| `Origin` | Always `Partner Referral` |
| `PartnerOpportunityIdentifier` | HubSpot deal `govwin_id` |
| `PrimaryNeedsFromAws[]` | HubSpot custom property `govwin_ace_partner_need` (manual entry) |
| `LifeCycle.TargetCloseDate` | HubSpot deal `closedate` |
| `NationalSecurity` | `Yes` if HubSpot company is industry=Government, else `No` |
