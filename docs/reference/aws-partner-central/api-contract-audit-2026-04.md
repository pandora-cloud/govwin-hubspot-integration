# AWS Partner Central Selling API: contract audit (April 2026)

> Sweep of the canonical API contracts against the v2 implementation in `src/ace/`.
> Sources used:
> - boto3 1.43.0 service model `partnercentral-selling`, API version `2022-07-26` (`c.meta.service_model.operation_model(...)`).
> - AWS docs at `docs.aws.amazon.com/partner-central/latest/selling-api/` (CreateOpportunity, UpdateOpportunity, AssociateOpportunity, StartEngagementFromOpportunityTask, selling-api-events).
> - Captured 2026-04-30 in branch `feature/v2-ace-end-to-end`.

This document is the source of truth for fix-implementation work. Each section lists the canonical contract, what we currently send, and any drift. "MUST FIX" callouts mark places where our code is contradicting AWS.

## Executive summary of MUST FIX items

1. **`Project.ExpectedCustomerSpend[].Frequency` must be `"Monthly"`.** Boto3 enum is a single value, not `Annual | Monthly`. Our mapper hard-codes `"Monthly"` (correct), but the existing reference doc `api-create-opportunity.md` still says `Annual / Monthly`, and the HubSpot validation in `hubspot/properties.py` (if any) should not allow other values.
2. **`Customer.Account.Industry` is a strict enum** at the boto3 level. Our mapper passes through whatever HubSpot has in `govwin_industry`, which is set from a NAICS-derived label (commonly `"Government"`) but may be `"Government Administration"` or similar. Anything outside the enum will get a `ValidationException`. The valid values are the 28 listed below.
3. **`Customer.Account.Address.StateOrRegion` is a free string at the boto3 level** but is server-side validated as an enum **only when `CountryCode == "US"`** (full state name with the oddity `"Dist. of Columbia"`). Our `_normalize_state` helper handles US correctly but defaults to `"Dist. of Columbia"` for **any** missing state, including non-US addresses. For non-US the field should be omitted (or set to a non-US province name accepted by AWS). MUST FIX: do not force a US state value when the country is not US.
4. **`UpdateOpportunity` has true PUT semantics: omitted fields are nulled.** Our `scrub_for_update` whitelists the right top-level fields, but on `LifeCycle` we lose `Stage` / `ClosedLostReason` / `NextSteps` / `NextStepsHistory` / `ReviewComments` / `ReviewStatusReason` if we let our update Lambda drop them. Today our `update_in_ace` Lambda computes a sparse `LifeCycle` block with only the changed fields; if the caller does not echo back the existing fields, AWS will null them. MUST FIX: round-trip via `GetOpportunity` and merge, do not synthesize from scratch.
5. **`UpdateOpportunity` does NOT accept `OpportunityTeam`, `Origin`, or `Tags`.** Our `scrub_for_update` does not include any of these (good), but reviewers must know they cannot be added later via Update.
6. **`LifeCycle.ReviewStatus` enum value is `"In review"` (lowercase r).** Boto3 model confirms exact-case. Our codebase doesn't write it explicitly but any future filter / event handler must use the lowercase form.
7. **`PaymentFrequency` enum is `["Monthly"]` only.** No `Annual` / `Quarterly` despite older documentation. If we ever map an annual contract value we must re-amortize as monthly.
8. **`ListEngagementInvitations.ParticipantType` is REQUIRED** and uses uppercase `"SENDER"` / `"RECEIVER"` (the EventBridge event payload uses mixed-case `"Sender"` / `"Receiver"`). Don't conflate the two.
9. **`StartEngagementFromOpportunityTask.AwsSubmission.InvolvementType` enum is `"For Visibility Only" | "Co-Sell"`.** Our `config.ace.default_involvement_type` defaults to `"Co-Sell"` (verify in `src/config.py`). Anything else is an immediate `ValidationException`.
10. **Every state-level write must echo `PartnerOpportunityIdentifier`** because Update has PUT semantics. `scrub_for_update` handles this; the `update_in_ace` Lambda must build the full payload from a fresh GetOpportunity, not from cached deltas.
11. **`engagementId`, `engagementInvitationId`, and `taskId` patterns are stricter than our current validators.** `is_valid_aws_opportunity_id` allows `[A-Za-z0-9_-]+`, but the canonical patterns are: opportunity `O[0-9]{1,19}`, engagement `eng-[0-9a-z]{14}`, invitation `engi-[0-9,a-z]{13}`, task `.*task-[0-9a-z]{13}` (note the literal `task-` substring), snapshot job `job-[0-9a-z]{13}`, solution `S-[0-9]{1,19}`. Tighten the validators so we don't accept malformed ids from webhook events.
12. **`Phone` regex is `\+[1-9]\d{1,14}` (E.164) and `Email` is lowercase-only with an 80-char total cap.** If Contacts ever populate from HubSpot, sanitize first or AWS will reject the whole CreateOpportunity payload.

The remaining sections expand on each operation.

---

