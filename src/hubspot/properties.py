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
        fieldType="select",
        description="Type of AWS support needed (manual entry for ACE submission)",
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
]

# ---------------------------------------------------------------------------
# Company Custom Properties
# ---------------------------------------------------------------------------

COMPANY_PROPERTIES: list[HubSpotProperty] = [
    HubSpotProperty(
        name="govwin_gov_entity_id",
        label="GovWin Entity ID",
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
# Pipeline Definition
# ---------------------------------------------------------------------------

GOVWIN_PIPELINE = {
    "label": "GovWin Pipeline",
    "displayOrder": 1,
    "stages": [
        {"label": "Pre-RFP", "displayOrder": 0, "metadata": {"probability": "0.1"}},
        {"label": "RFP Released", "displayOrder": 1, "metadata": {"probability": "0.2"}},
        {"label": "Proposal Submitted", "displayOrder": 2, "metadata": {"probability": "0.4"}},
        {"label": "Under Evaluation", "displayOrder": 3, "metadata": {"probability": "0.5"}},
        {"label": "Other", "displayOrder": 4, "metadata": {"probability": "0.2"}},
        {
            "label": "Awarded (Won)",
            "displayOrder": 5,
            "metadata": {"probability": "1.0", "isClosed": "true"},
        },
        {
            "label": "Cancelled (Lost)",
            "displayOrder": 6,
            "metadata": {"probability": "0.0", "isClosed": "true"},
        },
    ],
}

# Map from GovWin status to pipeline stage label
GOVWIN_STATUS_TO_STAGE: dict[str, str] = {
    "Pre-RFP": "Pre-RFP",
    "Pre-Solicitation": "Pre-RFP",
    "RFP Released": "RFP Released",
    "RFP": "RFP Released",
    "Solicitation": "RFP Released",
    "Proposal Submitted": "Proposal Submitted",
    "Under Evaluation": "Under Evaluation",
    "Evaluation": "Under Evaluation",
    "Awarded": "Awarded (Won)",
    "Award": "Awarded (Won)",
    "Cancelled": "Cancelled (Lost)",
    "Closed": "Cancelled (Lost)",
    "Lost": "Cancelled (Lost)",
}
