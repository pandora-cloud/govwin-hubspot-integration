"""Transform GovWin data into HubSpot properties, including NAICS-to-AWS-industry mapping."""

from __future__ import annotations

import html
import re
from typing import Any

from src.models import (
    GovWinContact,
    GovWinGovEntity,
    GovWinOpportunityBundle,
)

# ---------------------------------------------------------------------------
# NAICS prefix -> AWS ACE industry mapping
# ---------------------------------------------------------------------------

NAICS_TO_AWS_INDUSTRY: dict[str, str] = {
    "11": "Agriculture",
    "21": "Energy",
    "22": "Energy",
    "23": "Other",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Distribution",
    "44": "Consumer Goods",
    "45": "Consumer Goods",
    "48": "Transportation",
    "49": "Transportation",
    "51": "Software & Internet",
    "52": "Financial Services",
    "53": "Other",
    "54": "Professional Services",
    "55": "Professional Services",
    "56": "Professional Services",
    "61": "Education",
    "62": "Healthcare",
    "71": "Media & Entertainment",
    "72": "Travel & Hospitality",
    "81": "Other",
    "92": "Government",
}


def naics_to_aws_industry(naics_code: str | None) -> str:
    """Map a NAICS code to an AWS ACE industry classification."""
    if not naics_code:
        return "Government"  # Default for gov contracting

    prefix = naics_code[:2]
    return NAICS_TO_AWS_INDUSTRY.get(prefix, "Other")


# ---------------------------------------------------------------------------
# HTML sanitization
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
MAX_DESCRIPTION_LENGTH = 65536


def sanitize_html(text: str | None) -> str | None:
    """Strip HTML tags and decode entities, truncate to HubSpot limit."""
    if not text:
        return text
    clean = _TAG_RE.sub("", text)
    clean = html.unescape(clean)
    clean = clean.strip()
    if len(clean) > MAX_DESCRIPTION_LENGTH:
        clean = clean[:MAX_DESCRIPTION_LENGTH]
    return clean


# ---------------------------------------------------------------------------
# Date extraction helpers
# ---------------------------------------------------------------------------

def _extract_date_value(date_field: dict[str, Any] | str | None) -> str | None:
    """Extract a date string from GovWin's date field format."""
    if not date_field:
        return None
    if isinstance(date_field, str):
        return date_field
    return date_field.get("value")


def _extract_link_href(links: Any) -> str | None:
    """Extract the webHref URL from GovWin links."""
    if not links:
        return None
    web_href = links.web_href if hasattr(links, "web_href") else None
    if isinstance(web_href, dict):
        return web_href.get("href")
    if isinstance(web_href, str):
        return web_href
    return None


# ---------------------------------------------------------------------------
# Opportunity -> Deal mapper
# ---------------------------------------------------------------------------

def map_opportunity_to_deal(
    bundle: GovWinOpportunityBundle,
    pipeline_id: str | None = None,
    stage_id: str | None = None,
) -> dict[str, Any]:
    """Map a GovWin opportunity bundle to a HubSpot deal upsert payload."""
    opp = bundle.opportunity

    # Determine close date from projected award or response date
    close_date = (
        _extract_date_value(opp.p_award_date_to)
        or _extract_date_value(opp.response_date)
    )

    # Calculate amount (GovWin stores in thousands)
    amount = None
    if opp.opp_value is not None:
        amount = str(int(opp.opp_value * 1000))
    elif opp.opp_value_canada is not None:
        amount = str(int(opp.opp_value_canada * 1000))

    # NAICS -> AWS industry
    naics_code = opp.primary_naics.id if opp.primary_naics else None
    industry = naics_to_aws_industry(naics_code)

    # Smart tags concatenation
    smart_tags = None
    if opp.smart_tag:
        tags = []
        for tag in opp.smart_tag:
            if isinstance(tag, dict) and tag.get("title"):
                tags.append(tag["title"])
        smart_tags = "; ".join(tags) if tags else None

    # Competition and contract types
    competition_type = None
    if opp.competition_types:
        competition_type = opp.competition_types[0].get("title")

    contract_type = None
    if opp.contract_types:
        contract_type = opp.contract_types[0].get("title")

    properties: dict[str, Any] = {
        "dealname": opp.title or "Untitled GovWin Opportunity",
        "amount": amount,
        "description": sanitize_html(opp.description),
        "closedate": close_date,
        "govwin_opp_id": opp.id,
        "govwin_iq_opp_id": str(opp.iq_opp_id) if opp.iq_opp_id else None,
        "govwin_opp_type": opp.type,
        "govwin_status": opp.status,
        "govwin_solicitation_date": _extract_date_value(opp.solicitation_date),
        "govwin_solicitation_number": opp.solicitation_number,
        "govwin_source_url": opp.source_url,
        "govwin_iq_url": _extract_link_href(opp.links),
        "govwin_duration": opp.duration,
        "govwin_primary_naics": opp.primary_naics.title if opp.primary_naics else None,
        "govwin_naics_code": naics_code,
        "govwin_primary_requirement": opp.primary_requirement,
        "govwin_analyst_notes": sanitize_html(opp.procurement),
        "govwin_competition_type": competition_type,
        "govwin_contract_type": contract_type,
        "govwin_type_of_award": opp.type_of_award,
        "govwin_country": opp.country,
        "govwin_created_date": opp.created_date,
        "govwin_update_date": opp.update_date,
        "govwin_cmmc_requirements": opp.cmmc_requirements,
        "govwin_smart_tags": smart_tags,
        "govwin_agency": opp.gov_entity.title if opp.gov_entity else None,
        "govwin_priority": str(opp.priority) if opp.priority else None,
        # ACE-ready fields
        "govwin_industry": industry,
        "govwin_ace_opportunity_type": "Net New Business",
    }

    if pipeline_id:
        properties["pipeline"] = pipeline_id
    if stage_id:
        properties["dealstage"] = stage_id

    # Remove None values
    properties = {k: v for k, v in properties.items() if v is not None}

    return {"properties": properties}


# ---------------------------------------------------------------------------
# GovEntity -> Company mapper
# ---------------------------------------------------------------------------

def map_gov_entity_to_company(
    entity: GovWinGovEntity,
) -> dict[str, Any]:
    """Map a GovWin government entity to a HubSpot company upsert payload."""
    parent_agency = None
    if entity.parent_hierarchy:
        parent_agency = entity.parent_hierarchy[0].get("title")

    properties: dict[str, Any] = {
        "name": entity.title or "Unknown Agency",
        "industry": "Government",
        "govwin_gov_entity_id": str(entity.id) if entity.id else None,
        "govwin_parent_agency": parent_agency,
    }

    properties = {k: v for k, v in properties.items() if v is not None}
    return {"properties": properties}


# ---------------------------------------------------------------------------
# Contact -> Contact mapper
# ---------------------------------------------------------------------------

def map_contact_to_hubspot(contact: GovWinContact) -> dict[str, Any]:
    """Map a GovWin contact to a HubSpot contact upsert payload."""
    properties: dict[str, Any] = {
        "email": contact.email,
        "firstname": contact.first_name,
        "lastname": contact.last_name,
        "phone": contact.phone,
        "jobtitle": contact.title,
        "address": contact.address1,
        "city": contact.city,
        "state": contact.state,
        "zip": contact.zip,
        "govwin_contact_id": contact.contact_id,
        "govwin_entity_level1": contact.gov_entity_level1,
        "govwin_entity_level2": contact.gov_entity_level2,
    }

    properties = {k: v for k, v in properties.items() if v is not None}
    return {"properties": properties}
