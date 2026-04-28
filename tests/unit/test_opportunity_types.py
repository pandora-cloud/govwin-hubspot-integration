"""Coverage for the six GovWin opportunity types: OPP, BID, TNS, FBO, OPN, TOP.

The model has had to absorb several real-world data quirks per type
(``smartTag`` as ``str`` for OPN, ``contract.company`` as ``list`` for OPP, etc.).
This test exercises a realistic minimal payload for each type through the full
parse + map pipeline so a model-shape regression for any type fails loudly here
rather than silently in production.
"""

from __future__ import annotations

import pytest

from src.models import GovWinOpportunity, GovWinOpportunityBundle
from src.sync.mapper import map_opportunity_to_deal

# Minimal-but-realistic payload per opportunity type. Each captures a quirk
# observed in production data that the integration must absorb.
TYPE_FIXTURES: dict[str, dict] = {
    "OPP": {
        "id": "OPP123456",
        "type": "trackedopp",
        "title": "OPP-type opportunity",
        "status": "Pre-RFP",
        "updateDate": "2026-04-01T00:00:00Z",
        "oppValue": 500.0,
        "primaryNAICS": {"id": "541512", "title": "Computer Systems Design"},
        "govEntity": {"id": 200, "title": "GSA"},
    },
    "BID": {
        "id": "BID789012",
        "type": "bid",
        "title": "BID-type solicitation",
        "status": "RFP Released",
        "updateDate": "2026-04-01T00:00:00Z",
        "solicitationNumber": "GS-35F-001",
    },
    "TNS": {
        "id": "TNS345678",
        "type": "tns",
        "title": "TNS-type opportunity",
        "status": "Pre-Solicitation",
        "updateDate": "2026-04-01T00:00:00Z",
    },
    "FBO": {
        "id": "FBO901234",
        "type": "fbo",
        "title": "FBO-type federal listing",
        "status": "RFP Released",
        "updateDate": "2026-04-01T00:00:00Z",
        "sourceURL": "https://sam.gov/opp/901234",
    },
    "OPN": {
        # Production case: smartTag returned as a plain string (OPN31627)
        "id": "OPN567890",
        "type": "opn",
        "title": "APFS Procurement Notice",
        "status": "Pre-RFP",
        "updateDate": "2026-04-01T00:00:00Z",
        "smartTag": "Cloud; Cybersecurity",
    },
    "TOP": {
        "id": "TOP135790",
        "type": "top",
        "title": "TOP-type task order opportunity",
        "status": "RFP Released",
        "updateDate": "2026-04-01T00:00:00Z",
    },
}


@pytest.mark.parametrize("opp_type,payload", list(TYPE_FIXTURES.items()))
def test_opportunity_type_parses_and_maps(opp_type: str, payload: dict):
    """Each opportunity type must validate and produce a non-empty deal payload."""
    opp = GovWinOpportunity.model_validate(payload)
    assert opp.id == payload["id"]

    bundle = GovWinOpportunityBundle(opportunity=opp)
    result = map_opportunity_to_deal(bundle)
    props = result["properties"]

    # Every type must produce these core fields
    assert props["dealname"] == payload["title"]
    assert props["govwin_id"] == payload["id"]
    assert props["govwin_opp_id"] == payload["id"]
    assert props["govwin_status"] == payload["status"]
    # ACE defaults always populated
    assert props["govwin_ace_opportunity_type"] == "Net New Business"
    assert "govwin_industry" in props
