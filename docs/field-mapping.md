# Field Mapping Reference

Complete mapping of GovWin IQ fields to HubSpot CRM properties, including ACE-ready fields for AWS Partner Central submission.

## Custom Property Group

All GovWin-specific properties are created under the `govwin` property group in HubSpot with the `govwin_` prefix.

## GovWin Opportunities -> HubSpot Deals

### Built-in HubSpot Properties

| GovWin Field | HubSpot Property | Type | Transform |
|---|---|---|---|
| `title` | `dealname` | string | Direct |
| `oppValue` | `amount` | number | Multiply by 1,000 (GovWin stores in thousands) |
| `description` | `description` | string | Strip HTML tags, truncate to 65,536 chars |
| `pAwardDateTo` or `responseDate` | `closedate` | date | ISO-8601 to HubSpot timestamp |

### Custom GovWin Properties (Deal)

| GovWin Field | HubSpot Property | Type | Description |
|---|---|---|---|
| `id` | `govwin_opp_id` | string | Global opportunity ID (e.g., OPP12345). **Dedup key.** |
| `iqOppId` | `govwin_iq_opp_id` | string | Internal numeric GovWin ID |
| `type` | `govwin_opp_type` | enumeration | trackedopp, toon, bid, fbo, opn, top |
| `status` | `govwin_status` | string | Raw GovWin status value |
| `solicitationDate.value` | `govwin_solicitation_date` | date | Solicitation release date |
| `solicitationNumber` | `govwin_solicitation_number` | string | Solicitation number |
| `sourceURL` | `govwin_source_url` | string | Link to government procurement page |
| `links.webHref.href` | `govwin_iq_url` | string | Direct link to GovWin IQ page |
| `duration` | `govwin_duration` | string | Contract duration text |
| `primaryNAICS.title` | `govwin_primary_naics` | string | Primary NAICS title |
| `primaryNAICS.id` | `govwin_naics_code` | string | Primary NAICS code |
| `primaryRequirement` | `govwin_primary_requirement` | string | Main procurement objective |
| `procurement` | `govwin_analyst_notes` | textarea | GovWin analyst updates |
| `competitionTypes[0].title` | `govwin_competition_type` | string | Competition type |
| `contractTypes[0].title` | `govwin_contract_type` | string | Contract type |
| `typeOfAward` | `govwin_type_of_award` | string | Type of award |
| `country` | `govwin_country` | string | USA or CAN |
| `createdDate` | `govwin_created_date` | datetime | When opportunity was created in GovWin |
| `updateDate` | `govwin_update_date` | datetime | Last update in GovWin (used for change detection) |
| `cmmcRequirements` | `govwin_cmmc_requirements` | string | CMMC certification level required |
| `smartTag` (concatenated) | `govwin_smart_tags` | string | Smart-tagged categories |
| `govEntity.title` | `govwin_agency` | string | Buying organization name |
| `priority` | `govwin_priority` | number | Bookmarked priority (1-5) |
| `market` | `govwin_market` | enumeration | Federal or SLED |

### ACE-Ready Properties (Deal)

These properties support downstream submission to AWS Partner Central via the SaaSify ACE Connector.

| ACE Mandatory Field | HubSpot Property | Source | Auto-populated? |
|---|---|---|---|
| Customer Company Name | Associated Company `name` | `govEntity.title` | Yes |
| Industry Vertical | `govwin_industry` | NAICS code mapped to AWS industry | Yes |
| Country | `govwin_country` | `country` | Yes |
| Target Close Date | `closedate` | `pAwardDateTo` or `responseDate` | Yes |
| Project Title | `dealname` | `title` | Yes |
| Project Description | `description` | `description` (sanitized) | Yes |
| Opportunity Type | `govwin_ace_opportunity_type` | Default: "Net New Business" | Yes |
| Expected AWS Monthly Revenue | `amount` | `oppValue` x 1000 | Yes |
| Stage | `dealstage` | Mapped from `status` | Yes |
| Delivery Model | `govwin_ace_delivery_model` | -- | **Manual** |
| Solution Offered | `govwin_ace_solution` | -- | **Manual** |
| Partner Primary Need | `govwin_ace_partner_need` | -- | **Manual** |

