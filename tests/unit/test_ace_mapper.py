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
        # MRR fix: 150_000 total / 12 months ≈ 12500 monthly to match
        # AWS Frequency=Monthly semantics.
        assert payload["Project"]["ExpectedCustomerSpend"][0]["Amount"] == "12500.00"
        assert payload["Project"]["ExpectedCustomerSpend"][0]["Frequency"] == "Monthly"

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

    def test_sales_activities_seeded_by_default(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """AWS requires Project.SalesActivities to be non-empty before it
        will advance the opportunity to ReviewStatus=Submitted. Verify the
        mapper seeds a default so the review flow does not stall.
        """
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        activities = payload["Project"]["SalesActivities"]
        assert isinstance(activities, list) and len(activities) >= 1
        # Every element must be in the AWS-published enum.
        from src.ace.mapper import ALLOWED_SALES_ACTIVITIES
        assert all(a in ALLOWED_SALES_ACTIVITIES for a in activities)

    def test_use_case_other_falls_back_to_default(
        self, deal: dict[str, object], app_config: AppConfig, caplog
    ) -> None:
        """Legacy 'Other' value (BD UX shorthand for 'I don't know which fits')
        must NOT block submission. Mapper silently substitutes the default
        and logs a warning so the operator sees what happened.
        """
        deal["properties"]["govwin_ace_use_case"] = "Other"  # type: ignore[index]
        with caplog.at_level("WARNING"):
            payload = map_hubspot_deal_to_ace_create_payload(
                deal, app_config, client_token="tok"
            )
        assert payload["Project"]["CustomerUseCase"] == "Migration / Database Migration"
        assert any("Other" in r.message for r in caplog.records)

    def test_hubspot_short_partner_need_translates_to_aws_long(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """HubSpot stores short labels; AWS expects the Co-Sell-prefixed form."""
        deal["properties"]["govwin_ace_partner_need"] = "Technical Consultation"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert payload["PrimaryNeedsFromAws"] == ["Co-Sell - Technical Consultation"]

    def test_other_solution_description_emitted_when_set(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_other_solution_description"] = (  # type: ignore[index]
            "Pandora federal cloud services"
        )
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert (
            payload["Project"]["OtherSolutionDescription"]
            == "Pandora federal cloud services"
        )

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
    def test_uses_default_in_aws_catalog(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        from dataclasses import replace
        cfg = replace(app_config, ace=replace(app_config.ace, catalog="AWS"))
        assert resolve_solution_id(deal, cfg) == "S-0051246"

    def test_default_ignored_in_sandbox_catalog(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """Sandbox does not have production solutions; default is ignored."""
        # app_config fixture uses Sandbox catalog by default.
        assert resolve_solution_id(deal, app_config) == ""

    def test_per_deal_override_wins(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_solution_id"] = "S-0050888"  # type: ignore[index]
        assert resolve_solution_id(deal, app_config) == "S-0050888"

    def test_no_default_returns_empty(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """When neither override nor default is set, returns "" (caller falls
        back to OtherSolutionDescription)."""
        from dataclasses import replace
        cfg = replace(app_config, ace=replace(app_config.ace, default_solution_id=""))
        assert resolve_solution_id(deal, cfg) == ""

    def test_legacy_solution_field_accepted(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """govwin_ace_solution (legacy property name) is also honored."""
        deal["properties"]["govwin_ace_solution"] = "S-9999999"  # type: ignore[index]
        deal["properties"].pop("govwin_ace_solution_id", None)  # type: ignore[union-attr]
        assert resolve_solution_id(deal, app_config) == "S-9999999"


class TestEnumParity:
    """Drift guards: HubSpot dropdown options must be a subset of the AWS
    enums the mapper accepts. If these tests fail, either the AWS API
    enum changed (update the mapper) or someone added a HubSpot option
    that AWS won't accept (will silently get rejected by submit_to_ace).
    """

    def test_hubspot_use_case_options_are_subset_of_mapper_allowlist(self) -> None:
        from src.ace.mapper import ALLOWED_CUSTOMER_USE_CASES
        from src.hubspot.properties import DEAL_PROPERTIES

        prop = next(p for p in DEAL_PROPERTIES if p.name == "govwin_ace_use_case")
        hubspot_values = {opt["value"] for opt in (prop.options or [])}
        unknown = hubspot_values - ALLOWED_CUSTOMER_USE_CASES
        assert not unknown, (
            f"HubSpot dropdown govwin_ace_use_case exposes values not in "
            f"ALLOWED_CUSTOMER_USE_CASES; AWS will reject submission for "
            f"these: {sorted(unknown)}"
        )

    def test_hubspot_partner_need_options_are_subset_of_mapper_allowlist(self) -> None:
        from src.ace.mapper import _HUBSPOT_PARTNER_NEED_TO_AWS
        from src.hubspot.properties import DEAL_PROPERTIES

        prop = next(p for p in DEAL_PROPERTIES if p.name == "govwin_ace_partner_need")
        hubspot_values = {opt["value"] for opt in (prop.options or [])}
        unmapped = hubspot_values - set(_HUBSPOT_PARTNER_NEED_TO_AWS.keys())
        assert not unmapped, (
            f"HubSpot dropdown govwin_ace_partner_need has options the "
            f"mapper cannot translate to AWS PrimaryNeedsFromAws values: "
            f"{sorted(unmapped)}"
        )

    def test_hubspot_delivery_model_options_are_subset_of_mapper_allowlist(self) -> None:
        from src.ace.mapper import ALLOWED_DELIVERY_MODELS
        from src.hubspot.properties import DEAL_PROPERTIES

        prop = next(p for p in DEAL_PROPERTIES if p.name == "govwin_ace_delivery_model")
        hubspot_values = {opt["value"] for opt in (prop.options or [])}
        unknown = hubspot_values - ALLOWED_DELIVERY_MODELS
        assert not unknown, (
            f"HubSpot dropdown govwin_ace_delivery_model exposes values "
            f"not in ALLOWED_DELIVERY_MODELS: {sorted(unknown)}"
        )


class TestExtendedFieldMapping:
    """Extended-mapping tests: associated company / contacts / owner reads,
    Marketing block, Additional Details, MRR fix, AWS Products list."""

    def test_customer_account_reads_from_associated_company(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        company = {
            "id": "c1",
            "properties": {
                "name": "Department of Energy",
                "industry": "Government",
                "website": "https://www.energy.gov",
                "address": "1000 Independence Ave SW",
                "city": "Washington",
                "state": "DC",
                "zip": "20585",
                "country": "United States",
            },
        }
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok", company=company
        )
        addr = payload["Customer"]["Account"]["Address"]
        assert payload["Customer"]["Account"]["CompanyName"] == "Department of Energy"
        assert payload["Customer"]["Account"]["WebsiteUrl"] == "https://www.energy.gov"
        assert addr["AddressLine1"] == "1000 Independence Ave SW"
        assert addr["City"] == "Washington"
        assert addr["StateOrRegion"] == "Dist. of Columbia"  # "DC" normalized
        assert addr["PostalCode"] == "20585"

    def test_customer_contacts_populated_from_associated_contacts(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        contacts = [
            {
                "id": "1",
                "properties": {
                    "firstname": "Jane",
                    "lastname": "Doe",
                    "email": "jane.doe@energy.gov",
                    "jobtitle": "Contracting Officer",
                    "phone": "202-555-0100",
                },
            },
            {
                "id": "2",
                "properties": {
                    "firstname": "John",
                    "lastname": "Smith",
                    "email": "john.smith@energy.gov",
                    # no title or phone -- still valid
                },
            },
            {
                "id": "3",
                "properties": {
                    # missing email -- must be dropped silently
                    "firstname": "X",
                    "lastname": "Y",
                },
            },
        ]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok", contacts=contacts
        )
        out = payload["Customer"]["Contacts"]
        assert len(out) == 2
        assert out[0] == {
            "FirstName": "Jane",
            "LastName": "Doe",
            "Email": "jane.doe@energy.gov",
            "BusinessTitle": "Contracting Officer",
            "Phone": "+12025550100",  # normalized to E.164
        }
        assert out[1]["FirstName"] == "John"
        assert "BusinessTitle" not in out[1]

    def test_opportunity_team_from_owner(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        owner = {
            "id": "42",
            "firstName": "Isi",
            "lastName": "Lawson",
            "email": "isi@pandoracloud.net",
        }
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok", owner=owner
        )
        assert payload["OpportunityTeam"][0]["Email"] == "isi@pandoracloud.net"
        assert payload["OpportunityTeam"][0]["FirstName"] == "Isi"

    def test_no_owner_omits_opportunity_team(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert "OpportunityTeam" not in payload

    def test_marketing_block_emitted_when_source_is_marketing_activity(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_marketing_source"] = "Marketing Activity"  # type: ignore[index]
        deal["properties"]["govwin_ace_marketing_campaign_name"] = "AWS Re:Invent 2026"  # type: ignore[index]
        deal["properties"]["govwin_ace_marketing_dev_funded"] = "Yes"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert payload["Marketing"]["Source"] == "Marketing Activity"
        assert payload["Marketing"]["CampaignName"] == "AWS Re:Invent 2026"
        assert payload["Marketing"]["AwsFundingUsed"] == "Yes"

    def test_marketing_block_omitted_when_source_none(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """AWS rejects companion Marketing fields when Source is 'None'.
        Skip the whole block in that case (and when Source is unset)."""
        deal["properties"]["govwin_ace_marketing_source"] = "None"  # type: ignore[index]
        deal["properties"]["govwin_ace_marketing_dev_funded"] = "No"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert "Marketing" not in payload

    def test_marketing_block_omitted_when_no_field_set(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert "Marketing" not in payload

    def test_zero_amount_omits_expected_customer_spend(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """RFI-stage opps often carry amount=0 (no disclosed value yet).
        AWS regex rejects strict-zero on Amount, so skip the spend entry
        entirely rather than emit a value AWS will reject."""
        deal["properties"]["amount"] = "0"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert "ExpectedCustomerSpend" not in payload["Project"]

    def test_additional_details_pass_through(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        deal["properties"]["govwin_ace_competitor_name"] = "Microsoft Azure"  # type: ignore[index]
        deal["properties"]["govwin_ace_additional_comments"] = "BD lead Q3"  # type: ignore[index]
        deal["properties"]["govwin_ace_aws_account_id"] = "123456789012"  # type: ignore[index]
        deal["properties"]["govwin_ace_related_opportunity_id"] = "O11111111"  # type: ignore[index]
        deal["properties"]["govwin_ace_next_steps"] = "Schedule discovery call"  # type: ignore[index]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        assert payload["Project"]["CompetitorName"] == "Microsoft Azure"
        assert payload["Project"]["AdditionalComments"] == "BD lead Q3"
        assert payload["Project"]["CustomerAwsAccountId"] == "123456789012"
        assert payload["Project"]["RelatedOpportunityIdentifier"] == "O11111111"
        assert payload["LifeCycle"]["NextSteps"] == "Schedule discovery call"

    def test_mrr_divides_amount_by_twelve(
        self, deal: dict[str, object], app_config: AppConfig
    ) -> None:
        """The MRR fix: AWS expects ExpectedCustomerSpend.Amount to match
        Frequency. We bill monthly, so divide by 12. Without this AWS sees
        12x reality."""
        deal["properties"]["amount"] = "1200000"  # type: ignore[index] -- $1.2M annual
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok"
        )
        spend = payload["Project"]["ExpectedCustomerSpend"][0]
        assert spend["Amount"] == "100000.00"  # 1.2M / 12
        assert spend["Frequency"] == "Monthly"

    def test_aws_products_for_deal_splits_csv(
        self, deal: dict[str, object]
    ) -> None:
        from src.ace.mapper import aws_products_for_deal
        deal["properties"]["govwin_ace_aws_products"] = "AmazonEC2Linux;AWSLambda;AmazonS3"  # type: ignore[index]
        assert aws_products_for_deal(deal) == ["AmazonEC2Linux", "AWSLambda", "AmazonS3"]

    def test_aws_products_for_deal_empty_when_unset(
        self, deal: dict[str, object]
    ) -> None:
        from src.ace.mapper import aws_products_for_deal
        assert aws_products_for_deal(deal) == []


class TestPhoneNormalization:
    """AWS rejects the whole CreateOpportunity when any contact phone fails
    the E.164 regex. We normalize what we can and drop the rest."""

    def test_e164_input_passes_through(self):
        from src.ace.mapper import _normalize_phone
        assert _normalize_phone("+12025550100") == "+12025550100"
        assert _normalize_phone("+1 (202) 555-0100") == "+12025550100"

    def test_us_10_digit_gets_plus_one(self):
        from src.ace.mapper import _normalize_phone
        assert _normalize_phone("202-555-0100") == "+12025550100"
        assert _normalize_phone("(202) 555-0100") == "+12025550100"
        assert _normalize_phone("2025550100") == "+12025550100"

    def test_us_11_digit_starting_with_1(self):
        from src.ace.mapper import _normalize_phone
        assert _normalize_phone("1-202-555-0100") == "+12025550100"

    def test_unparseable_returns_none(self):
        from src.ace.mapper import _normalize_phone
        assert _normalize_phone("ext 555") is None
        assert _normalize_phone("call later") is None
        assert _normalize_phone("0000") is None
        assert _normalize_phone("") is None
        assert _normalize_phone(None) is None

    def test_contact_with_unparseable_phone_drops_phone_only(self, app_config):
        from src.ace.mapper import map_hubspot_deal_to_ace_create_payload
        deal = {
            "properties": {
                "dealname": "X", "amount": "120000", "closedate": "2026-12-31",
                "description": "twenty characters needed for cbp ok",
                "govwin_opp_id": "OPP1", "govwin_agency": "DoD",
                "govwin_industry": "Government",
                "govwin_ace_partner_need": "Co-Sell - Technical Consultation",
                "govwin_ace_delivery_model": "Professional Services",
            }
        }
        contacts = [
            {"properties": {
                "firstname": "Jane", "lastname": "Doe", "email": "jd@x.gov",
                "phone": "ext 555",  # unparseable -- drop only the phone
            }},
        ]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="t", contacts=contacts,
        )
        contact = payload["Customer"]["Contacts"][0]
        assert contact["Email"] == "jd@x.gov"
        assert "Phone" not in contact


class TestSecurityHardening:
    """Audit-driven hardening tests."""

    def test_country_strict_allowlist_rejects_unknown(self, deal, app_config):
        """A free-text country that's not in the lookup map and not a
        valid ISO-2 code raises ACEMappingError rather than silently
        producing a wrong code (e.g. 'Internal Test' -> 'IN' which is
        India). Federal jurisdiction routing depends on this."""
        company = {"id": "c1", "properties": {
            "name": "X", "country": "Internal Test",
        }}
        with pytest.raises(ACEMappingError, match="Cannot map country"):
            map_hubspot_deal_to_ace_create_payload(
                deal, app_config, client_token="tok", company=company,
            )

    def test_country_full_name_resolves(self, deal, app_config):
        company = {"id": "c1", "properties": {"name": "X", "country": "Germany"}}
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok", company=company,
        )
        assert payload["Customer"]["Account"]["Address"]["CountryCode"] == "DE"

    def test_phone_repeated_digits_rejected(self):
        from src.ace.mapper import _normalize_phone
        assert _normalize_phone("0000000000") is None
        assert _normalize_phone("1111111111") is None
        assert _normalize_phone("+1111111111111") is None

    def test_phone_extension_stripped(self):
        from src.ace.mapper import _normalize_phone
        assert _normalize_phone("+1 202 555 0100 x123") == "+12025550100"
        assert _normalize_phone("(202) 555-0100 ext 5") == "+12025550100"
        assert _normalize_phone("202-555-0100,99") == "+12025550100"

    def test_phone_nanp_area_code_validated(self):
        from src.ace.mapper import _normalize_phone
        # 10-digit US: area code must start [2-9]
        assert _normalize_phone("0000000000") is None
        assert _normalize_phone("1234567890") is None  # area code 1, invalid
        # 11-digit US: must be 1-NXXNXXXXXX where N is [2-9]
        assert _normalize_phone("11234567890") is None  # area code 1, invalid

    def test_marketing_block_strips_control_chars(self, deal, app_config):
        deal["properties"]["govwin_ace_marketing_source"] = "Marketing Activity"
        deal["properties"]["govwin_ace_marketing_campaign_name"] = "AWS\x00Re:Invent\x07"
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok",
        )
        assert payload["Marketing"]["CampaignName"] == "AWSRe:Invent"

    def test_contacts_filtered_by_lifecyclestage(self, deal, app_config):
        contacts = [
            # forwardable: opportunity stage
            {"id": "1", "properties": {
                "firstname": "Jane", "lastname": "Doe",
                "email": "jane.doe@energy.gov",
                "lifecyclestage": "opportunity",
            }},
            # not forwardable: subscriber (newsletter signup, not customer-side)
            {"id": "2", "properties": {
                "firstname": "Spam", "lastname": "User",
                "email": "spam@x.com",
                "lifecyclestage": "subscriber",
            }},
            # not forwardable: hyperscaler-contact (AWS-side, not customer)
            {"id": "3", "properties": {
                "firstname": "PDM", "lastname": "Person",
                "email": "pdm@amazon.com",
                "hs_lead_status": "HYPERSCALER_CONTACT",
            }},
        ]
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok", contacts=contacts,
        )
        out = payload["Customer"]["Contacts"]
        assert len(out) == 1
        assert out[0]["Email"] == "jane.doe@energy.gov"

    def test_state_full_name_normalized_to_aws_enum(self, deal, app_config):
        """HubSpot stores 'District of Columbia' (full name) but AWS's
        enum requires 'Dist. of Columbia'."""
        company = {"id": "c1", "properties": {
            "name": "X", "country": "US", "state": "District of Columbia",
        }}
        payload = map_hubspot_deal_to_ace_create_payload(
            deal, app_config, client_token="tok", company=company,
        )
        assert (
            payload["Customer"]["Account"]["Address"]["StateOrRegion"]
            == "Dist. of Columbia"
        )
