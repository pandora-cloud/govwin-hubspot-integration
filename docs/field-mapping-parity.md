# Field-mapping parity: GovWin → HubSpot → AWS Partner Central

End-to-end accounting of every field that flows through the pipeline, plus what SaaSify maps as their default for the HubSpot → ACE leg. SaaSify column populated from their admin UI screenshots (2026-04-30); diff against ours drives the action list below.

## Architectural insight from SaaSify

SaaSify reads customer data from the deal's **associated HubSpot Company** (`(Company).Field`), customer contact data from the **associated Contact** (`(Contact).Field`), and partner contact data from the **HubSpot deal Owner** (`(Owner).Field`). That's a different, better architecture than ours: we currently read everything from deal properties.

We sync GovWin→HubSpot in three flavors today:
- Opportunity → Deal
- GovEntity → Company (associated to Deal)
- GovWin Contact → HubSpot Contact (associated to Deal and Company)

So the underlying associations exist. The ACE mapper just doesn't read from them. Closing this gap means: read `Customer.Account.*` from the associated Company, read `Customer.Contacts[]` from the associated Contacts, and use the deal Owner for `PartnerOpportunityTeam` (the partner-side contact AWS attributes the engagement to).

## Customer Details — 10 fields

All `CRM Lookup` reading from the associated **Company** record. Asterisk = SaaSify-required.

| AWS field | SaaSify maps from | Ours today | Gap |
|---|---|---|---|
| Customer Company Name * | `(Company).Company name` | `govwin_agency` deal property | **architecture**: should read from associated Company |
| Industry Vertical * | `(Company).Industry` | `govwin_industry` deal property | **architecture** |
| Industry Other * | `(No Default)` | derived: when our Industry isn't in AWS enum, set Industry=Other and OtherIndustry=value | OK; SaaSify left blank (their logic likely matches) |
| Customer Website * | `(Company).Website URL` | synthesized `https://www.<agency>.gov` | **fix**: read Company.website; only synthesize on miss |
| Customer Address | `(Company).Street Address` | **not mapped** | **➕ add `Customer.Account.Address.AddressLine1`** |
| Customer City | `(Company).City` | **not mapped** | **➕ add `Customer.Account.Address.City`** |
| Customer State * | `(Company).State/Region` | constant `Dist. of Columbia` | **fix**: read Company.state |
| Customer Country * | `(Company).Country/Region` | constant `US` | **fix**: read Company.country |
| Postal Code * | `(Company).Postal Code` | constant `20001` | **fix**: read Company.zip |
| Customer DUNS | `(No Default)` | **not mapped** | optional; HubSpot has no standard DUNS field — would need a custom property |

## Customer Contact Details — 5 fields

`CRM Lookup` from the associated **Contact** record. This entire section maps to AWS's `Customer.Contacts[]` array — **we don't populate it at all today**.

| AWS field | SaaSify maps from | Ours today |
|---|---|---|
| Customer First Name | `(Contact).First Name` | not mapped |
| Customer Last Name | `(Contact).Last Name` | not mapped |
| Customer Email | `(Contact).Email` | not mapped |
| Customer Title | `(No Default)` | not mapped |
| Customer Phone | `(Contact).Phone Number` | not mapped |

**➕ add `Customer.Contacts[]`** — single highest-value gap. AWS reviewers use this to qualify the opp. We already sync GovWin contacts as HubSpot contacts associated to the deal; the data is there.

## Opportunity Details — 17 fields

Mix of `CRM Lookup` (read from deal), `Static` (constant value), and `Expression` (computed).

