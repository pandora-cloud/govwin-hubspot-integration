"""Tests for the EventBridge-driven ACE event handler Lambda."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.lambdas import handle_ace_event


@pytest.fixture
def state_mock() -> MagicMock:
    state = MagicMock()
    state.is_event_seen.return_value = False
    state.get_ace_mapping.return_value = {
        "hubspot_deal_id": "deal-1",
        "ace_opportunity_id": "O1",
    }
    return state


@pytest.fixture
def hubspot_mock() -> MagicMock:
    hs = MagicMock()
    hs.__enter__.return_value = hs
    hs.__exit__.return_value = False
    hs.get_stage_id.return_value = "stage-id-123"
    return hs


def _event(detail_type: str, detail: dict, event_id: str = "e1") -> dict:
    return {
        "id": event_id,
        "detail-type": detail_type,
        "source": "aws.partnercentral-selling",
        "detail": detail,
    }


def test_opportunity_updated_with_approved_status(state_mock, hubspot_mock) -> None:
    event = _event(
        "Opportunity Updated",
        {"partnerOpportunityIdentifier": "OPP1", "reviewStatus": "Approved"},
    )
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["status"] == "updated"
    hubspot_mock.update_deal.assert_called_once()


def test_invitation_accepted_updates_stage(state_mock, hubspot_mock) -> None:
    event = _event(
        "Engagement Invitation Accepted",
        {"partnerOpportunityIdentifier": "OPP1"},
    )
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["status"] == "updated"
    assert result["stage"] == "approved_by_aws"


def test_invitation_rejected_moves_to_closed_lost(state_mock, hubspot_mock) -> None:
    event = _event(
        "Engagement Invitation Rejected",
        {"partnerOpportunityIdentifier": "OPP1"},
    )
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["stage"] == "closedlost"


def test_dedup_short_circuits_processing(state_mock, hubspot_mock) -> None:
    state_mock.is_event_seen.return_value = True
    event = _event("Opportunity Updated", {"partnerOpportunityIdentifier": "OPP1"})
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["status"] == "duplicate"
    hubspot_mock.update_deal.assert_not_called()


def test_event_marked_seen_after_processing(state_mock, hubspot_mock) -> None:
    event = _event(
        "Opportunity Updated",
        {"partnerOpportunityIdentifier": "OPP1", "reviewStatus": "Approved"},
    )
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        handle_ace_event.handler(event, context=None)
    state_mock.mark_event_seen.assert_called_once()


def test_unmapped_partner_opportunity_skipped(state_mock, hubspot_mock) -> None:
    state_mock.get_ace_mapping.return_value = None
    event = _event("Opportunity Updated", {"partnerOpportunityIdentifier": "ZZZ"})
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["status"] == "skipped"
    hubspot_mock.update_deal.assert_not_called()


def test_unhandled_detail_type_skipped(state_mock, hubspot_mock) -> None:
    event = _event("Some Unrelated Event", {})
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["status"] == "skipped"
