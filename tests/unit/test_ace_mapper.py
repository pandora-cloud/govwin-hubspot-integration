"""Tests for the HubSpot deal -> ACE CreateOpportunity payload mapper."""

from __future__ import annotations

import pytest

from src.ace.mapper import (
    ACEMappingError,
    map_hubspot_deal_to_ace_create_payload,
    resolve_solution_id,
)
from src.config import AppConfig


@pytest.fixture
def deal() -> dict[str, object]:
    return {
        "id": "1234567890",
        "properties": {
            "dealname": "DoD Cloud Migration",
            "amount": "150000",
            "closedate": "2026-12-31T00:00:00Z",
            "description": "DoD wants AWS migration support.",
            "govwin_opp_id": "OPP263150",
            "govwin_agency": "Department of Defense",
            "govwin_industry": "Government",
            "govwin_ace_partner_need": "Co-Sell - Technical Consultation",
            "govwin_ace_delivery_model": "Professional Services",
        },
    }


class TestMapHubSpotDealToACECreatePayload:
    def test_happy_path(self, deal: dict[str, object], app_config: AppConfig) -> None:
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok-1"
        )
        assert payload["Catalog"] == "Sandbox"
        assert payload["ClientToken"] == "tok-1"
        assert payload["Origin"] == "Partner Referral"
        assert payload["OpportunityType"] == "Net New Business"
        assert payload["PrimaryNeedsFromAws"] == ["Co-Sell - Technical Consultation"]
        assert payload["Project"]["Title"] == "DoD Cloud Migration"
        assert payload["Project"]["DeliveryModels"] == ["Professional Services"]
        assert payload["Customer"]["Account"]["CompanyName"] == "Department of Defense"
        assert payload["Customer"]["Account"]["Industry"] == "Government"
        # CountryCode lives under Address, not flat on Account, per the
        # AWS Partner Central Selling API shape.
        assert payload["Customer"]["Account"]["Address"]["CountryCode"] == "US"
        assert "CountryCode" not in payload["Customer"]["Account"]
        # Sandbox business validation requires WebsiteUrl + full address.
        assert payload["Customer"]["Account"]["WebsiteUrl"]
        assert payload["Customer"]["Account"]["Address"]["PostalCode"]
        assert payload["Customer"]["Account"]["Address"]["StateOrRegion"]
        # CustomerUseCase must be one of the AWS-published enum, not free text.
        assert payload["Project"]["CustomerUseCase"] == "Migration / Database Migration"
        assert payload["LifeCycle"]["TargetCloseDate"] == "2026-12-31"
        assert payload["PartnerOpportunityIdentifier"] == "OPP263150"
        assert payload["Project"]["ExpectedCustomerSpend"][0]["Amount"] == "150000.00"

    def test_invalid_customer_use_case_raises(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_use_case"] = "not in the enum"  # type: ignore[index]
        with pytest.raises(ACEMappingError, match="Invalid CustomerUseCase"):
            map_hubspot_deal_to_ace_create_payload(deal, app_config, client_token="tok")

    def test_use_case_override_accepted(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_use_case"] = "Security & Compliance"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert payload["Project"]["CustomerUseCase"] == "Security & Compliance"

    def test_missing_partner_need_raises(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_partner_need"] = ""  # type: ignore[index]
        with pytest.raises(ACEMappingError, match="govwin_ace_partner_need"):
            map_hubspot_deal_to_ace_create_payload(deal, app_config, client_token="tok")

    def test_invalid_partner_need_raises(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_partner_need"] = "Some Invented Need"  # type: ignore[index]
        with pytest.raises(ACEMappingError, match="Invalid PrimaryNeedsFromAws"):
            map_hubspot_deal_to_ace_create_payload(deal, app_config, client_token="tok")

    def test_missing_delivery_model_raises(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_delivery_model"] = ""  # type: ignore[index]
        with pytest.raises(ACEMappingError, match="govwin_ace_delivery_model"):
            map_hubspot_deal_to_ace_create_payload(deal, app_config, client_token="tok")

    def test_invalid_delivery_model_raises(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_delivery_model"] = "Snake Oil"  # type: ignore[index]
        with pytest.raises(ACEMappingError, match="Invalid DeliveryModels"):
            map_hubspot_deal_to_ace_create_payload(deal, app_config, client_token="tok")

    def test_multiple_partner_needs_split_on_semicolon(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_partner_need"] = (  # type: ignore[index]
            "Co-Sell - Technical Consultation;Co-Sell - Pricing Assistance"
        )
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert "Co-Sell - Technical Consultation" in payload["PrimaryNeedsFromAws"]
        assert "Co-Sell - Pricing Assistance" in payload["PrimaryNeedsFromAws"]

    def test_invalid_amount_does_not_raise(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["amount"] = "not-a-number"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert "ExpectedCustomerSpend" not in payload["Project"]

    def test_flat_deal_payload_supported(self, app_config: AppConfig) -> None:
        flat = {
            "dealname": "Flat Deal",
            "govwin_ace_partner_need": "Co-Sell - Deal Support",
            "govwin_ace_delivery_model": "Resell",
        }
        payload = map_hubspot_deal_to_ace_create_payload(
            flat, app_config, client_token="tok"
        )
        assert payload["Project"]["Title"] == "Flat Deal"


class TestResolveSolutionId:
    def test_uses_default(self, deal: dict[str, object], app_config: AppConfig) -> None:
        assert resolve_solution_id(deal, app_config) == "S-0051246"

    def test_per_deal_override_wins(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_solution_id"] = "S-0050888"  # type: ignore[index]
        assert resolve_solution_id(deal, app_config) == "S-0050888"

    def test_no_default_raises(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        from dataclasses import replace
        cfg = replace(app_config, ace=replace(app_config.ace, default_solution_id=""))
        with pytest.raises(ACEMappingError, match="No Solution ID"):
            resolve_solution_id(deal, cfg)
