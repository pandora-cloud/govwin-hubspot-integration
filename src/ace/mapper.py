"""HubSpot deal -> AWS Partner Central CreateOpportunity payload.

The pipeline keeps three fields **manual** because they cannot be reliably
auto-populated from GovWin data:

* ``PrimaryNeedsFromAws`` (HubSpot property: ``govwin_ace_partner_need``)
* ``Project.DeliveryModels`` (HubSpot property: ``govwin_ace_delivery_model``)
* The Solution association (handled via :func:`AssociateOpportunity`,
  defaulting to ``ACEConfig.default_solution_id`` when the deal does not
  override it via ``govwin_ace_solution_id``)

If any required manual field is missing the mapper raises ``ValueError`` so
the submission Lambda can DLQ the deal back to the BD team for completion.
"""

from __future__ import annotations

import logging
from typing import Any

from src.config import AppConfig

logger = logging.getLogger(__name__)


# Allowed values for ``PrimaryNeedsFromAws`` per the AWS docs (April 2026).
ALLOWED_PRIMARY_NEEDS: set[str] = {
    "Co-Sell - Architectural Validation",
    "Co-Sell - Business Presentation",
    "Co-Sell - Competitive Information",
    "Co-Sell - Pricing Assistance",
    "Co-Sell - Technical Consultation",
    "Co-Sell - Total Cost of Ownership Evaluation",
    "Co-Sell - Deal Support",
    "Co-Sell - Support for Public Tender / RFx",
}

# HubSpot's govwin_ace_partner_need property uses short labels (e.g.
# "Technical Consultation") but AWS PrimaryNeedsFromAws expects the
# Co-Sell-prefixed long form. This map normalizes; values already in the
# AWS-long form pass through unchanged.
_HUBSPOT_PARTNER_NEED_TO_AWS: dict[str, str] = {
    "Architectural Validation": "Co-Sell - Architectural Validation",
    "Business Presentation": "Co-Sell - Business Presentation",
    "Competitive Intelligence": "Co-Sell - Competitive Information",
    "Competitive Information": "Co-Sell - Competitive Information",
    "Pricing Assistance": "Co-Sell - Pricing Assistance",
    "Technical Consultation": "Co-Sell - Technical Consultation",
    "Total Cost of Ownership Evaluation": "Co-Sell - Total Cost of Ownership Evaluation",
    "Deal Support": "Co-Sell - Deal Support",
    "Support for Public Tender": "Co-Sell - Support for Public Tender / RFx",
    "Support for Public Tender / RFx": "Co-Sell - Support for Public Tender / RFx",
}


def _normalize_partner_need(value: str) -> str:
    """Translate HubSpot short labels to AWS-long PrimaryNeedsFromAws values."""
    return _HUBSPOT_PARTNER_NEED_TO_AWS.get(value, value)

# Allowed values for ``Project.DeliveryModels``.
ALLOWED_DELIVERY_MODELS: set[str] = {
    "SaaS or PaaS",
    "BYOL or AMI",
    "Managed Services",
    "Professional Services",
    "Resell",
    "Other",
}

# Allowed values for ``Project.CustomerUseCase``. Server-side enum (not in
# the boto3 client model). Sourced from the API's ValidationException error
# message; refresh by calling CreateOpportunity with an invalid value to
# get the latest list. The enum is broader than just "what AWS service is
# being used"; treat as a use-case category.
ALLOWED_CUSTOMER_USE_CASES: set[str] = {
    "AI Machine Learning and Analytics",
    "Archiving",
    "Big Data: Data Warehouse / Data Integration / ETL / Data Lake / BI",
    "Blockchain",
    "Business Applications: Mainframe Modernization",
    "Business Applications & Contact Center",
    "Business Applications & SAP Production",
    "Centralized Operations Management",
    "Cloud Management Tools",
    "Cloud Management Tools & DevOps with Continuous Integration & Continuous Delivery (CICD)",
    "Configuration, Compliance & Auditing",
    "Connected Services",
    "Containers & Serverless",
    "Content Delivery & Edge Services",
    "Database",
    "Edge Computing / End User Computing",
    "Energy",
    "Enterprise Governance & Controls",
    "Enterprise Resource Planning",
    "Financial Services",
    "Healthcare and Life Sciences",
    "High Performance Computing",
    "Hybrid Application Platform",
    "Industrial Software",
    "IOT",
    "Manufacturing, Supply Chain and Operations",
    "Media & High performance computing (HPC)",
    "Migration / Database Migration",
    "Monitoring, logging and performance",
    "Monitoring & Observability",
    "Networking",
    "Outpost",
    "SAP",
    "Security & Compliance",
    "Storage & Backup",
    "Training",
    "VMC",
    "VMWare",
    "Web development & DevOps",
}

