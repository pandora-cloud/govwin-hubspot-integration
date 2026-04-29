"""Map a HubSpot deal record to an AWS Partner Central CreateOpportunity payload.

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

# Allowed values for ``Project.DeliveryModels``.
ALLOWED_DELIVERY_MODELS: set[str] = {
    "SaaS or PaaS",
    "BYOL or AMI",
    "Managed Services",
    "Professional Services",
    "Resell",
    "Other",
}


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
    """Build the Customer block from agency / industry properties."""
    company_name = _get(deal, "govwin_agency") or _get(deal, "dealname") or "Unknown Federal Agency"
    industry = _get(deal, "govwin_industry") or "Government"
    block: dict[str, Any] = {
        "Account": {
            "CompanyName": company_name,
            "Industry": industry,
            "CountryCode": "US",
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
        raise ACEMappingError(f"Invalid DeliveryModels: {invalid}")

    project: dict[str, Any] = {
        "Title": title[:255],
        "DeliveryModels": delivery_models,
    }
    if description:
        project["CustomerUseCase"] = description[:1500]
        project["CustomerBusinessProblem"] = description[:1500]

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
    primary_needs = _split_csv(_get(deal, "govwin_ace_partner_need"))
    if not primary_needs:
        raise ACEMappingError(
            "govwin_ace_partner_need is required (one or more of: "
            f"{sorted(ALLOWED_PRIMARY_NEEDS)})"
        )
    invalid_needs = [n for n in primary_needs if n not in ALLOWED_PRIMARY_NEEDS]
    if invalid_needs:
        raise ACEMappingError(f"Invalid PrimaryNeedsFromAws: {invalid_needs}")

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
    """Return the Solution ID to associate with this opportunity.

    Honors a per-deal override via ``govwin_ace_solution_id``; otherwise uses
    the configured default. Raises if neither is set so we never associate
    the wrong solution silently.
    """
    override = _get(deal, "govwin_ace_solution_id")
    if override:
        return str(override)
    if config.ace.default_solution_id:
        return config.ace.default_solution_id
    raise ACEMappingError(
        "No Solution ID available: set govwin_ace_solution_id on the deal "
        "or ACE_DEFAULT_SOLUTION_ID in config"
    )