## 1. CreateOpportunity

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_CreateOpportunity.html` (canonical) and boto3 `CreateOpportunityRequest` (binding contract on the wire).

### 1.1 Required fields (boto3 service model)

Per the boto3 service model, only **two** fields are formally required at the SDK boundary:

| Field | Type | Pattern / enum | Notes |
|---|---|---|---|
| `Catalog` | string | `[a-zA-Z]+` | Effectively `AWS` or `Sandbox`; the regex is loose but server-side rejects anything else. |
| `ClientToken` | string | `.{1,255}` | Idempotency key. UUID4 fits in 36 chars. ConflictException if reused with a different body. |

Everything else is technically optional at the SDK layer but enforced at the **business validation** layer when you call `StartEngagementFromOpportunityTask`. AWS's docs list "mandatory fields to create opportunities" prose that does not match the strict SDK model: in practice you can `CreateOpportunity` with just Catalog + ClientToken and then iterate via `UpdateOpportunity`, but you cannot `StartEngagementFromOpportunityTask` until the opportunity has a complete payload.

### 1.2 Required-for-submission fields (business rules)

These must be populated before `StartEngagementFromOpportunityTask` will accept the opportunity. The mapper enforces this on create so we don't have to chase the validation error later.

| Field | Type | Constraints | We send? |
|---|---|---|---|
| `PrimaryNeedsFromAws[]` | list of enum | see 1.4.1 | Yes, from `govwin_ace_partner_need` (manual). |
| `Project.DeliveryModels[]` | list of enum | see 1.4.2 | Yes, from `govwin_ace_delivery_model` (manual). |
| `Project.ExpectedCustomerSpend[]` | list of struct, max 10 | see 1.4.3 | Yes, one entry derived from `amount`. |
| `Project.Title` | string | `(?s).{0,255}` | Yes, from `dealname` truncated to 255. |
| `Project.CustomerBusinessProblem` | string | `(?s).{20,2000}` | Yes, padded to 20 chars min in `_project_block`. |
| `Project.CustomerUseCase` | string | server-side enum (not in boto3 model) | Yes, default `"Migration / Database Migration"`. |
| `Customer.Account.CompanyName` | string | `(?s).{0,120}` | Yes, from `govwin_agency`. |
| `Customer.Account.Industry` | enum (28 values) | see 1.4.4 | Yes, but we pass `govwin_industry` through unchanged — drift risk. |
| `Customer.Account.WebsiteUrl` | string | `(?s).{4,255}` | Yes, fallback to `https://www.usa.gov`. |
| `Customer.Account.Address.CountryCode` | enum (250 ISO-2) | see 1.4.5 | Yes, hard-coded `"US"`. |
| `Customer.Account.Address.PostalCode` | string | `(?s).{0,20}` | Yes, fallback `"20001"`. |
| `Customer.Account.Address.StateOrRegion` | string (server-side US state enum when CountryCode=US) | see 1.4.6 | Yes, but with a US-only normalizer. |
| `LifeCycle.TargetCloseDate` | date `YYYY-MM-DD` | `[1-9][0-9]{3}-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01])` | Yes, from HubSpot `closedate[:10]`. |
| `LifeCycle.ReviewStatus` | enum | see 1.4.7 | Yes, hard-coded `"Pending Submission"`. |
| `OpportunityType` | enum | `Net New Business | Flat Renewal | Expansion` | Yes, hard-coded `"Net New Business"`. |
| `Origin` | enum | `AWS Referral | Partner Referral` | Yes, from `config.ace.default_origin`. For `Catalog: AWS` MUST be `Partner Referral`. |
| `PartnerOpportunityIdentifier` | string | `(?s).{0,64}` | Yes, from `govwin_opp_id`. **Must echo on every Update**. |

### 1.3 Optional fields we currently populate

| Field | Source | Notes |
|---|---|---|
| `Project.OtherSolutionDescription` | `govwin_ace_other_solution_description` else dealname (capped at 255) | Required when no Solution is associated; safe to always set. |
| `Project.ExpectedCustomerSpend[0].TargetCompany` | hard-coded `"Pandora Cloud LLC"` | Should be derived from `config.partner_company_name`. |
| `Project.ExpectedCustomerSpend[0].CurrencyCode` | hard-coded `"USD"` | Could be derived from HubSpot's deal currency property. |

### 1.4 Server-side enums and constraints

#### 1.4.1 PrimaryNeedsFromAws (boto3 enum, exact strings)
```
Co-Sell - Architectural Validation
Co-Sell - Business Presentation
Co-Sell - Competitive Information
Co-Sell - Pricing Assistance
Co-Sell - Technical Consultation
Co-Sell - Total Cost of Ownership Evaluation
Co-Sell - Deal Support
Co-Sell - Support for Public Tender / RFx
```
Note the spaces around the dash (Unicode U+002D) and the literal `/` in `Tender / RFx`. AWS's prose docs describe these with `Cosell—` (em dash) but the wire values use `Co-Sell - `. Use the boto3 form.

The HubSpot `govwin_ace_partner_need` property uses short labels (e.g. `"Technical Consultation"`); the `_HUBSPOT_PARTNER_NEED_TO_AWS` map in `mapper.py` translates them. This translation table should ship in `docs/reference/aws-partner-central/` so OSS users can configure their HubSpot property options without reverse-engineering the code:

| HubSpot short label (option value) | AWS PrimaryNeedsFromAws enum |
|---|---|
| Architectural Validation | Co-Sell - Architectural Validation |
| Business Presentation | Co-Sell - Business Presentation |
| Competitive Intelligence (or Information) | Co-Sell - Competitive Information |
| Pricing Assistance | Co-Sell - Pricing Assistance |
| Technical Consultation | Co-Sell - Technical Consultation |
| Total Cost of Ownership Evaluation | Co-Sell - Total Cost of Ownership Evaluation |
| Deal Support | Co-Sell - Deal Support |
| Support for Public Tender (or `... / RFx`) | Co-Sell - Support for Public Tender / RFx |

#### 1.4.2 Project.DeliveryModels (boto3 enum)
```
SaaS or PaaS, BYOL or AMI, Managed Services, Professional Services, Resell, Other
```
Our `ALLOWED_DELIVERY_MODELS` matches.

#### 1.4.3 Project.ExpectedCustomerSpend struct
- `Amount` regex: `((0|([1-9][0-9]{0,30}))(\.[0-9]{0,2})?)?` (2 decimals max, no leading zero unless `0`).
- `CurrencyCode` enum: 156 ISO 4217 codes; `USD` is fine.
- **`Frequency` enum: `["Monthly"]` ONLY** — no `Annual` or `Quarterly`.
- `TargetCompany` regex: `(?s).{1,80}` (1-80 chars, required).
- `EstimationUrl` regex: `https://(calculator\.aws|pricing\.calculator\.aws\.eu)/#/estimate\?id=[a-f0-9]{32,64}`.
- List bounds: `min=0, max=10`.

