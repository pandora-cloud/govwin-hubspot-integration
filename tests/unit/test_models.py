"""Tests for Pydantic data models."""

from src.models import (
    GovWinContact,
    GovWinGovEntity,
    GovWinOpportunity,
    GovWinOpportunityBundle,
)
from tests.conftest import SAMPLE_CONTACT_JSON, SAMPLE_GOV_ENTITY_JSON, SAMPLE_OPPORTUNITY_JSON


def test_opportunity_from_json():
    opp = GovWinOpportunity.model_validate(SAMPLE_OPPORTUNITY_JSON)
    assert opp.id == "OPP12345"
    assert opp.title == "Cloud Migration Services for DoD"
    assert opp.opp_value == 5000.0
    assert opp.gov_entity is not None
    assert opp.gov_entity.title == "Department of Defense"
    assert opp.primary_naics is not None
    assert opp.primary_naics.id == "541512"


def test_opportunity_handles_missing_fields():
    opp = GovWinOpportunity.model_validate({"id": "OPP99999", "title": "Minimal"})
    assert opp.id == "OPP99999"
    assert opp.opp_value is None
    assert opp.gov_entity is None
    assert opp.primary_naics is None


def test_contact_from_json():
    contact = GovWinContact.model_validate(SAMPLE_CONTACT_JSON)
    assert contact.first_name == "Jane"
    assert contact.last_name == "Smith"
    assert contact.email == "jane.smith@dod.gov"
    assert contact.gov_entity_level1 == "Department of Defense"


def test_gov_entity_from_json():
    entity = GovWinGovEntity.model_validate(SAMPLE_GOV_ENTITY_JSON)
    assert entity.id == 100
    assert entity.title == "Department of Defense"
    assert len(entity.parent_hierarchy) == 1


def test_opportunity_bundle():
    opp = GovWinOpportunity.model_validate(SAMPLE_OPPORTUNITY_JSON)
    contact = GovWinContact.model_validate(SAMPLE_CONTACT_JSON)
    GovWinGovEntity.model_validate(SAMPLE_GOV_ENTITY_JSON)

    bundle = GovWinOpportunityBundle(
        opportunity=opp,
        contacts=[contact],
        companies=[],
        contracts=[],
        places_of_performance=[],
    )
    assert bundle.opportunity.id == "OPP12345"
    assert len(bundle.contacts) == 1
    assert bundle.contacts[0].email == "jane.smith@dod.gov"


def test_opportunity_smart_tag_as_string():
    """Production fix (OPN31627): smartTag came back as a plain string instead of list[dict]."""
    from src.models import GovWinOpportunity

    opp = GovWinOpportunity.model_validate(
        {"id": "OPN31627", "title": "APFS Notice", "smartTag": "Cyber; Cloud"}
    )
    assert opp.smart_tag == "Cyber; Cloud"


def test_opportunity_smart_tag_as_list():
    from src.models import GovWinOpportunity

    opp = GovWinOpportunity.model_validate(
        {"id": "OPP1", "title": "Test", "smartTag": [{"title": "Cyber"}, {"title": "Cloud"}]}
    )
    assert isinstance(opp.smart_tag, list)
    assert opp.smart_tag[0]["title"] == "Cyber"


def test_contract_company_as_list():
    """Production fix (OPP261672): contract.company came back as a list of dicts."""
    from src.models import GovWinContract

    contract = GovWinContract.model_validate(
        {
            "contractId": "C-1",
            "company": [{"id": 1, "name": "ACME"}, {"id": 2, "name": "Beta"}],
        }
    )
    assert isinstance(contract.company, list)
    assert len(contract.company) == 2


def test_contract_incumbent_as_string():
    """Production fix: contract.incumbent came back as the string 'Yes' instead of bool."""
    from src.models import GovWinContract

    contract = GovWinContract.model_validate({"contractId": "C-1", "incumbent": "Yes"})
    assert contract.incumbent == "Yes"


def test_contract_id_as_int():
    """Production fix: contractId came back as an integer."""
    from src.models import GovWinContract

    contract = GovWinContract.model_validate({"contractId": 12345, "contractNumber": 999})
    assert contract.contract_id == 12345
    assert contract.contract_number == 999


def test_contact_id_as_int():
    """Production fix: contactId came back as an integer for some contacts."""
    contact = GovWinContact.model_validate({"contactId": 4242, "firstName": "X"})
    assert contact.contact_id == 4242


def test_links_contacts_as_dict():
    """Production fix: links.contacts came back as a dict {'href': ...} instead of a string."""
    from src.models import GovWinLinks

    links = GovWinLinks.model_validate(
        {"contacts": {"href": "https://services.govwin.com/.../contacts"}}
    )
    assert isinstance(links.contacts, dict)
    assert links.contacts["href"].endswith("/contacts")


def test_extra_fields_ignored():
    """Create a model with unknown fields and verify they are silently dropped (extra='ignore')."""
    opp = GovWinOpportunity.model_validate({
        "id": "OPP99999",
        "title": "Test",
        "unknown_field_xyz": "should be ignored",
        "another_extra": 12345,
    })
    assert opp.id == "OPP99999"
    assert opp.title == "Test"
    assert not hasattr(opp, "unknown_field_xyz")
    assert not hasattr(opp, "another_extra")

    contact = GovWinContact.model_validate({
        "contactId": "C999",
        "firstName": "Bob",
        "extraField": "ignored",
    })
    assert contact.contact_id == "C999"
    assert not hasattr(contact, "extraField")