| AWS field | SaaSify | Ours today | Gap |
|---|---|---|---|
| Stage | CRM Lookup `(Deal).Deal Stage` (Auto Sync) | constant `Pending Submission` | We treat Stage as server-managed; SaaSify writes Deal Stage back. Acceptable difference. |
| Partner Project Title * | `(Deal).Deal Name` | `dealname` ✓ | match |
| Customer Business Problem * | `(No Default)` | `description` | **we're better — they leave blank, we fill from `description`** |
| Estimated AWS Monthly Recurring Revenue * | **Expression** `(Deal).Amount * 0.083` | `amount` passed raw with `Frequency=Monthly` | **🔴 BUG**: we send total deal amount as monthly. AWS sees 12x reality. SaaSify divides by 12 (× 0.083). Need to fix. |
| Target Close Date * | `(Deal).Close Date` (Auto Sync) | `closedate` ✓ | match (with our null→today+180d fallback) |
| Primary Need from AWS * | `(No Default)` | `govwin_ace_partner_need` first value | OK |
| Specific needs from AWS for Co-sell * | `(No Default)` | `govwin_ace_partner_need` (full multi-select) | OK; SaaSify users fill manually |
| Use Case * | `(No Default)` | `govwin_ace_use_case` | match (we have a default; they require manual) |
| Delivery Model * | Static `SaaS or PaaS` | `govwin_ace_delivery_model` | match (deal-driven is better) |
| Next Step | `(No Default)` (Auto Sync) | not mapped | **➕ add** `LifeCycle.NextSteps`. Likely seed from `description` or BD edit. |
| Opportunity Type * | Static `Net New Business` | `govwin_ace_opportunity_type` | match |
| Parent Opportunity Id | `(No Default)` | not mapped | **➕ add** `Project.RelatedOpportunityIdentifier` for renewals/expansions |
| Sales Activities * | Static `Initialized discussions with customer` | seeded same | match |
| Solution Offered * | `(No Default)` | `govwin_ace_solution_id` (associate) + `OtherSolutionDescription` (fallback) | OK |
| AWS Products | `(No Default)` | not mapped (we use it only as Sandbox-test fallback) | **➕ add** `AssociateOpportunity(RelatedEntityType=AwsProducts)` for production too — partners typically associate one or two AWS services |
| APN Program | `(No Default)` | not mapped | **➕ add** `Marketing.AwsFundingUsed` / `Marketing.UseCases` (APN Program isn't in the boto3 model directly; this likely lands on Marketing block) |
| Closed Reason | `(No Default)` | partial (we use `LifeCycle.ClosedLostReason` only on cleanup) | **➕ surface** `LifeCycle.ClosedLostReason` on the deal as a BD-editable property for human Closed Lost transitions |

## Marketing Details — 5 fields

Mostly defaults. AWS's `Marketing` block is optional but valuable for AWS attribution / co-marketing budget tracking.

| AWS field | SaaSify | Ours today |
|---|---|---|
| Is Opportunity From Marketing Activity * | Static `No` | not mapped → **➕ default to `No`, allow BD override** |
| Campaign Name | No Default | not mapped → **➕ optional BD field** |
| Marketing Activity Use Case | No Default | not mapped |
| Marketing Activity Channel | No Default | not mapped |
| Is Marketing Development Funded * | Static `No` | not mapped → **➕ default to `No`** |

These map to AWS's `Marketing.Source`, `Marketing.CampaignName`, `Marketing.UseCases`, `Marketing.Channel`, `Marketing.AwsFundingUsed`. Default the two `*` fields to `No`; expose the others as BD-editable HubSpot properties. **These four BD-editable fields plus the two defaults will close most of the Marketing-block gap.**

## Additional Details — 4 fields

All No Default in SaaSify (BD fills manually). AWS fields:

| AWS field | SaaSify | Ours |
|---|---|---|
| Competitive Tracking | No Default | not mapped → **➕ add** `Project.CompetitorName` |
| Competitive Tracking Other | No Default | not mapped → covered by CompetitorName=Other + free-text |
| Additional Comments | No Default | not mapped → **➕ add** `Project.AdditionalComments` |
| AWS Account ID | No Default | not mapped → **➕ add** customer's AWS Account ID for partners working with existing AWS customers |

## Partner Contact Details — 3 fields

`CRM Lookup` from the **Owner** of the HubSpot deal. **Critical: SaaSify uses the deal Owner, not an associated contact.** The deal Owner is who AWS attributes the engagement to from the partner side.

| AWS field | SaaSify maps from | Ours today |
|---|---|---|
| Primary Contact First Name | `(Owner).First Name` | not mapped |
| Primary Contact Last Name | `(Owner).Last Name` | not mapped |
| Primary Contact Email | `(Owner).Email` | not mapped |

**➕ add `OpportunityTeam[]` / `PrimaryContact`** populated from the HubSpot deal owner's HubSpot user record (HubSpot users have `firstName`, `lastName`, `email` accessible via the owners API).

## ACE Co-sell Owner — 1 field

| AWS field | SaaSify | Ours |
|---|---|---|
| ACE Co-sell Owner Email | No Default | not mapped → **➕ optional BD field**, used by AWS to route to the right AWS PDM |

## SaaS Documentation — 5 fields

For SaaS-listed solutions. **Skip until Pandora lists a SaaS solution in AWS Marketplace.** When that day comes, these would map to AWS's `SoftwareRevenue.*` block.

## AWS Co-sell Status — 3 fields (Write-Back)

This is **AWS → HubSpot** flow, not HubSpot → AWS. SaaSify writes these AWS-side values back into HubSpot deal properties whenever AWS updates the opp.

| AWS source | SaaSify writes to | We have |
|---|---|---|
| AWS Marketplace Engagement Score | (HubSpot deal property, write-back) | not implemented |
| AWS Co-sell Status | (HubSpot deal property, write-back) | partial — we update `dealstage` but don't expose the AWS string status separately |
| AWS Co-sell ID | (HubSpot deal property, write-back) | stored in DynamoDB only; not on the deal |

**➕ add three new HubSpot deal properties** (`govwin_aws_marketplace_engagement_score`, `govwin_aws_cosell_status`, `govwin_aws_cosell_id`) and have `handle_ace_event` populate them on every Opportunity Updated event.

## AWS Contacts Association — 2 entries

When AWS adds a contact to the engagement (e.g. assigns a PDM), SaaSify creates a HubSpot Contact with the label "Hyperscaler Contact" and associates it to both the Deal and the Company.

| HubSpot Object | SaaSify writes label | We have |
|---|---|---|
| Deal | "Hyperscaler Contact" association | not implemented |
| Company | "Hyperscaler Contact" association | not implemented |

**➕ extend `handle_ace_event` to create + associate HubSpot Contacts** when AWS includes contact records in the EngagementInvitation event detail.

---

## Action list (prioritized)

### 🔴 Bug fix (immediate)

1. **MRR calculation**: divide deal amount by 12 (or compute monthly equivalent) before sending as `ExpectedCustomerSpend.Amount` with `Frequency=Monthly`. Right now AWS sees 12× the real revenue. SaaSify uses `× 0.083` (≈ 1/12). One-line mapper fix.

### 🟢 High-value additions (close real BD gaps)

2. **Read Customer.Account.* from associated Company.** Replace the constants with reads from the deal's associated HubSpot company record (`address`, `city`, `state`, `zip`, `country`, `domain`/`website`). One extra HubSpot API call per submission; one mapper rewrite.
3. **Customer.Contacts[]**: forward the deal's associated contacts (which we already sync from GovWin) into AWS as the customer-side contacts. Highest-value missing field.
4. **PartnerOpportunityTeam from deal Owner**: read the HubSpot user record for the deal owner and forward as the partner-side primary contact.
5. **AWS write-back to three new HubSpot deal properties**: `aws_cosell_id`, `aws_cosell_status`, `aws_marketplace_engagement_score`. Update on every Opportunity Updated event.

### 🟡 BD-editable additions (smaller value, BD discretion)

6. **Marketing block** (`Marketing.Source`, `CampaignName`, `UseCases`, `Channel`, `AwsFundingUsed`). Two defaults to `No`; three BD-editable HubSpot properties.
7. **Additional Details** (`Project.CompetitorName`, `Project.AdditionalComments`, customer's `AwsAccountId`). All BD-editable.
8. **Next Steps + RelatedOpportunityIdentifier** as BD-editable fields.
9. **AWS Products association** — promote from Sandbox-only fallback to a BD-editable HubSpot multi-select that lists AWS services the deal involves. AssociateOpportunity then runs once per selected product.
10. **Hyperscaler Contact** — when EngagementInvitation events return AWS-side contacts, create the HubSpot contact + association.

### 🔵 Defer

11. **SaaS Documentation block** — only relevant if Pandora lists a SaaS solution in AWS Marketplace. Skip until needed.
12. **Customer DUNS** — federal customers don't have one (UEI superseded DUNS in 2022); not worth a custom HubSpot property until a commercial customer needs it.

---

## End-state mapper architecture

After actions 1-10, the mapper looks roughly like:

```
deal = hubspot.get_deal(id, deal_properties...)
company = hubspot.get_associated_company(deal_id)        # NEW
contacts = hubspot.get_associated_contacts(deal_id)       # NEW
owner = hubspot.get_owner(deal.owner_id)                  # NEW

payload = {
    Catalog, ClientToken, Origin, OpportunityType, PrimaryNeedsFromAws,
    PartnerOpportunityIdentifier,
    Customer = {
        Account = {
            CompanyName: company.name,
            Industry: industry, OtherIndustry: other_industry,
            WebsiteUrl: company.website or company.domain,
            Address: { AddressLine1, City, StateOrRegion, PostalCode, CountryCode } ← all from company
        },
        Contacts: [ {FirstName, LastName, Email, Title, Phone} for each contact ]   # NEW
    },
    Project = {
        Title, CustomerBusinessProblem, CustomerUseCase, DeliveryModels,
        OtherSolutionDescription, SalesActivities, AdditionalComments,        # AdditionalComments NEW
        CompetitorName, RelatedOpportunityIdentifier,                          # NEW
        ExpectedCustomerSpend = [{Amount: deal.amount / 12, Frequency: 'Monthly', ...}]  # FIXED
    },
    Marketing = {                                                              # NEW
        Source: 'Marketing Activity' or 'None', CampaignName,
        Channel, UseCases, AwsFundingUsed
    },
    LifeCycle = {ReviewStatus, TargetCloseDate, NextSteps, ClosedLostReason},  # NextSteps + ClosedLostReason
    OpportunityTeam = [{                                                       # NEW
        FirstName: owner.firstName, LastName: owner.lastName, Email: owner.email,
        BusinessTitle: 'Partner', Role: 'BusinessOwner'
    }]
}
```

Plus on the `handle_ace_event` side:

```
on Opportunity Updated:
    update HubSpot deal:
        dealstage (existing)
        govwin_aws_cosell_id = aws_opp.Id                          # NEW
        govwin_aws_cosell_status = aws_opp.LifeCycle.ReviewStatus  # NEW
        govwin_aws_marketplace_engagement_score = ... (when AWS publishes it)  # NEW

on Engagement Invitation Created/Accepted:
    if invitation includes AWS contacts:
        for each contact:
            create or upsert HubSpot Contact with label 'Hyperscaler Contact'
            associate to Deal
            associate to Company
```

That gives us full SaaSify parity except where we deliberately skip (SaaS docs, DUNS).

## What I recommend doing next

The MRR bug (#1) and the Customer.Account.* architecture fix (#2) are the most impactful. Customer.Contacts[] (#3) is the highest single field-level value.

I'd land all 10 actionable items in one PR rather than piecemeal; they share new HubSpot client methods (`get_associated_company`, `get_associated_contacts`, `get_owner`) and the unit-test surface is similar. Estimated effort: 4-6 hours of code, 30 unit tests, one redeployment. End-to-end verification on a real opp to confirm AWS accepts the wider payload.

Say "go" and I'll do it.
