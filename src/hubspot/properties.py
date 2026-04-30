"""HubSpot custom property and pipeline definitions for GovWin integration."""

from __future__ import annotations

from src.models import HubSpotProperty

# ---------------------------------------------------------------------------
# Property Group
# ---------------------------------------------------------------------------

PROPERTY_GROUP = {
    "name": "govwin",
    "label": "GovWin IQ",
    "displayOrder": 1,
}

# ---------------------------------------------------------------------------
# Deal Custom Properties
# ---------------------------------------------------------------------------

DEAL_PROPERTIES: list[HubSpotProperty] = [
    HubSpotProperty(
        name="govwin_id",
        label="GovWin ID",
        type="string",
        fieldType="text",
        hasUniqueValue=True,
        description="Unique GovWin opportunity ID used for deduplication",
    ),
    HubSpotProperty(
        name="govwin_opp_id",
        label="GovWin Opportunity ID",
        type="string",
        fieldType="text",
        description="Global opportunity ID from GovWin IQ (e.g., OPP12345)",
    ),
    HubSpotProperty(
        name="govwin_iq_opp_id",
        label="GovWin IQ Internal ID",
        type="string",
        fieldType="text",
        description="Internal numeric GovWin ID",
    ),
    HubSpotProperty(
        name="govwin_opp_type",
        label="GovWin Opportunity Type",
        type="enumeration",
        fieldType="select",
        description="Type of GovWin opportunity",
        options=[
            {"label": "Tracked Opportunity", "value": "trackedopp"},
            {"label": "Task Order (TOON)", "value": "toon"},
            {"label": "Bid/Lead", "value": "bid"},
            {"label": "SAM Notice", "value": "fbo"},
            {"label": "Other Procurement", "value": "opn"},
            {"label": "Opportunity Manager", "value": "top"},
        ],
    ),
    HubSpotProperty(
        name="govwin_status",
        label="GovWin Status",
        type="string",
        fieldType="text",
        description="Raw opportunity status from GovWin",
    ),
    HubSpotProperty(
        name="govwin_solicitation_date",
        label="Solicitation Date",
        type="date",
        fieldType="date",
        description="Date the solicitation was released",
    ),
    HubSpotProperty(
        name="govwin_solicitation_number",
        label="Solicitation Number",
        type="string",
        fieldType="text",
        description="Government solicitation number",
    ),
    HubSpotProperty(
        name="govwin_source_url",
        label="Source URL",
        type="string",
        fieldType="text",
        description="Link to the government procurement page",
    ),
    HubSpotProperty(
        name="govwin_iq_url",
        label="GovWin IQ URL",
        type="string",
        fieldType="text",
        description="Direct link to this opportunity in GovWin IQ",
    ),
    HubSpotProperty(
        name="govwin_duration",
        label="Contract Duration",
        type="string",
        fieldType="text",
        description="Expected contract duration",
    ),
    HubSpotProperty(
        name="govwin_primary_naics",
        label="Primary NAICS",
        type="string",
        fieldType="text",
        description="Primary NAICS classification title",
    ),
    HubSpotProperty(
        name="govwin_naics_code",
        label="NAICS Code",
        type="string",
        fieldType="text",
        description="Primary NAICS classification code",
    ),
    HubSpotProperty(
        name="govwin_primary_requirement",
        label="Primary Requirement",
        type="string",
        fieldType="text",
        description="Main procurement requirement",
    ),
    HubSpotProperty(
        name="govwin_analyst_notes",
        label="Analyst Notes",
        type="string",
        fieldType="textarea",
        description="GovWin analyst procurement notes and updates",
    ),
    HubSpotProperty(
        name="govwin_competition_type",
        label="Competition Type",
        type="string",
        fieldType="text",
        description="Type of competition (Full & Open, Set-Aside, etc.)",
    ),
    HubSpotProperty(
        name="govwin_contract_type",
        label="Contract Type",
        type="string",
        fieldType="text",
        description="Contract type (FFP, T&M, CPFF, etc.)",
    ),
    HubSpotProperty(
        name="govwin_type_of_award",
        label="Type of Award",
        type="string",
        fieldType="text",
        description="Award type classification",
    ),
    HubSpotProperty(
        name="govwin_country",
        label="Country",
        type="string",
        fieldType="text",
        description="Country (USA or CAN)",
    ),
    HubSpotProperty(
        name="govwin_created_date",
        label="GovWin Created Date",
        type="datetime",
        fieldType="date",
        description="When this opportunity was created in GovWin IQ",
    ),
    HubSpotProperty(
        name="govwin_update_date",
        label="GovWin Update Date",
        type="datetime",
        fieldType="date",
        description="When this opportunity was last updated in GovWin IQ",
    ),
    HubSpotProperty(
        name="govwin_cmmc_requirements",
        label="CMMC Requirements",
        type="string",
        fieldType="text",
        description="Cybersecurity Maturity Model Certification requirements",
    ),
    HubSpotProperty(
        name="govwin_smart_tags",
        label="Smart Tags",
        type="string",
        fieldType="text",
        description="GovWin smart-tagged categories",
    ),
    HubSpotProperty(
        name="govwin_agency",
        label="Government Agency",
        type="string",
        fieldType="text",
        description="Buying government agency name",
    ),
    HubSpotProperty(
        name="govwin_priority",
        label="GovWin Priority",
        type="number",
        fieldType="number",
        description="Bookmarked priority (1-5)",
    ),
    HubSpotProperty(
        name="govwin_market",
        label="Market",
        type="enumeration",
        fieldType="select",
        description="Federal or State/Local/Education",
        options=[
            {"label": "Federal", "value": "Federal"},
            {"label": "State/Local/Education", "value": "SLED"},
        ],
    ),
    # ACE-ready properties
    HubSpotProperty(
        name="govwin_industry",
        label="Industry (ACE)",
        type="string",
        fieldType="text",
        description="AWS ACE industry classification derived from NAICS code",
    ),
    HubSpotProperty(
        name="govwin_ace_opportunity_type",
        label="ACE Opportunity Type",
        type="enumeration",
        fieldType="select",
        description="AWS ACE opportunity type for Partner Central submission",
        options=[
            {"label": "Net New Business", "value": "Net New Business"},
            {"label": "Expansion", "value": "Expansion"},
            {"label": "Flat Renewal", "value": "Flat Renewal"},
        ],
    ),
    HubSpotProperty(
        name="govwin_ace_delivery_model",
        label="ACE Delivery Model",
        type="enumeration",
        fieldType="select",
        description="How the solution is delivered (manual entry for ACE submission)",
        options=[
            {"label": "SaaS or PaaS", "value": "SaaS or PaaS"},
            {"label": "BYOL or AMI", "value": "BYOL or AMI"},
            {"label": "Managed Services", "value": "Managed Services"},
            {"label": "Professional Services", "value": "Professional Services"},
            {"label": "Resell", "value": "Resell"},
            {"label": "Other", "value": "Other"},
        ],
    ),
    HubSpotProperty(
        name="govwin_ace_solution",
        label="ACE Solution Offered",
        type="string",
        fieldType="text",
        description="AWS solution offered (manual entry for ACE submission)",
    ),
    HubSpotProperty(
        name="govwin_ace_partner_need",
        label="ACE Partner Need from AWS",
        type="enumeration",
        # AWS PrimaryNeedsFromAws is a List<String>, so the HubSpot property
        # uses checkbox (multi-select) with semicolon-joined values that the
        # mapper splits.
        fieldType="checkbox",
        description="Type(s) of AWS support needed (manual entry for ACE submission)",
        options=[
            {"label": "Architectural Validation", "value": "Architectural Validation"},
            {"label": "Business Presentation", "value": "Business Presentation"},
            {"label": "Competitive Intelligence", "value": "Competitive Intelligence"},
            {"label": "Pricing Assistance", "value": "Pricing Assistance"},
            {"label": "Technical Consultation", "value": "Technical Consultation"},
            {
                "label": "Total Cost of Ownership Evaluation",
                "value": "Total Cost of Ownership Evaluation",
            },
            {"label": "Deal Support", "value": "Deal Support"},
            {"label": "Support for Public Tender", "value": "Support for Public Tender"},
        ],
    ),
    HubSpotProperty(
        name="govwin_ace_use_case",
        label="ACE Customer Use Case",
        type="enumeration",
        fieldType="select",
        description=(
            "AWS-published Customer Use Case (manual override; defaults to "
            "Migration / Database Migration). See "
            "src/ace/mapper.py:ALLOWED_CUSTOMER_USE_CASES for the full list."
        ),
        options=[
            {"label": "Migration / Database Migration", "value": "Migration / Database Migration"},
            {"label": "Security & Compliance", "value": "Security & Compliance"},
            {"label": "Containers & Serverless", "value": "Containers & Serverless"},
            {
                "label": "AI Machine Learning and Analytics",
                "value": "AI Machine Learning and Analytics",
            },
            {
                "label": "Networking",
                "value": "Networking",
            },
            {
                "label": "Database",
                "value": "Database",
            },
            {
                "label": "Storage & Backup",
                "value": "Storage & Backup",
            },
            {
                "label": "Web development & DevOps",
                "value": "Web development & DevOps",
            },
            # Note: do NOT add an "Other" option. AWS treats CustomerUseCase
            # as a closed enum (no companion OtherCustomerUseCase free-text
            # field), so any value not listed in
            # src/ace/mapper.py:ALLOWED_CUSTOMER_USE_CASES would be rejected
            # at CreateOpportunity time. The mapper falls back to "Migration
            # / Database Migration" silently if the property is left blank.
        ],
    ),
    HubSpotProperty(
        name="govwin_ace_other_solution_description",
        label="ACE Other Solution Description",
        type="string",
        fieldType="textarea",
        description=(
            "Free-text description used in place of an associated AWS Solution "
            "(255 char max). Optional; the mapper auto-falls back to the deal "
            "title when this is blank."
        ),
    ),
]