DEFAULT_CUSTOMER_USE_CASE = "Migration / Database Migration"


# StateOrRegion is a server-side enum that uses full names (with the
# specific oddity "Dist. of Columbia" instead of "District of Columbia").
# We keep a postal-code-to-enum-name lookup so HubSpot company records
# carrying the standard 2-letter abbreviation Just Work; everything else
# falls through unchanged.
_STATE_ABBR_TO_FULL: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AS": "American Samoa", "AZ": "Arizona",
    "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "Dist. of Columbia",
    "FM": "Federated States of Micronesia", "FL": "Florida", "GA": "Georgia",
    "GU": "Guam", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MH": "Marshall Islands",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PW": "Palau", "PA": "Pennsylvania",
    "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "VI": "Virgin Islands",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming",
}


def _normalize_state(value: str | None) -> str:
    """Return the AWS-accepted full state name for a HubSpot state value.

    Accepts the standard 2-letter postal abbreviation (most HubSpot company
    records use this) and returns the matching full name. Unknown values
    pass through unchanged so a real full name like "California" still
    works, and AWS's enum check is the final gate.
    """
    if not value:
        return "Dist. of Columbia"
    upper = value.strip().upper()
    return _STATE_ABBR_TO_FULL.get(upper, value)


class ACEMappingError(ValueError):
    """Raised when a HubSpot deal cannot be mapped to a valid ACE payload."""


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [segment.strip() for segment in value.split(";") if segment.strip()]


def _get(deal: dict[str, Any], key: str) -> Any:
    """Pull a property off a HubSpot deal payload (handles nested ``properties``)."""
    if "properties" in deal and isinstance(deal["properties"], dict):
        return deal["properties"].get(key) or deal.get(key)
    return deal.get(key)


def _customer_block(deal: dict[str, Any]) -> dict[str, Any]:
    """Build the Customer.Account block from agency / industry properties.

    Sandbox business validation requires WebsiteUrl, Address.PostalCode,
    and Address.StateOrRegion in addition to CompanyName. Production may
    require more. We pull from HubSpot company-association fields when
    available and fall back to GovWin agency defaults.

    CountryCode lives under Customer.Account.Address (not flat on Account)
    per the AWS Partner Central Selling API shape.
    """
    company_name = (
        _get(deal, "govwin_agency") or _get(deal, "dealname") or "Unknown Federal Agency"
    )
    industry = _get(deal, "govwin_industry") or "Government"
    website = _get(deal, "govwin_entity_url") or _get(deal, "website") or "https://www.usa.gov"
    postal_code = _get(deal, "zip") or _get(deal, "govwin_customer_postal_code") or "20001"
    state = _normalize_state(_get(deal, "state") or _get(deal, "govwin_customer_state"))
    block: dict[str, Any] = {
        "Account": {
            "CompanyName": company_name,
            "Industry": industry,
            "WebsiteUrl": website,
            "Address": {
                "CountryCode": "US",
                "PostalCode": postal_code,
                "StateOrRegion": state,
            },
        }
    }
    return block


def _project_block(deal: dict[str, Any]) -> dict[str, Any]:
    title = _get(deal, "dealname") or "GovWin Opportunity"
    description = _get(deal, "description") or _get(deal, "govwin_primary_requirement") or ""
    delivery_models = _split_csv(_get(deal, "govwin_ace_delivery_model"))
    if not delivery_models:
        raise ACEMappingError(
            "govwin_ace_delivery_model is required (one of: "
            f"{sorted(ALLOWED_DELIVERY_MODELS)})"
        )
    invalid = [m for m in delivery_models if m not in ALLOWED_DELIVERY_MODELS]
    if invalid:
        raise ACEMappingError(
            f"Invalid DeliveryModels: {len(invalid)} value(s) not in the "
            "AWS-published enum"
        )

    project: dict[str, Any] = {
        "Title": title[:255],
        "DeliveryModels": delivery_models,
    }
    if description:
        # CustomerBusinessProblem is free text; CustomerUseCase is an
        # AWS-published enum (different from a free-text description).
        # Server-side regex requires 20-2000 chars, so deals with very
        # short descriptions get padded with the deal title for context.
        text = description[:2000]
        if len(text) < 20:
            title_for_pad = title[:200]
            text = f"{title_for_pad}: {text}"[:2000]
        if len(text) >= 20:
            project["CustomerBusinessProblem"] = text

    # Resolve CustomerUseCase from a HubSpot custom property override or the
    # default ("Migration / Database Migration"). Reject deals that override
    # to a value not in the published enum so AWS does not reject them later.
    use_case = _get(deal, "govwin_ace_use_case") or DEFAULT_CUSTOMER_USE_CASE
    if use_case not in ALLOWED_CUSTOMER_USE_CASES:
        raise ACEMappingError(
            "Invalid CustomerUseCase: value not in the AWS-published enum"
        )
    project["CustomerUseCase"] = use_case

    # AWS rejects the opportunity if neither a Solution association nor
    # OtherSolutionDescription is provided. Since AssociateOpportunity is
    # a separate post-create step (and may be skipped, e.g. in Sandbox),
    # we always populate OtherSolutionDescription here as a fallback.
    # Per-deal override via govwin_ace_other_solution_description wins;
    # otherwise we fall back to the deal title.
    other_solution = (
        _get(deal, "govwin_ace_other_solution_description")
        or title
        or "Partner solution"
    )
    project["OtherSolutionDescription"] = str(other_solution)[:255]

    amount = _get(deal, "amount")
    if amount:
        try:
            spend = float(amount)
            project["ExpectedCustomerSpend"] = [
                {
                    "Amount": f"{spend:.2f}",
                    "CurrencyCode": "USD",
                    "Frequency": "Monthly",
                    "TargetCompany": "Pandora Cloud LLC",
                }
            ]
        except (TypeError, ValueError):
            logger.warning("ace.mapper: invalid amount %r on deal %s", amount, deal.get("id"))

    return project


