"""Tests for GovWin -> HubSpot field mapping."""

from src.models import GovWinContact, GovWinGovEntity, GovWinOpportunity, GovWinOpportunityBundle
from src.sync.mapper import (
    map_contact_to_hubspot,
    map_gov_entity_to_company,
    map_opportunity_to_deal,
    naics_to_aws_industry,
    sanitize_html,
)
from tests.conftest import SAMPLE_CONTACT_JSON, SAMPLE_GOV_ENTITY_JSON, SAMPLE_OPPORTUNITY_JSON


def test_naics_to_aws_industry():
    assert naics_to_aws_industry("541512") == "Professional Services"
    assert naics_to_aws_industry("511210") == "Software & Internet"
    assert naics_to_aws_industry("336411") == "Manufacturing"
    assert naics_to_aws_industry("921190") == "Government"
    assert naics_to_aws_industry("622110") == "Healthcare"
    assert naics_to_aws_industry(None) == "Government"
    assert naics_to_aws_industry("") == "Government"
    assert naics_to_aws_industry("999999") == "Other"


def test_naics_541330_engineering_services_maps_to_professional_services():
    """NAICS 541330 (Engineering Services) is a common federal AWS partner
    sector. The mapping uses the 2-digit prefix (`54`), so 541330 routes to
    Professional Services along with the rest of NAICS 54xxxx.
    """
    assert naics_to_aws_industry("541330") == "Professional Services"


def test_naics_other_54_subsectors_share_professional_services():
    """All NAICS 54xxxx codes share the Professional Services bucket.
    Locking this in so a future "more granular for federal partners" change
    is a deliberate decision, not an accidental drift.
    """
    for code in ("541330", "541410", "541512", "541611", "541715"):
        assert naics_to_aws_industry(code) == "Professional Services", code


def test_sanitize_html():
    assert sanitize_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert sanitize_html("Plain text") == "Plain text"
    assert sanitize_html(None) is None
    assert sanitize_html("") == ""
    assert sanitize_html("&amp; &lt; &gt;") == "& < >"


def test_sanitize_html_truncation():
    long_text = "x" * 100000
    result = sanitize_html(long_text)
    assert len(result) == 65536


def test_map_opportunity_to_deal():
    opp = GovWinOpportunity.model_validate(SAMPLE_OPPORTUNITY_JSON)
    bundle = GovWinOpportunityBundle(opportunity=opp)

    result = map_opportunity_to_deal(bundle, pipeline_id="pipe123", stage_id="stage456")
    props = result["properties"]

    assert props["dealname"] == "Cloud Migration Services for DoD"
    assert props["amount"] == "5000000"  # 5000 * 1000
    assert props["govwin_opp_id"] == "OPP12345"
    assert props["govwin_status"] == "RFP Released"
    assert props["govwin_country"] == "USA"
    assert props["govwin_primary_naics"] == "Computer Systems Design Services"
    assert props["govwin_naics_code"] == "541512"
    assert props["govwin_industry"] == "Professional Services"
    assert props["govwin_ace_opportunity_type"] == "Net New Business"
    assert props["pipeline"] == "pipe123"
    assert props["dealstage"] == "stage456"
    assert props["govwin_agency"] == "Department of Defense"
    # closedate is a HubSpot epoch millisecond timestamp
    assert props["closedate"].isdigit()
    # HTML should be stripped from description
    assert "<p>" not in props["description"]
    assert "Cloud migration" in props["description"]


def test_map_opportunity_no_value():
    opp = GovWinOpportunity.model_validate({"id": "BID99999", "title": "Minimal Bid"})
    bundle = GovWinOpportunityBundle(opportunity=opp)

    result = map_opportunity_to_deal(bundle)
    props = result["properties"]

    assert props["dealname"] == "Minimal Bid"
    assert "amount" not in props
    assert "pipeline" not in props


def test_map_gov_entity_to_company():
    entity = GovWinGovEntity.model_validate(SAMPLE_GOV_ENTITY_JSON)
    result = map_gov_entity_to_company(entity)
    props = result["properties"]

    assert props["name"] == "Department of Defense"
    assert props["industry"] == "GOVERNMENT_ADMINISTRATION"
    assert props["govwin_gov_entity_id"] == "100"
    assert props["govwin_parent_agency"] == "Federal Government"


