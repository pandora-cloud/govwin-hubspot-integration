# Field-mapping parity: GovWin → HubSpot → AWS Partner Central

End-to-end accounting of every field that flows through the pipeline, plus what SaaSify maps as their default for the HubSpot → ACE leg. Use this to spot value gaps where AWS Partner Central accepts a field, GovWin populates it, and SaaSify ships a default mapping for it but our integration does not.

## How to read this

Each row is one logical concept (e.g. "company name", "expected spend amount") observed at three layers:

- **GovWin → HubSpot** (column 2): the GovWin source field, transformed by `src/sync/mapper.py`, written to a `govwin_*` HubSpot deal/company/contact property. Empty when the concept is HubSpot- or BD-originated.
- **HubSpot → ACE (ours)** (column 3): the AWS Partner Central Selling API field our `src/ace/mapper.py` populates from the HubSpot property. Empty when we don't map it.
- **HubSpot → ACE (SaaSify)** (column 4): the same AWS field per SaaSify's default mapping. **You fill this column in from SaaSify's "Field Mappings" admin screen**; when blank, treat as unknown rather than zero.

Action key:
- ✅ matches — both ours and SaaSify map this; nothing to do.
- ➕ add — SaaSify maps this and ours doesn't; we should add it.
- ➖ ours-only — we map this and SaaSify doesn't; verify the value is real (don't bloat for parity's sake).
- ❓ unknown — needs SaaSify-side data to resolve.

## How to fill column 4 (SaaSify defaults)

1. Open any HubSpot deal that shows the "Co-sell with AWS" card.
2. Click the card's gear / Configure icon → opens SaaSify's web app.
3. Navigate to **Field Mappings** (sometimes "Mappings" or "Sync Settings").
4. Export to CSV if available; otherwise screenshot each section.
5. For every row in the matrix, look up the corresponding AWS field on the SaaSify side and fill in the HubSpot property they read from. If SaaSify has no mapping for that AWS field, write "(unmapped)".

## AWS Partner Central required fields (CreateOpportunity)

These are the AWS-required fields. Every row in this section must have a non-empty column 3 (ours) on every successful submission, or AWS rejects.

| AWS Partner Central field | GovWin → HubSpot (ours) | HubSpot → ACE (ours) | HubSpot → ACE (SaaSify default) | Action |
|---|---|---|---|---|
| `Catalog` | n/a | constant: `Sandbox` or `AWS` (from `ace_catalog` tfvar) | likely a SaaSify config setting, not a deal-level mapping | ❓ confirm |
| `ClientToken` | n/a | generated, persisted in DynamoDB for retry-idempotency | likely SaaSify-internal | ❓ confirm |
| `Origin` | n/a | constant: `Partner Referral` | configurable (Partner Referral / AWS Referral) | ❓ confirm |
| `OpportunityType` | n/a | `govwin_ace_opportunity_type` (default `Net New Business`) | `govwin_ace_opportunity_type` or similar | ❓ |
| `PrimaryNeedsFromAws` | n/a | `govwin_ace_partner_need` (multi-select) | their property | ❓ |
| `PartnerOpportunityIdentifier` | `opportunity.id` → `govwin_opp_id` | `govwin_opp_id` | their deal-id mapping | ❓ |
| `Customer.Account.CompanyName` | `gov_entity.title` → `govwin_agency` | `govwin_agency` | likely the deal's associated company name | ❓ |
| `Customer.Account.Industry` | `primary_naics` (NAICS → AWS industry) → `govwin_industry` | `govwin_industry` (with `OtherIndustry` fallback) | their industry mapping | ❓ |
| `Customer.Account.WebsiteUrl` | n/a | derived: agency name → `https://www.<best-guess>.gov` | likely associated company's `domain` property | ❓ |
| `Customer.Account.Address.CountryCode` | `opportunity.country` → `govwin_country` | constant `US` (override path: tbd) | likely associated company's `country` | ❓ |
| `Customer.Account.Address.PostalCode` | n/a | constant `20001` (DC default) | likely associated company's `zip` | ❓ |
| `Customer.Account.Address.StateOrRegion` | n/a | constant `Dist. of Columbia` | likely associated company's `state` | ❓ |
| `Project.Title` | `opportunity.title` → `dealname` | `dealname` | `dealname` ✓ | ✅ |
| `Project.CustomerBusinessProblem` | `opportunity.description` → `description` | `description` | `description` ✓ | ✅ |
| `Project.CustomerUseCase` | n/a | `govwin_ace_use_case` (default `Migration / Database Migration`) | their property | ❓ |
| `Project.DeliveryModels` | n/a | `govwin_ace_delivery_model` | their property | ❓ |
| `Project.OtherSolutionDescription` | n/a | `govwin_ace_other_solution_description` (fallback to `dealname`) | their property | ❓ |
| `Project.ExpectedCustomerSpend[].Amount` | `opportunity.opp_value` (×1000) → `amount` | `amount` (HubSpot → string) | `amount` | ✅ |
| `Project.ExpectedCustomerSpend[].CurrencyCode` | n/a | constant `USD` | configurable | ❓ |
| `Project.ExpectedCustomerSpend[].Frequency` | n/a | constant `Monthly` | configurable | ❓ |
| `Project.ExpectedCustomerSpend[].TargetCompany` | n/a | constant: company name from `aws_account_id` | likely associated company name | ❓ |
| `Project.SalesActivities` | n/a | seeded default `["Initialized discussions with customer"]` | likely a HubSpot multi-select they own | ❓ |
| `LifeCycle.ReviewStatus` | n/a | constant `Pending Submission` (server-managed afterward) | constant | ✅ |
| `LifeCycle.TargetCloseDate` | `p_award_date_to` or `response_date` → `closedate` | `closedate` (defaults to today+180d when null) | `closedate` | ✅ |