# ---------------------------------------------------------------------------
# Company Custom Properties
# ---------------------------------------------------------------------------

COMPANY_PROPERTIES: list[HubSpotProperty] = [
    HubSpotProperty(
        name="govwin_entity_id",
        label="GovWin Entity ID (Key)",
        type="string",
        fieldType="text",
        hasUniqueValue=True,
        groupName="govwin",
        description="Unique GovWin entity ID used for deduplication",
    ),
    HubSpotProperty(
        name="govwin_gov_entity_id",
        label="GovWin Gov Entity ID",
        type="string",
        fieldType="text",
        groupName="govwin",
        description="GovWin government entity ID",
    ),
    HubSpotProperty(
        name="govwin_parent_agency",
        label="Parent Agency",
        type="string",
        fieldType="text",
        groupName="govwin",
        description="Parent department/agency name",
    ),
    HubSpotProperty(
        name="govwin_entity_url",
        label="GovWin Entity URL",
        type="string",
        fieldType="text",
        groupName="govwin",
        description="Link to entity in GovWin IQ",
    ),
    HubSpotProperty(
        name="govwin_entity_type",
        label="Entity Type",
        type="enumeration",
        fieldType="select",
        groupName="govwin",
        description="Federal or State/Local",
        options=[
            {"label": "Federal", "value": "federal"},
            {"label": "State/Local", "value": "state_local"},
        ],
    ),
]