**MUST FIX (already correct, document for OSS):** `_project_block` hard-codes `"Monthly"`. Keep it that way. Update the existing `api-create-opportunity.md` table that says `Annual/Monthly`.

#### 1.4.4 Customer.Account.Industry (strict enum, 28 values)
```
Aerospace, Agriculture, Automotive, Computers and Electronics, Consumer Goods,
Education, Energy - Oil and Gas, Energy - Power and Utilities, Financial Services,
Gaming, Government, Healthcare, Hospitality, Life Sciences, Manufacturing,
Marketing and Advertising, Media and Entertainment, Mining, Non-Profit Organization,
Professional Services, Real Estate and Construction, Retail, Software and Internet,
Telecommunications, Transportation and Logistics, Travel,
Wholesale and Distribution, Other
```
If `Industry == "Other"`, populate `OtherIndustry` (free text, `(?s).{0,255}`).

**MUST FIX:** `_customer_block` falls back to `"Government"` (in-enum) but otherwise passes `govwin_industry` through. The HubSpot mapper sets `govwin_industry` from a NAICS-derived label (`src/sync/mapper.py`); confirm that label set is restricted to the AWS enum or add a normalization map. If unmappable, set `Industry = "Other"` and put the full label into `OtherIndustry`.

#### 1.4.5 CountryCode (ISO 3166-1 alpha-2 enum, 250 values)
We hard-code `"US"`. Keep that for federal-government opps. If we ever sync state/local opps for other geos this becomes a real lookup.

#### 1.4.6 StateOrRegion (server-side US state enum)
Boto3 only types this as `string`. The server enforces an enum **when `CountryCode == "US"`**, with these notable quirks (verified against AWS console drop-down):
- `Dist. of Columbia` (not `District of Columbia`).
- Territories use full names (`Puerto Rico`, `Virgin Islands`, `Guam`, etc.).
- US military APO/FPO codes are not in the enum.

**MUST FIX:** `_normalize_state` returns `"Dist. of Columbia"` when `value` is empty, but does so unconditionally. If `CountryCode != "US"`, this is wrong and will fail validation. Fix: only run the US-state lookup when CountryCode == "US"; for non-US, omit the field or pass through unchanged.

#### 1.4.7 LifeCycle enums (boto3-confirmed exact-case)
- `Stage`: `Prospect | Qualified | Technical Validation | Business Validation | Committed | Launched | Closed Lost`.
- `ClosedLostReason` (19 values): `Customer Deficiency, Delay / Cancellation of Project, Legal / Tax / Regulatory, Lost to Competitor - Google, Lost to Competitor - Microsoft, Lost to Competitor - SoftLayer, Lost to Competitor - VMWare, Lost to Competitor - Other, No Opportunity, On Premises Deployment, Partner Gap, Price, Security / Compliance, Technical Limitations, Customer Experience, Other, People/Relationship/Governance, Product/Technology, Financial/Commercial`.
- **`ReviewStatus`: `Pending Submission | Submitted | In review | Approved | Rejected | Action Required`** — note `In review` (lowercase r). The AWS prose docs use mixed case in some places; the boto3 model is authoritative.
- `NextSteps` regex: `(?s).{0,255}` (255 chars max).
- `TargetCloseDate` regex: `[1-9][0-9]{3}-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01])`.

#### 1.4.8 Project.CustomerUseCase (server-side enum, NOT in boto3 model)
Boto3 types this as plain `string` with no enum. The actual enum is enforced server-side and surfaces only via `ValidationException.ErrorList`. Our `ALLOWED_CUSTOMER_USE_CASES` set in `mapper.py` is sourced from prior validation errors; treat it as approximate. Refresh by sending an unknown value and reading the error. The list is broader than "AWS service category" — it includes vertical industry use cases (`SAP`, `Healthcare and Life Sciences`).

**Open question for OSS docs:** The use-case list is the same regardless of region/program based on our sandbox testing, but AWS does not publish a canonical reference. Document both: that the list is inferred and that the server is the ultimate gate.

#### 1.4.9 Project.SalesActivities (8 enum values)
```
Initialized discussions with customer, Customer has shown interest in solution,
Conducted POC / Demo, In evaluation / planning stage,
Agreed on solution to Business Problem, Completed Action Plan,
Finalized Deployment Need, SOW Signed
```
Not currently populated. Could be auto-derived from HubSpot dealstage in a future iteration.

#### 1.4.10 Project.CompetitorName (11 values)
```
Oracle Cloud, On-Prem, Co-location, Akamai, AliCloud, Google Cloud Platform,
IBM Softlayer, Microsoft Azure, Other- Cost Optimization, No Competition, *Other
```
Note the literal asterisk in `*Other` and the missing space in `Other- Cost Optimization`. If `CompetitorName == "*Other"`, populate `OtherCompetitorNames` (`(?s).{0,255}`).

#### 1.4.11 NationalSecurity
Enum `Yes | No`. AWS rule: only set `Yes` when `Customer.Account.Industry == "Government"`. Our mapper does not currently populate this. **Recommendation:** when `Industry == "Government"`, default to `"No"` unless the deal has a HubSpot flag; this is harmless and shows up in the AWS UI. (`MUST FIX` only if AWS starts requiring it on the federal track.)