## AWS Partner Central optional fields (CreateOpportunity)

These would add value to the AWS reviewer but are not required. Most likely candidates for SaaSify ↔ ours diff.

| AWS Partner Central field | GovWin → HubSpot (ours) | HubSpot → ACE (ours) | HubSpot → ACE (SaaSify default) | Action |
|---|---|---|---|---|
| `NationalSecurity` (Yes/No) | n/a (could derive from `cmmc_requirements`) | not mapped | likely a deal property like `aws_national_security` | ❓ likely ➕ |
| `Project.AdditionalComments` | n/a | not mapped | likely a free-text mapping | ❓ |
| `Project.CompetitorName` | n/a | not mapped | likely a deal property | ❓ |
| `Project.RelatedOpportunityIdentifier` | n/a | not mapped | likely a deal property | ❓ |
| `Project.SolutionsOfferedDescription` | n/a | not mapped | likely a deal property | ❓ |
| `Marketing.Source` (Marketing Campaign / Other) | n/a | not mapped | likely a HubSpot dropdown | ❓ likely ➕ |
| `Marketing.UseCases` | n/a | not mapped | likely a HubSpot multi-select | ❓ |
| `Marketing.Channel` | n/a | not mapped | likely a HubSpot dropdown | ❓ |
| `Marketing.AwsFundingUsed` (Yes/No) | n/a | not mapped | likely a HubSpot bool | ❓ likely ➕ |
| `Marketing.CampaignName` | n/a | not mapped | likely | ❓ |
| `SoftwareRevenue.Value.Amount` (for SaaS opps) | n/a | not mapped | likely if SaaSify supports SaaS-listed solutions | ❓ |
| `SoftwareRevenue.DeliveryModel` | n/a | not mapped | likely | ❓ |
| `SoftwareRevenue.EffectiveDate` | n/a | not mapped | likely | ❓ |
| `SoftwareRevenue.ExpirationDate` | n/a | not mapped | likely | ❓ |
| `Customer.Contacts[]` (CustomerContacts array) | `bundle.contacts` → HubSpot contact records (associated via deal-contact) | **not mapped to ACE** | **likely mapped — high-value gap** | ❓ likely ➕ |
| `LifeCycle.NextSteps` | n/a | not mapped | likely a deal property | ❓ |
| `LifeCycle.NextStepsHistory` | n/a | not mapped | n/a (server-tracked) | n/a |

## SaaSify-likely-but-API-rejected fields

Things SaaSify might map that AWS doesn't actually accept on CreateOpportunity (closed enums or server-only fields). Don't waste effort on these for parity:

- `LifeCycle.Stage` (server-only on Create)
- `Id`, `LastModifiedDate` (server-generated)
- `EngagementInvitationId`, `TaskId` (set during StartEngagementFromOpportunityTask)
- `AwsOpportunitySummary.*` (AWS-side fields populated by AWS reviewer)

## Once you've filled in column 4

Drop the populated matrix back in chat. I'll:

1. Open a PR that adds every ➕ row to `src/ace/mapper.py` with appropriate fall-throughs.
2. Update the HubSpot property catalog in `src/hubspot/properties.py` for any new BD-editable fields.
3. Add unit-test parity guards for each new mapping (mirroring the ones already in place for `CustomerUseCase`, `PrimaryNeedsFromAws`, `DeliveryModels`).
4. Re-run scenario 11 end-to-end to confirm the wider payload still gets accepted by AWS.

## End-to-end coverage today (column 2 → column 3, before the SaaSify diff)

| HubSpot deal property | GovWin source | ACE field |
|---|---|---|
| `dealname` | `opportunity.title` | `Project.Title` |
| `description` | `opportunity.description` (sanitized HTML) | `Project.CustomerBusinessProblem` |
| `amount` | `opportunity.opp_value × 1000` | `Project.ExpectedCustomerSpend[0].Amount` |
| `closedate` | `p_award_date_to` or `response_date` | `LifeCycle.TargetCloseDate` |
| `govwin_opp_id` | `opportunity.id` | `PartnerOpportunityIdentifier` |
| `govwin_agency` | `gov_entity.title` | `Customer.Account.CompanyName` |
| `govwin_industry` | NAICS-derived | `Customer.Account.Industry` |
| `govwin_ace_opportunity_type` | (set to `Net New Business`) | `OpportunityType` |
| `govwin_ace_partner_need` (BD-edited) | n/a | `PrimaryNeedsFromAws[]` |
| `govwin_ace_delivery_model` (BD-edited) | n/a | `Project.DeliveryModels[]` |
| `govwin_ace_use_case` (BD-edited) | n/a | `Project.CustomerUseCase` |
| `govwin_ace_other_solution_description` (BD-edited, optional) | n/a | `Project.OtherSolutionDescription` |
| `govwin_ace_solution_id` (BD-edited, optional) | n/a | `AssociateOpportunity(RelatedEntityType=Solutions)` |

GovWin-only (currently sit on HubSpot but not mapped to ACE — fine, they're for BD review):

`govwin_id`, `govwin_iq_opp_id`, `govwin_opp_type`, `govwin_status`, `govwin_solicitation_date`, `govwin_solicitation_number`, `govwin_source_url`, `govwin_iq_url`, `govwin_duration`, `govwin_primary_naics`, `govwin_naics_code`, `govwin_primary_requirement`, `govwin_analyst_notes`, `govwin_competition_type`, `govwin_contract_type`, `govwin_type_of_award`, `govwin_country`, `govwin_created_date`, `govwin_update_date`, `govwin_cmmc_requirements`, `govwin_smart_tags`, `govwin_priority`.