### NAICS to AWS Industry Mapping

| NAICS Prefix | NAICS Sector | AWS ACE Industry |
|---|---|---|
| 11 | Agriculture, Forestry, Fishing | Agriculture |
| 21 | Mining, Oil & Gas | Energy |
| 22 | Utilities | Energy |
| 23 | Construction | Other |
| 31-33 | Manufacturing | Manufacturing |
| 42 | Wholesale Trade | Distribution |
| 44-45 | Retail Trade | Consumer Goods |
| 48-49 | Transportation & Warehousing | Transportation |
| 51 | Information | Software & Internet |
| 52 | Finance & Insurance | Financial Services |
| 53 | Real Estate | Other |
| 54 | Professional, Scientific & Technical | Professional Services |
| 55 | Management of Companies | Professional Services |
| 56 | Administrative & Support | Professional Services |
| 61 | Educational Services | Education |
| 62 | Health Care & Social Assistance | Healthcare |
| 71 | Arts, Entertainment & Recreation | Media & Entertainment |
| 72 | Accommodation & Food Services | Travel & Hospitality |
| 81 | Other Services | Other |
| 92 | Public Administration | Government |

### Deal Pipeline Stages

A custom pipeline "GovWin Pipeline" is created with these stages:

| GovWin Status | HubSpot Stage ID | Stage Label | Probability |
|---|---|---|---|
| Pre-RFP | `govwin_pre_rfp` | Pre-RFP | 10% |
| RFP Released | `govwin_rfp_released` | RFP Released | 20% |
| Proposal Submitted | `govwin_proposal_submitted` | Proposal Submitted | 40% |
| Under Evaluation | `govwin_under_evaluation` | Under Evaluation | 50% |
| Awarded | `closedwon` | Awarded (Won) | 100% |
| Cancelled | `closedlost` | Cancelled (Lost) | 0% |
| Other | `govwin_other` | Other | 20% |

## GovWin GovEntities -> HubSpot Companies

| GovWin Field | HubSpot Property | Type | Notes |
|---|---|---|---|
| `title` | `name` (built-in) | string | Agency name |
| `id` | `govwin_gov_entity_id` | string | **Dedup key** |
| `parentHierarchy[0].title` | `govwin_parent_agency` | string | Parent department |
| `links.webHref` | `govwin_entity_url` | string | GovWin entity page |
| `type` | `govwin_entity_type` | enumeration | federal, state_local |
| -- | `industry` (built-in) | string | Set to "Government" |

## GovWin Contacts -> HubSpot Contacts

| GovWin Field | HubSpot Property | Type | Notes |
|---|---|---|---|
| `firstName` | `firstname` (built-in) | string | |
| `lastName` | `lastname` (built-in) | string | |
| `email` | `email` (built-in) | string | **Primary dedup key** |
| `phone` | `phone` (built-in) | string | |
| `title` | `jobtitle` (built-in) | string | |
| `contactId` | `govwin_contact_id` | string | Fallback dedup key |
| `govEntityLevel1` | `govwin_entity_level1` | string | Top-level agency |
| `govEntityLevel2` | `govwin_entity_level2` | string | Sub-agency |
| `address1` | `address` (built-in) | string | |
| `city` | `city` (built-in) | string | |
| `state` | `state` (built-in) | string | |
| `zip` | `zip` (built-in) | string | |

## Associations

| From | To | Association Type | Trigger |
|---|---|---|---|
| Deal | Company | `deal_to_company` | Opportunity's `govEntity` |
| Deal | Contact | `deal_to_contact` | Opportunity's contacts |
| Company | Contact | `company_to_contact` | Contact's `govEntityLevel1` match |