### 1.5 Response shape
```json
{
  "Id": "O123456789",                       // matches O[0-9]{1,19}
  "PartnerOpportunityIdentifier": "...",
  "LastModifiedDate": "2026-04-28T22:24:33.498Z"
}
```
**Drift watch:** the AWS docs claim `PartnerOpportunityIdentifier` is in the response, but our sandbox tests show it can be **omitted** when set on input. Our state-write code in `submit_to_ace.py` should not require it from the response — read it from the request payload we sent.

### 1.6 Error codes (canonical)
- `ValidationException` (400) with `Reason: REQUEST_VALIDATION_FAILED | BUSINESS_VALIDATION_FAILED`. Includes `ErrorList[]` with per-field `FieldName` and `Message`. Do not retry.
- `ConflictException` (400) — typically ClientToken reuse with mismatched body. Generate a new token.
- `AccessDeniedException` (400) — IAM. Do not retry.
- `ResourceNotFoundException` (400) — referenced entity missing.
- `InternalServerException` (500) — retry with backoff.
- `ThrottlingException` (400) — retry with backoff.

Our `_is_retryable` catches `ThrottlingException`, `InternalServerException`, `ServiceUnavailableException`. Add `ServiceQuotaExceededException` (used by StartEngagement) — currently treated as fatal but it's effectively a longer-term throttle.

---

## 2. UpdateOpportunity

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_UpdateOpportunity.html` and boto3 `UpdateOpportunityRequest`.

### 2.1 Required fields
| Field | Type | Notes |
|---|---|---|
| `Catalog` | string | Same enum as Create. |
| `Identifier` | string | `O[0-9]{1,19}` — opportunity id from CreateOpportunity. |
| `LastModifiedDate` | timestamp | Optimistic-locking token. Must match the most recent value or `ConflictException`. |

### 2.2 PUT semantics: omit-as-null

Per AWS doc verbatim: *"When you perform updates, include the entire payload with each request. If any field is omitted, the API assumes that the field is set to `null`."*

This is the most dangerous behavior in the API.

**MUST FIX:** `update_in_ace` Lambda must always:
1. Call `GetOpportunity` to fetch the current state.
2. Pass the result through `scrub_for_update` to drop server-only fields.
3. Apply the deltas from the HubSpot webhook on top of the scrubbed state.
4. Call `UpdateOpportunity` with the merged payload.

If we ever skip step 1 and just write a sparse delta, AWS will null every field we didn't echo. The `update_with_retry` helper in `client.py` already does step 1 implicitly (to fetch `LastModifiedDate`); the `update_in_ace` Lambda must use the **same Get response** as the merge base, not synthesize from cached deltas.

### 2.3 Fields accepted by Update (per boto3 input shape)

| Field | Same constraints as Create? |
|---|---|
| `Customer` (full struct) | yes |
| `LifeCycle` (full struct) | yes |
| `Marketing` (full struct) | yes |
| `NationalSecurity` | yes |
| `OpportunityType` | yes |
| `PartnerOpportunityIdentifier` | yes |
| `PrimaryNeedsFromAws[]` | yes |
| `Project` (full struct) | yes |
| `SoftwareRevenue` (full struct) | yes |

### 2.4 Fields NOT accepted by Update

| Field | Reason |
|---|---|
| `Origin` | Immutable post-create. |
| `Tags` | Use `TagResource` / `UntagResource` separately. |
| `OpportunityTeam` | Not in the Update shape (only on Create). Cannot be edited via Update. |
| `RelatedEntityIdentifiers` (Solutions, AwsProducts, AwsMarketplaceOffers) | Use `AssociateOpportunity` / `DisassociateOpportunity`. |
| `ClientToken` | Update is not idempotent; use `LastModifiedDate` for safety. |

**Verification of `scrub_for_update`:** the current whitelist is `{PrimaryNeedsFromAws, NationalSecurity, Customer, Project, OpportunityType, Marketing, SoftwareRevenue, LifeCycle, PartnerOpportunityIdentifier}`. This matches the boto3 input shape. Good.

### 2.5 Lock state after StartEngagementFromOpportunityTask

AWS docs: *"After submission, you can't edit the opportunity until the review is complete."* In practice:
- Once `Lifecycle.ReviewStatus` transitions out of `"Pending Submission"` (i.e. `"Submitted" | "In review" | "Approved" | "Rejected" | "Action Required"`), `UpdateOpportunity` returns `ValidationException (BUSINESS_VALIDATION_FAILED)`.
- The `ReviewStatus = "Action Required"` state is the only post-submit state where AWS asks the partner to edit; this is gated by AWS-side workflow, not unconditional.

**MUST FIX:** `update_in_ace` Lambda should pre-flight via `GetOpportunity` and short-circuit with a "skipped: opportunity locked for review" log entry when `ReviewStatus != "Pending Submission"` and `ReviewStatus != "Action Required"`. Surface this as a HubSpot deal note so the BD team knows their edits aren't being propagated.

### 2.6 Marketing / SoftwareRevenue conditions

These are optional structs. Per AWS docs they're "required only for partners in eligible programs" (typically AWS Marketplace SaaS sellers and ISVs in the SaaS Revenue Recognition program). For a co-sell-only services partner like Pandora Cloud, omitting both is correct.

**Drift note:** AWS does not document a "conditional require" rule for `Marketing` or `SoftwareRevenue` on UpdateOpportunity. The behavior is: if you populated them at create, you must echo them on update (PUT semantics); if you didn't, you can keep omitting them. There is **no** "do not echo unset fields" toggle — the PUT semantics are absolute. The only way to clear a previously-set Marketing or SoftwareRevenue is to send the struct with empty/null sub-fields explicitly (subject to the sub-field's own validators).

---

## 3. AssociateOpportunity / DisassociateOpportunity

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_AssociateOpportunity.html` and boto3 model.

### 3.1 Request shape

```json
{
  "Catalog": "AWS",
  "OpportunityIdentifier": "O123456789",
  "RelatedEntityType": "Solutions",
  "RelatedEntityIdentifier": "S-1234"
}
```

