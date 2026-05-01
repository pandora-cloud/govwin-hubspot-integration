# Roadmap

A living view of where this project is going. The headline priority for the next release is making AWS Partner Central submission less manual: today the BD team has to remember which three fields are required, click through the deal sidebar to find them, and toggle a stage to fire submission. v2.2 turns that into a one-click experience inside HubSpot.

This roadmap is a maintainer commitment, not a contract. We adjust based on real-deployment feedback. If something on this list matters to you and you want to accelerate it, contributions are welcome (see [CONTRIBUTING.md](CONTRIBUTING.md)) and paid prioritization is available (see [SUPPORT.md](SUPPORT.md)).

## Now (v2.x maintenance)

Continuous, no scheduled cut:

- New NAICS codes added to the industry mapping table as Census/BLS rotations land.
- ACE field-mapping refinements as AWS adds new optional fields to `CreateOpportunity` / `UpdateOpportunity`.
- Bug fixes from production reports across the federal AWS partner community.
- Documentation polish from real-deployment feedback.
- Renovate / Dependabot keeps Python and Terraform dependencies current; security patches auto-merge.

## Next (v2.2 - "make AWS submission less manual")

The single anchor feature for the next release. Three sub-features, each shippable independently if the larger card requires more design iteration.

### v2.2.1: HubSpot CRM card on the deal sidebar (anchor)

A HubSpot UI Extension (CRM card) that renders inside the deal sidebar and:

- Shows the three ACE-required fields (`govwin_ace_partner_need`, `govwin_ace_delivery_model`, `govwin_ace_use_case`) with real-time validation against the published AWS enums (so BD can't pick a value AWS will reject).
- Surfaces the deal's current ACE submission state (`pending`, `submitted`, `approved`, `rejected`, `closed_won`, `closed_lost`) read from DynamoDB via API Gateway, with a link to the AWS Partner Central UI for the corresponding opportunity once submitted.
- Provides a one-click "Submit to AWS" button that calls the API Gateway directly, bypassing the dealstage-transition trigger entirely. The button enables only when all three required fields are populated and shows the validation errors inline if not.
- Lives in the same `hubspot-app/` developer-platform project as the existing webhook subscriptions; no new HubSpot artifact for the deployer to manage.

The technical design is straightforward: HubSpot provides `crm-card.json` + a React component file + `hubspot.fetch` to call our API Gateway. The new API Gateway routes (`GET /deal/{id}/ace-status`, `POST /deal/{id}/submit-to-ace`) reuse the existing webhook receiver Lambda's authentication patterns.

### v2.2.2: Auto-fill of the manual fields where possible

Several of the "manual" fields can be derived from data the integration already has:

- `govwin_ace_use_case` can default from the deal's primary NAICS code via a NAICS -> AWS-customer-use-case lookup table.
- `govwin_ace_delivery_model` can default from the GovWin product hierarchy (`type_of_product`, `contract_type`).
- `govwin_ace_partner_need` is harder to derive automatically and remains BD-driven, but the card will show inline AWS guidance.

When the integration auto-fills a field, the BD user sees a "Verified by GovWin" badge on the field and can override; the override is sticky (won't be reset on re-sync).

### v2.2.3: Rich progress indicator on the deal

Today the deal moves through HubSpot pipeline stages but BD has no visibility into the AWS-side progression of the engagement (Pending Submission -> In Review -> Action Required -> Approved / Rejected). The CRM card surfaces this from the EventBridge events the project already consumes; users see a live timeline.

## Future (v3.x and beyond)

Larger commitments that depend on external blockers or significant scope:

- **GovCloud (us-gov-west-1) support.** Blocked on AWS exposing the `partnercentral-selling` API in GovCloud; today the API exists only in the commercial us-east-1 region. We will ship FedRAMP-Moderate-aligned operating instructions as soon as AWS makes this possible.
- **Bidirectional ACE field sync.** Today we mirror state changes (stage, review status) back to HubSpot but not all editable fields. v3 expands this so an AWS PDM editing the opportunity in Partner Central propagates back to the HubSpot deal.
- **GovWin -> AWS Partner Central direct path (opt-in).** A separate code path that bypasses HubSpot for partners who use HubSpot only as a system of record, not as a BD review surface.

## Won't do

We will not accept PRs in these directions; forks are welcome:

- **Adapters for other CRMs**: Salesforce, Pipedrive, Microsoft Dynamics, Zoho, monday.com, etc. The project's identity is the GovWin -> HubSpot -> AWS Partner Central triad; staying focused on that is what makes the project useful for federal AWS partners.
- **Adapters for non-federal CRMs or commercial-only ACE flows.** Out of audience scope.
- **Ports to other languages.** Python 3.12 is the runtime. The dependency surface is small enough that single-language maintenance keeps the project sustainable.
- **A hosted SaaS version.** This project ships as code you deploy in your own AWS account. We won't operate a multi-tenant version.
- **Breaking the open-source license.** Apache-2.0, full stop.

## How to influence the roadmap

- Open a feature request issue using the template; describe the federal AWS partner workflow your request addresses.
- For larger commitments, start a Discussion thread first - the maintainer cost of a roadmap entry is real, and discussions surface alternative approaches early.
- Paid prioritization is available; contact <pc@pandoracloud.net>.