# ---------------------------------------------------------------------------
# Contact Custom Properties
# ---------------------------------------------------------------------------

CONTACT_PROPERTIES: list[HubSpotProperty] = [
    HubSpotProperty(
        name="govwin_contact_id",
        label="GovWin Contact ID",
        type="string",
        fieldType="text",
        groupName="govwin",
        description="GovWin contact identifier",
    ),
    HubSpotProperty(
        name="govwin_entity_level1",
        label="Agency (Level 1)",
        type="string",
        fieldType="text",
        groupName="govwin",
        description="Top-level government agency",
    ),
    HubSpotProperty(
        name="govwin_entity_level2",
        label="Sub-Agency (Level 2)",
        type="string",
        fieldType="text",
        groupName="govwin",
        description="Sub-agency or office",
    ),
]

# ---------------------------------------------------------------------------
# Pipeline Configuration
# ---------------------------------------------------------------------------

# Use an existing HubSpot pipeline instead of creating a new one.
# This avoids hitting the pipeline limit on non-Enterprise accounts.
PIPELINE_NAME = "Government"

# Map GovWin statuses to stage labels in the existing pipeline.
# These must match the stage labels in your HubSpot "Government" pipeline.
#
# The vocabulary below was confirmed against 1,000 live federal+SLED opps on
# 2026-04-28; Deltek's WSAPI docs (Appendix C) describe `status` as 100-char
# free text rather than a published enum, so this map combines the actually-
# observed values with the legacy values our earlier rollouts saw. New statuses
# fall through to ``DEFAULT_STAGE_LABEL`` so the deal still lands in a stage
# instead of being created with ``dealstage = null``.
GOVWIN_STATUS_TO_STAGE: dict[str, str] = {
    # Identified / forecast (pre-solicitation)
    "Pre-RFP": "Opportunity Identified",
    "Pre-Solicitation": "Opportunity Identified",
    "Forecast Pre-RFP": "Opportunity Identified",
    "Umbrella Program": "Opportunity Identified",
    # Reviewing requirements (solicitation released, BD evaluating)
    "RFP Released": "Reviewing Requirements",
    "RFP": "Reviewing Requirements",
    "Solicitation": "Reviewing Requirements",
    # Preparing response (proposal in flight)
    "Proposal Submitted": "Preparing Response",
    # Submitted (in evaluation, source selection)
    "Under Evaluation": "Submitted",
    "Evaluation": "Submitted",
    "Source Selection": "Submitted",
    "Post-RFP": "Submitted",
    # Closed won
    "Awarded": "Closed Won",
    "Award": "Closed Won",
    "Partial Award": "Closed Won",
    # Closed lost
    "Cancelled": "Closed Lost",
    "Canceled": "Closed Lost",
    "Closed": "Closed Lost",
    "Lost": "Closed Lost",
    "Deleted/Canceled": "Closed Lost",
    "Expired/Archived": "Closed Lost",
    # Other paths
    "Declined": "Declined",
    "Other": "Other",
}

# Fallback stage for any GovWin status not in the map above. Lands the deal in
# the catch-all "Other" stage instead of creating it with ``dealstage = null``.
# A WARN log fires whenever this fallback is hit so unmapped statuses are easy
# to find in CloudWatch and add to GOVWIN_STATUS_TO_STAGE.
DEFAULT_STAGE_LABEL = "Other"