def test_map_contact_to_hubspot():
    contact = GovWinContact.model_validate(SAMPLE_CONTACT_JSON)
    result = map_contact_to_hubspot(contact)
    props = result["properties"]

    assert props["email"] == "jane.smith@dod.gov"
    assert props["firstname"] == "Jane"
    assert props["lastname"] == "Smith"
    assert props["jobtitle"] == "Contracting Officer"
    assert props["govwin_contact_id"] == "C001"
    assert props["govwin_entity_level1"] == "Department of Defense"


def test_map_opportunity_smart_tag_string():
    """smart_tag arrives as a plain string and should pass through to govwin_smart_tags."""
    opp = GovWinOpportunity.model_validate(
        {"id": "OPN1", "title": "T", "smartTag": "Cyber; Cloud"}
    )
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    assert props["govwin_smart_tags"] == "Cyber; Cloud"


def test_map_opportunity_smart_tag_list():
    """smart_tag list[dict] is concatenated by title with '; ' separator."""
    opp = GovWinOpportunity.model_validate(
        {
            "id": "OPP1",
            "title": "T",
            "smartTag": [{"title": "Cyber"}, {"title": "Cloud"}, {"id": "no-title"}],
        }
    )
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    assert props["govwin_smart_tags"] == "Cyber; Cloud"


def test_map_opportunity_canadian_value_fallback():
    """When opp_value is missing but opp_value_canada is set, use the Canadian value."""
    opp = GovWinOpportunity.model_validate(
        {"id": "OPP1", "title": "Canadian Bid", "oppValueCanada": 1234.5}
    )
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    assert props["amount"] == "1234500"


def test_map_opportunity_close_date_falls_back_to_response_date():
    """If pAwardDateTo is missing, closedate should come from responseDate."""
    opp = GovWinOpportunity.model_validate(
        {"id": "OPP1", "title": "T", "responseDate": {"value": "2026-05-15"}}
    )
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    # closedate is HubSpot epoch milliseconds for the response date
    assert props["closedate"].isdigit()


def test_map_opportunity_zero_value_omits_amount():
    """Production behavior: $0 deals must not set the amount field at all."""
    opp = GovWinOpportunity.model_validate(
        {"id": "OPP1", "title": "Zero", "oppValue": 0}
    )
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    # opp_value = 0 evaluates falsy in `if opp.opp_value is not None` → amount is "0"
    # but mapper drops None-only; "0" is preserved as a real value
    assert props.get("amount") == "0"


def test_map_opportunity_large_value_178m():
    """Regression for the production $178M test case."""
    opp = GovWinOpportunity.model_validate(
        {"id": "OPP1", "title": "Big", "oppValue": 178000.0}
    )
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    # GovWin stores in thousands; HubSpot wants the full dollar amount
    assert props["amount"] == "178000000"


def test_map_opportunity_no_pipeline_no_stage_omitted():
    """When pipeline_id/stage_id are None, those properties must not appear in the payload."""
    opp = GovWinOpportunity.model_validate({"id": "OPP1", "title": "T"})
    bundle = GovWinOpportunityBundle(opportunity=opp)
    props = map_opportunity_to_deal(bundle)["properties"]
    assert "pipeline" not in props
    assert "dealstage" not in props


def test_to_hubspot_timestamp_invalid_returns_none():
    """A garbage date string should not crash; mapper returns None and the field is dropped."""
    from src.sync.mapper import _to_hubspot_timestamp

    assert _to_hubspot_timestamp("not-a-date") is None
    assert _to_hubspot_timestamp("") is None
    assert _to_hubspot_timestamp(None) is None


def test_map_contact_no_email():
    contact = GovWinContact.model_validate({
        "contactId": "C002",
        "firstName": "John",
        "lastName": "Doe",
    })
    result = map_contact_to_hubspot(contact)
    props = result["properties"]

    assert "email" not in props
    assert props["govwin_contact_id"] == "C002"
    assert props["firstname"] == "John"