All four fields are required. Response is HTTP 200 with empty body.

### 3.2 RelatedEntityType enum
`Solutions | AwsProducts | AwsMarketplaceOffers | AwsMarketplaceOfferSets`.

### 3.3 RelatedEntityIdentifier patterns by type
- Solutions: `S-[0-9]{1,19}` (from `ListSolutions`).
- AwsProducts: free string; values are AWS product codes from the published list.
- AwsMarketplaceOffers: ARN pattern `arn:aws:aws-marketplace:[a-z]{1,2}-[a-z]*-\d+:\d{12}:AWSMarketplace/Offer/.*`.
- AwsMarketplaceOfferSets: ARN pattern `arn:aws:aws-marketplace:[a-z]{1,2}-[a-z]*-\d+:\d{12}:AWSMarketplace/OfferSet/offerset-.*`.

### 3.4 When to use `OtherSolutionDescription` instead

If we have no Solution to associate (e.g. Sandbox catalog with no migrated solutions, or a deal where the BD team didn't pick one), populate `Project.OtherSolutionDescription` on the create/update payload (255-char free text). Our mapper does this unconditionally as a fallback.

`StartEngagementFromOpportunityTask` will accept the opportunity with either:
- at least one Solution association (via `AssociateOpportunity`), OR
- a non-empty `Project.OtherSolutionDescription`.

If both are absent, you get `OpportunityValidationFailed`.

### 3.5 Errors specific to associate
- `ResourceNotFoundException` if the Solution / Product ARN doesn't exist or isn't visible to the calling account.
- `AccessDeniedException` if the IAM principal doesn't have `partnercentral:AssociateOpportunity`.
- `ConflictException` if the same association already exists (idempotency: catch and treat as success).

### 3.6 Drift from current implementation

Our `associate_opportunity` raises `ACEAPIError` on `ConflictException`. Treat this as a soft success ("already associated, move on") rather than DLQ-ing the deal.

---

## 4. StartEngagementFromOpportunityTask

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_StartEngagementFromOpportunityTask.html` and boto3 model.

### 4.1 What it actually does

The doc explicitly enumerates the internal actions:

1. `GetOpportunity` (sanity-check the resource exists and is in `Pending Submission`).
2. `CreateEngagement` (if no engagement exists for this opportunity).
3. `CreateResourceSnapshot` (point-in-time of the opportunity, gated by a snapshot template).
4. `CreateResourceSnapshotJob` (attach the snapshot to the engagement).
5. `CreateEngagementInvitation` (if not already invited or accepted).
6. `SubmitOpportunity` (move ReviewStatus from `"Pending Submission"` to `"Submitted"`).

This means our **IAM policy must allow all six underlying actions**, not just `partnercentral:StartEngagementFromOpportunityTask`. Specifically the calling principal needs:
```
partnercentral:GetOpportunity
partnercentral:CreateEngagement
partnercentral:CreateResourceSnapshot
partnercentral:CreateResourceSnapshotJob
partnercentral:CreateEngagementInvitation
partnercentral:SubmitOpportunity
partnercentral:StartEngagementFromOpportunityTask
```
plus the `partnercentral:Catalog` condition matching the catalog. **MUST FIX (verify):** check `terraform/modules/ace/iam.tf` (or equivalent) and confirm all seven are present with the Catalog condition.

### 4.2 Request shape

```json
{
  "Catalog": "AWS",
  "ClientToken": "<uuid>",
  "Identifier": "O123456789",
  "AwsSubmission": {
    "InvolvementType": "Co-Sell",
    "Visibility": "Full"
  },
  "Tags": [{"Key": "Source", "Value": "GovWin"}]
}
```

| Field | Required | Constraint |
|---|---|---|
| `Catalog` | yes | `[a-zA-Z]+`, effectively `AWS | Sandbox` |
| `ClientToken` | yes | `.{1,255}`. Persist in DynamoDB before the call so retries reuse it. |
| `Identifier` | yes | `O[0-9]{1,19}`. |
| `AwsSubmission.InvolvementType` | yes | enum `For Visibility Only | Co-Sell` |
| `AwsSubmission.Visibility` | no | enum `Full | Limited` |
| `Tags[]` | no | min=1, max=200. Same key/value patterns as CreateOpportunity. |

### 4.3 Response shape

```json
{
  "TaskId": "...task-1234567890abc",     // pattern: .*task-[0-9a-z]{13}
  "TaskArn": "arn:...",
  "TaskStatus": "IN_PROGRESS",            // enum: IN_PROGRESS | COMPLETE | FAILED
  "StartTime": "2026-04-28T22:30:00Z",
  "OpportunityId": "O123456789",
  "EngagementId": "eng-...",              // populated when COMPLETE; pattern: eng-[0-9a-z]{14}
  "EngagementInvitationId": "engi-...",   // populated when COMPLETE; pattern: engi-[0-9,a-z]{13}
  "ResourceSnapshotJobId": "job-...",     // populated when COMPLETE; pattern: job-[0-9a-z]{13}
  "Message": "...",                       // populated when FAILED
  "ReasonCode": "..."                     // populated when FAILED; see 4.5
}
```

**Drift note:** The doc text says `^oit-[0-9a-z]{13}$` for `TaskId`, but the actual pattern in the boto3 model is `.*task-[0-9a-z]{13}` (note `task-` not `oit-`). Trust boto3.

### 4.4 What edits get locked

After `SubmitOpportunity` runs (step 6 of the task), `Lifecycle.ReviewStatus` transitions from `"Pending Submission"` to `"Submitted"`. From that moment forward:
- `UpdateOpportunity` returns `ValidationException` until ReviewStatus goes back to `"Pending Submission"` or `"Action Required"`.
- `AssociateOpportunity` and `DisassociateOpportunity` are also locked.
- The opportunity moves into AWS's review queue (24-72 hours typical SLA).

### 4.5 Failure ReasonCode enum (boto3 confirmed, 23 values)
```
InvitationAccessDenied, InvitationValidationFailed, EngagementAccessDenied,
OpportunityAccessDenied, ResourceSnapshotJobAccessDenied,
ResourceSnapshotJobValidationFailed, ResourceSnapshotJobConflict,
EngagementValidationFailed, EngagementConflict, OpportunitySubmissionFailed,
EngagementInvitationConflict, InternalError, OpportunityValidationFailed,
OpportunityConflict, ResourceSnapshotAccessDenied,
ResourceSnapshotValidationFailed, ResourceSnapshotConflict,
ServiceQuotaExceeded, RequestThrottled, ContextNotFound,
CustomerProjectContextNotPermitted, DisqualifiedLeadNotPermitted
```

Important interpretation:
- `OpportunityValidationFailed` = the opportunity is missing required-for-submit fields (PrimaryNeedsFromAws, ExpectedCustomerSpend, DeliveryModels, or no Solution/OtherSolutionDescription). Our mapper guards against this on Create, but if we fall behind on schema changes (e.g. AWS adds a new mandatory field) this is the failure mode.
- `OpportunityConflict` = `Pending Submission` already submitted. Idempotent; treat as success.
- `EngagementConflict` / `EngagementInvitationConflict` = retry of an in-flight task. Caller should look up the existing `EngagementId` via `ListEngagementInvitations`.
- `RequestThrottled` / `ServiceQuotaExceeded` = transient. Retry with backoff.

---

## 5. GetOpportunity

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_GetOpportunity.html` and boto3 model.

### 5.1 Request

```json
{ "Catalog": "AWS", "Identifier": "O123456789" }
```

Both required. No paging. **No eventual consistency window documented**, but in practice we have observed up to ~3 seconds between a successful CreateOpportunity and the same record being readable. Build retries accordingly (not failing on ResourceNotFoundException for the first 5 seconds after Create).

### 5.2 Response (vs Create input shape)

The response shape **adds**:
- `Id` (the AWS-generated opportunity id, pattern `O[0-9]{1,19}`).
- `Arn` (`arn:.*`).
- `CreatedDate` (timestamp).
- `LastModifiedDate` (timestamp).
- `RelatedEntityIdentifiers`: a struct with `Solutions[]`, `AwsProducts[]`, `AwsMarketplaceOffers[]`, `AwsMarketplaceOfferSets[]` arrays.
- `OpportunityTeam` (back; create accepts it, get returns it, update does not accept it).

The response shape **omits or behaves differently for**:
- `PartnerOpportunityIdentifier` is named `PartnerOpportunityIdentifier` but with a different boto3 type alias (`GetOpportunityResponsePartnerOpportunityIdentifierString`). Same regex as Create. **Sandbox observation:** sometimes empty in the response even when it was set on input. Treat as best-effort; do not rely on it for state reconciliation.
- `ClientToken` is not echoed back (idempotency token; partners don't need it post-create).
- `Tags` is not part of the GetOpportunity response (use `ListTagsForResource`).

### 5.3 Pagination

`GetOpportunity` returns one record. For pagination, use `ListOpportunities`:
- `MaxResults`: 1-100, default 10.
- `NextToken`: opaque cursor.
- Filters: `Identifier[]` (max 20), `LifeCycleStage[]` (max 10), `LifeCycleReviewStatus[]` (max 10), `CustomerCompanyName[]` (max 10), `LastModifiedDate{After, Before}`, `CreatedDate{After, Before}`, `TargetCloseDate{After, Before}`.
- Sort: `SortBy` enum `LastModifiedDate | Identifier | CustomerCompanyName | CreatedDate | TargetCloseDate`; `SortOrder` enum `ASCENDING | DESCENDING`.

`ListOpportunities` returns `OpportunitySummary[]` (a subset of fields, no `Project` detail beyond `ProjectSummary`). **Use it for incremental sync, not for fetching the full payload pre-update.**

---

## 6. EventBridge events (`aws.partnercentral-selling`)

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/selling-api-events.html`.

### 6.1 Event-bus configuration

- Source name: `aws.partnercentral-selling`.
- Bus: the partner's **default** bus.
- Region: **must** be `us-east-1` (only region that publishes these events).

### 6.2 The ten event detail-types

| detail-type | Trigger (per AWS doc) |
|---|---|
| `Opportunity Created` | New opportunity (you or AWS). |
| `Opportunity Updated` | Existing opportunity changed (you or AWS). |
| `Engagement Invitation Created` | New invitation (Sender or Receiver). |
| `Engagement Invitation Accepted` | Other side accepted. |
| `Engagement Invitation Rejected` | Other side declined. |
| `Engagement Invitation Expired` | 15 days no action. |
| `Engagement Member Added` | New member joined. |
| `Engagement Resource Snapshot Created` | Snapshot revision (template-gated). |
| `Engagement Created` | New engagement. |
| `Engagement Updated` | Engagement metadata changed. |

### 6.3 Common envelope

All events share the EventBridge envelope:
```json
{
  "version": "0",                                    // sometimes "1"
  "id": "<uuid>",
  "source": "aws.partnercentral-selling",
  "detail-type": "<one of the ten>",
  "time": "<ISO-8601>",
  "region": "us-east-1",
  "account": "<12-digit account id>",
  "resources": ["arn:..."],                          // not always present
  "detail": { ... }                                  // shape varies per event
}
```

**`detail.catalog` is present on every event we have observed.** The doc samples confirm `catalog: "<Sandbox | AWS>"` in `detail` for all event types. Our EventBridge rules can rely on it for filtering.

### 6.4 Per-event detail shapes

#### 6.4.1 Opportunity Created / Opportunity Updated
```json
{
  "schemaVersion": "<version number>",
  "catalog": "AWS",
  "opportunity": { "identifier": "O..." }
}
```
The full opportunity is **not** included. Handler must call `GetOpportunity` to read state. Batch these or rate-limit if many events arrive in a burst.

#### 6.4.2 Engagement Invitation Created / Accepted / Rejected / Expired
```json
{
  "catalog": "AWS",
  "engagementInvitation": {
    "arn": "arn:aws:partnercentral:us-east-1::catalog/AWS/engagement-invitation/engi-...",
    "id": "engi-...",
    "engagementId": "eng-...",
    "senderAccountId": "string",
    "receiverAccountId": "string",
    "senderCompanyName": "string",                   // Created only
    "expirationDate": "string",                      // Created only
    "participantType": "Sender | Receiver",
    "payloadType": "OpportunityInvitation | LeadInvitation"
  }
}
```
**Note `participantType` is mixed-case (`Sender`/`Receiver`)** — different from the `ListEngagementInvitations.ParticipantType` filter parameter (uppercase `SENDER`/`RECEIVER`).

The `Created` event includes `expirationDate` and `senderCompanyName`; the other three reuse the same struct minus those two fields.

#### 6.4.3 Engagement Member Added
```json
{
  "catalog": "AWS",
  "engagement": { "id": "eng-..." },
  "engagementMember": {
    "accountId": "string",
    "companyName": "string"
  }
}
```

#### 6.4.4 Engagement Resource Snapshot Created
```json
{
  "catalog": "AWS",
  "resourceSnapshot": {
    "arn": "arn:aws:partnercentral-selling:us-east-1::catalog/AWS/engagement/eng-.../resource/Opportunity/o-.../template/<template-name>/snapshot/snapshot-...",
    "engagementId": "eng-...",
    "resourceType": "Opportunity",
    "resourceId": "O...",
    "createdBy": "string",
    "targetMemberAccounts": ["...", "aws"],
    "resourceSnapshotTemplateName": "<template-name>"
  }
}
```
Note `resourceId` here is the partner-side opportunity id (`O...` format) — the partner opportunity identifier we set, not the AWS-side opportunity id. **Verify this against a real Sandbox event.** Our `handle_ace_event` Lambda treats the value as an AWS opportunity id; if it's actually the partner opportunity identifier we need to lookup the AWS id via DynamoDB.

#### 6.4.5 Engagement Created / Engagement Updated
```json
{
  "catalog": "AWS",
  "engagement": {
    "engagementArn": "arn:...",
    "engagementId": "eng-...",
    "CreatedAt": "<ISO-8601>",                       // Created only
    "CreatedBy": "string",                           // Created only
    "LastModifiedAt": "<ISO-8601>",                  // Updated only
    "LastModifiedBy": "string",                      // Updated only
    "ContextTypes": ["Lead", "CustomerProject", ...]
  }
}
```

### 6.5 Which events fire during StartEngagementFromOpportunityTask

The doc's "Action by you as a partner" table answers the original question explicitly:

> You use `StartEngagementFromOpportunityTask` to submit an opportunity →
> **Opportunity Updated, Engagement Created, Engagement Resource Snapshot Created, Engagement Member Added, Engagement Invitation Created**.

In order:
1. `Engagement Created` (engagement appears).
2. `Engagement Member Added` (you are added as a member of your own engagement).
3. `Engagement Resource Snapshot Created` (snapshot of the opportunity attached).
4. `Engagement Invitation Created` (invitation to AWS, `participantType: Sender`).
5. `Opportunity Updated` (because `Lifecycle.ReviewStatus` flipped to `Submitted`).

**The `EngagementInvitationId` carries on the `Engagement Invitation Created` event detail.** The `EngagementId` carries on both `Engagement Created` (as `engagement.engagementId`) and `Engagement Invitation Created` (as `engagementInvitation.engagementId`).

The `Opportunity Updated` event carries only the opportunity identifier; you must call `GetOpportunity` to see the new ReviewStatus.

### 6.6 Idempotency

EventBridge can deliver duplicates. The `id` field is unique per event delivery and is the right dedup key. Our pattern:
1. On invocation, atomically write `event#{id}` to DynamoDB (with conditional `attribute_not_exists`) and TTL of 24 hours.
2. On `ConditionalCheckFailedException`, return success without doing the work.

This matches the existing dedup approach in `src/sync/dedup.py`.

---

## 7. Quotas, errors, and retry posture

**Source:** `https://docs.aws.amazon.com/partner-central/latest/selling-api/quotas.html` (cross-referenced in our existing `quotas-and-limits.md`).

| Quota | Value | Notes |
|---|---|---|
| Write requests per second | 1 | Token bucket; bursts above 1/s throttle. |
| Write requests per 24 hours | 10,000 | Hard quota; ServiceQuotaExceededException. |
| Read requests per second | 10 | Token bucket. |
| Read requests per 24 hours | 100,000 | Hard quota. |
| Tags per resource | 200 | |
| ExpectedCustomerSpend list size | 10 | |
| OpportunityTeam list size | 10 | |
| NextStepsHistory list size | 50 | |

`SubmitOpportunity` and `StartEngagementFromOpportunityTask` count as write quota. Our `ACERateLimiter` uses 1 write/sec and 10 reads/sec which matches.

### 7.1 Common error families
- `ValidationException` (400): non-retryable, fix payload. Includes `ErrorList[]` with field-level diagnostics — log and surface to BD team.
- `ConflictException` (400): typically idempotency-token reuse OR optimistic-locking failure on Update. For Update, refetch and retry up to 3 times (our `update_with_retry` does this).
- `ResourceNotFoundException` (400): caller error or eventual consistency. Retry once after 2s if the create just happened.
- `AccessDeniedException` (400): IAM. Do not retry; alert.
- `InternalServerException` (500): retry with exponential backoff (our tenacity config: 1-30s, max 5 attempts).
- `ThrottlingException` (400): retry with exponential backoff. AWS recommends 1s base, 30s ceiling.
- `ServiceQuotaExceededException` (400): only for `StartEngagementFromOpportunityTask` and `SubmitOpportunity`. Not in our `_is_retryable` list — should be (with longer backoff: at least 5 minutes between attempts because these are 24-hour quotas).

---

## 8. Identifier patterns (consolidated)

Our `validators.py` uses very loose `[A-Za-z0-9_-]+` patterns. The canonical patterns are:

| Resource | boto3 pattern |
|---|---|
| Opportunity | `O[0-9]{1,19}` |
| Engagement | `eng-[0-9a-z]{14}` |
| Engagement Invitation | `engi-[0-9,a-z]{13}` (note literal comma in char class) |
| Resource Snapshot Job | `job-[0-9a-z]{13}` |
| Task (StartEngagement) | `.*task-[0-9a-z]{13}` |
| Solution | `S-[0-9]{1,19}` |
| AWS Marketplace Offer | `arn:aws:aws-marketplace:[a-z]{1,2}-[a-z]*-\d+:\d{12}:AWSMarketplace/Offer/.*` |
| AWS Marketplace OfferSet | `arn:aws:aws-marketplace:[a-z]{1,2}-[a-z]*-\d+:\d{12}:AWSMarketplace/OfferSet/offerset-.*` |
| Phone (Contact) | `\+[1-9]\d{1,14}` (E.164) |
| Email (Contact) | lowercase + 80-char total |
| DUNS | `[0-9]{9}` |
| AWS Account Id | `([0-9]{12}|\w{1,12})` (12-digit number OR alphanumeric alias) |

**MUST FIX:** `validators.py` `is_valid_aws_opportunity_id` accepts way more than `O[0-9]{1,19}`. Tighten to the exact pattern. Add specific validators for engagement, invitation, task, snapshot-job, and solution ids so webhook events with bogus values fail loudly.

---

## 9. Drift summary table

| Topic | Our impl | Canonical | Action |
|---|---|---|---|
| `ExpectedCustomerSpend.Frequency` | hard-coded `"Monthly"` (correct) | enum `["Monthly"]` only | Update old reference doc; keep code |
| `ReviewStatus` casing | not used directly | `In review` lowercase | Document; align future event handlers |
| `Customer.Account.Industry` | passes `govwin_industry` through | strict 28-value enum | Add normalization map; fall back to `Other` + `OtherIndustry` |
| `Address.StateOrRegion` | always normalized to a US state | enum only when `CountryCode == "US"` | Conditional; do not force US normalization on non-US |
| `UpdateOpportunity` semantics | `scrub_for_update` whitelists | PUT semantics: omit = null | Update Lambda must merge from `GetOpportunity`, not from cached deltas |
| Lock-after-submit | not pre-flighted | UpdateOpp fails when ReviewStatus != Pending Submission/Action Required | Pre-flight in update Lambda; surface to HubSpot |
| Identifier validators | `[A-Za-z0-9_-]+` for all | distinct strict patterns per resource | Tighten validators |
| `participantType` casing | event vs API filter | event = `Sender`/`Receiver`; filter = `SENDER`/`RECEIVER` | Don't conflate |
| `TaskId` regex | doc says `oit-...` | boto3 says `task-...` | Trust boto3 |
| IAM for StartEngagementFromOpportunityTask | not yet audited | needs 7 underlying actions | Audit `terraform/modules/ace/iam.tf` |
| `ConflictException` on AssociateOpp | DLQ | should be soft-success | Catch and treat as already-associated |
| `ServiceQuotaExceededException` | not retryable in our config | retryable with long backoff (5+ min) | Add to `_is_retryable` for write ops |
| `PartnerOpportunityIdentifier` in GetOpp response | sometimes empty | doc says present | Don't rely; track in DynamoDB |
| `PrimaryNeedsFromAws` translation table | in code, undocumented | n/a | Ship the translation table in OSS reference docs |
| `CustomerUseCase` enum | inferred from validation errors | not in boto3 model; server-side gate | Document as inferred, refresh from sandbox |

---

## 10. Citations

- CreateOpportunity: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_CreateOpportunity.html`
- UpdateOpportunity: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_UpdateOpportunity.html`
- GetOpportunity: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_GetOpportunity.html`
- ListOpportunities: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_ListOpportunities.html`
- AssociateOpportunity: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_AssociateOpportunity.html`
- DisassociateOpportunity: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_DisassociateOpportunity.html`
- StartEngagementFromOpportunityTask: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_StartEngagementFromOpportunityTask.html`
- SubmitOpportunity: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_SubmitOpportunity.html`
- ListEngagementInvitations: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_ListEngagementInvitations.html`
- ListSolutions: `https://docs.aws.amazon.com/partner-central/latest/selling-api/API_ListSolutions.html`
- EventBridge events: `https://docs.aws.amazon.com/partner-central/latest/selling-api/selling-api-events.html`
- Quotas: `https://docs.aws.amazon.com/partner-central/latest/selling-api/quotas.html`

boto3 service model fields used:
- `c.meta.service_model.operation_model('CreateOpportunity').input_shape`
- ditto for UpdateOpportunity, GetOpportunity, AssociateOpportunity, DisassociateOpportunity, StartEngagementFromOpportunityTask, SubmitOpportunity, ListOpportunities, ListEngagementInvitations, ListSolutions, GetAwsOpportunitySummary
- shape recursion through `members`, `enum`, `metadata.pattern`, `metadata.min`, `metadata.max`
- boto3 1.43.0, service api version `2022-07-26`
