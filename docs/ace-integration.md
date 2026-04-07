# ACE Integration Guide

How to use synced GovWin deals with the SaaSify ACE Connector for AWS Partner Central co-selling.

## Overview

The GovWin-to-HubSpot integration automatically populates deals with most of the fields required for AWS ACE (APN Customer Engagements) submission. This guide explains the end-to-end workflow for taking a GovWin opportunity and submitting it to AWS Partner Central for co-selling with AWS field sellers.

## Prerequisites

- GovWin-to-HubSpot integration deployed and syncing (see [Deployment Guide](deployment-guide.md))
- SaaSify AWS ACE Connector installed from [AWS Marketplace](https://aws.amazon.com/marketplace)
- SaaSify connector configured and authenticated with your HubSpot account

## End-to-End Workflow

### 1. Opportunity Syncs from GovWin

The integration automatically syncs opportunities on schedule. When a new or updated opportunity is found in GovWin:

- A **Deal** is created/updated in HubSpot with 25+ properties
- The associated **Company** (government agency) is created/updated
- **Contacts** (agency personnel) are created/updated
- **Associations** are created between deals, companies, and contacts

### 2. Review the Deal in HubSpot

Open the deal in HubSpot. The following ACE-relevant fields are already populated:

| Field | Source | Example |
|---|---|---|
| Deal Name (Project Title) | GovWin `title` | "Cloud Migration Services for DoD" |
| Amount (Expected Revenue) | GovWin `oppValue` x 1000 | $5,000,000 |
| Close Date (Target Close) | GovWin `pAwardDateTo` | 2026-09-30 |
| Company (Customer) | GovWin `govEntity` | Department of Defense |
| Industry | NAICS mapped to AWS | Government |
| Country | GovWin `country` | USA |
| Description | GovWin `description` | Full opportunity description |
| Stage | GovWin `status` mapped | RFP Released |
| Opportunity Type | Default | Net New Business |

### 3. Fill Manual ACE Fields

Before submitting to AWS Partner Central, fill these 3 fields in HubSpot:

#### Delivery Model
How the solution will be delivered. Options:
- SaaS or PaaS
- BYOL or AMI
- Managed Services
- Professional Services
- Resell
- Other

#### Solution Offered
The specific AWS solution or product. Must match a solution registered in your AWS Partner Central account. Examples:
- "AWS GovCloud Migration"
- "Managed Cloud Operations"
- Your specific registered solution name

#### Partner Primary Need from AWS
What support you need from AWS. Options:
- Architectural Validation
- Business Presentation
- Competitive Intelligence
- Pricing Assistance
- Technical Consultation
- Total Cost of Ownership Evaluation
- Deal Support
- Support for Public Tender

### 4. Submit via SaaSify ACE Connector

1. Ensure the deal stage is "Qualified" or higher (RFP Released, Proposal Submitted, etc.)
2. Click the SaaSify ACE submission action in HubSpot
3. SaaSify validates all required fields
4. Deal is submitted to AWS Partner Central

### 5. AWS Validation

After submission:
- AWS reviews the opportunity (typically 1-3 business days)
- Status updates sync back to HubSpot via SaaSify
- If **Action Required**: AWS provides feedback; make corrections and resubmit
- If **Approved**: opportunity is active in AWS ACE Pipeline Manager

### 6. Co-Selling

Once approved:
- AWS field sellers can see and engage on the opportunity
- Updates in either direction sync automatically via SaaSify
- Progress through stages: Qualified -> Technical Validation -> Business Validation -> Committed -> Launched

## Field Mapping: GovWin -> HubSpot -> ACE

| ACE Field | HubSpot Property | GovWin Source | Notes |
|---|---|---|---|
| partnerProjectTitle | `dealname` | `title` | Auto |
| expectedMonthlyAwsRevenue | `amount` | `oppValue` x 1000 | Auto |
| targetCloseDate | `closedate` | `pAwardDateTo` | Auto |
| customerCompanyName | Company `name` | `govEntity.title` | Auto (via association) |
| industry | `govwin_industry` | NAICS mapping | Auto (mapped) |
| country | `govwin_country` | `country` | Auto |
| projectDescription | `description` | `description` | Auto (sanitized) |
| opportunityType | `govwin_ace_opportunity_type` | Default value | Auto |
| stage | `dealstage` | `status` mapping | Auto |
| deliveryModel | `govwin_ace_delivery_model` | -- | **Manual** |
| solutionOffered | `govwin_ace_solution` | -- | **Manual** |
| partnerPrimaryNeedFromAws | `govwin_ace_partner_need` | -- | **Manual** |

## Tips

- **Batch review**: After a sync, filter HubSpot deals by `govwin_update_date` to find newly synced/updated deals
- **Stage mapping**: The GovWin pipeline stages are designed to align with ACE stages. "Pre-RFP" maps to "Prospect" in ACE, while "RFP Released" and beyond meet the "Qualified" minimum for ACE submission
- **Revenue estimate**: GovWin `oppValue` is the total contract value. For ACE, this maps to expected monthly AWS revenue. You may want to adjust the amount for the AWS-specific portion
- **Duplicate prevention**: The integration uses `govwin_opp_id` as a unique key. If you manually create deals for the same opportunity, avoid duplicate ACE submissions
