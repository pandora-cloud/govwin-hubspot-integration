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