def _life_cycle_block(deal: dict[str, Any]) -> dict[str, Any]:
    closedate = _get(deal, "closedate")
    block: dict[str, Any] = {"ReviewStatus": "Pending Submission"}
    if closedate:
        # HubSpot delivers ISO-8601; ACE expects YYYY-MM-DD.
        try:
            block["TargetCloseDate"] = str(closedate)[:10]
        except (TypeError, AttributeError):
            pass
    return block


def map_hubspot_deal_to_ace_create_payload(
    deal: dict[str, Any],
    config: AppConfig,
    *,
    client_token: str,
) -> dict[str, Any]:
    """Build a ``CreateOpportunity`` payload from a HubSpot deal.

    :param deal: HubSpot deal record (either flat or nested ``{properties: {...}}``).
    :param config: app config (provides catalog and default origin/involvement).
    :param client_token: caller-supplied UUID; persist before calling ``CreateOpportunity``.
    :raises ACEMappingError: when required manual fields are missing or invalid.
    """
    primary_needs_raw = _split_csv(_get(deal, "govwin_ace_partner_need"))
    if not primary_needs_raw:
        raise ACEMappingError(
            "govwin_ace_partner_need is required (one or more of: "
            f"{sorted(ALLOWED_PRIMARY_NEEDS)})"
        )
    primary_needs = [_normalize_partner_need(n) for n in primary_needs_raw]
    invalid_needs = [n for n in primary_needs if n not in ALLOWED_PRIMARY_NEEDS]
    if invalid_needs:
        # Redact full values; report only count to keep deal text out of logs/DLQ.
        raise ACEMappingError(
            f"Invalid PrimaryNeedsFromAws: {len(invalid_needs)} value(s) not "
            "in the AWS-published enum"
        )

    govwin_id = _get(deal, "govwin_opp_id") or _get(deal, "govwin_iq_opp_id")

    payload: dict[str, Any] = {
        "Catalog": config.ace.catalog,
        "ClientToken": client_token,
        "Origin": config.ace.default_origin,
        "OpportunityType": "Net New Business",
        "PrimaryNeedsFromAws": primary_needs,
        "Project": _project_block(deal),
        "Customer": _customer_block(deal),
        "LifeCycle": _life_cycle_block(deal),
    }
    if govwin_id:
        payload["PartnerOpportunityIdentifier"] = str(govwin_id)
    return payload


def resolve_solution_id(deal: dict[str, Any], config: AppConfig) -> str:
    """Return the AWS Solution ID to associate, or "" if none is configured.

    Lookup order:
      1. ``govwin_ace_solution_id`` per-deal override (preferred name)
      2. ``govwin_ace_solution`` per-deal legacy field name
      3. configured ``ace_default_solution_id`` (production catalog only)

    The configured default is intentionally ignored in the Sandbox catalog
    because production-catalog solutions do not exist in the Sandbox
    catalog. In Sandbox, callers fall back to OtherSolutionDescription on
    the create payload.

    Returns "" when nothing is set, so the caller can fall back to the
    OtherSolutionDescription path instead of failing the submission.
    """
    override = _get(deal, "govwin_ace_solution_id") or _get(deal, "govwin_ace_solution")
    if override:
        return str(override)
    if config.ace.catalog == "Sandbox":
        return ""
    return config.ace.default_solution_id or ""
