"""Tests for the submit_to_ace SQS-driven Lambda."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.lambdas import submit_to_ace


@pytest.fixture(autouse=True)
def _ace_env(monkeypatch):
    monkeypatch.setenv("ACE_CATALOG", "Sandbox")
    monkeypatch.setenv("ACE_DEFAULT_SOLUTION_ID", "S-0051246")
    monkeypatch.setenv("ACE_TRIGGER_STAGES", "submit_to_aws,submitted_to_aws")


@pytest.fixture
def event_factory():
    def _make(property_value: str = "submit_to_aws", deal_id: str = "12345") -> dict:
        body = {
            "objectId": int(deal_id),
            "subscriptionType": "object.propertyChange",
            "propertyName": "dealstage",
            "propertyValue": property_value,
        }
        return {"Records": [{"messageId": "m1", "body": json.dumps(body)}]}

    return _make


@pytest.fixture
def deal_payload() -> dict:
    return {
        "id": "12345",
        "properties": {
            "dealname": "DoD Cloud",
            "amount": "100000",
            "closedate": "2026-12-31",
            "govwin_opp_id": "OPP001",
            "govwin_agency": "DoD",
            "govwin_industry": "Government",
            "govwin_ace_partner_need": "Co-Sell - Technical Consultation",
            "govwin_ace_delivery_model": "Professional Services",
        },
    }


def _patches(deal_payload: dict, ace_responses: dict | None = None):
    """Build the standard patch stack for submit_to_ace.handler."""
    ace = MagicMock()
    ace.create_opportunity.return_value = (
        ace_responses or {}
    ).get("create", {"Id": "O-NEW", "LastModifiedDate": "2026-04-29T00:00:00Z"})
    ace.start_engagement_from_opportunity_task.return_value = (
        ace_responses or {}
    ).get("start", {"TaskId": "T1", "EngagementInvitationId": "EI1"})

    state = MagicMock()
    state.get_ace_mapping.return_value = None
    state.reserve_client_token.return_value = "tok-uuid"

    hubspot = MagicMock()
    hubspot.__enter__.return_value = hubspot
    hubspot.__exit__.return_value = False
    hubspot.get_deal.return_value = deal_payload

    return ace, state, hubspot


def test_submit_runs_three_call_flow(event_factory, deal_payload) -> None:
    ace, state, hubspot = _patches(deal_payload)
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    assert ace.create_opportunity.call_count == 1
    assert ace.associate_opportunity.call_count == 1
    assert ace.start_engagement_from_opportunity_task.call_count == 1
    assert result["results"][0]["status"] == "submitted"
    assert result["batchItemFailures"] == []


def test_skips_when_dealstage_not_in_trigger_list(event_factory, deal_payload) -> None:
    ace, state, hubspot = _patches(deal_payload)
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        event = event_factory(property_value="appointmentscheduled")
        result = submit_to_ace.handler(event, context=None)
    assert result["results"][0]["status"] == "skipped"
    assert ace.create_opportunity.call_count == 0


def test_resumes_when_opportunity_already_created(event_factory, deal_payload) -> None:
    ace, state, hubspot = _patches(deal_payload)
    state.get_ace_mapping.return_value = {
        "ace_opportunity_id": "O-EXISTING",
        "last_modified_date": "2026-04-28T00:00:00Z",
    }
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        submit_to_ace.handler(event_factory(), context=None)
    # Should NOT recreate, but should still associate + start engagement
    assert ace.create_opportunity.call_count == 0
    assert ace.associate_opportunity.call_count == 1
    assert ace.start_engagement_from_opportunity_task.call_count == 1


def test_skips_when_govwin_id_missing(event_factory) -> None:
    ace, state, hubspot = _patches({"id": "1", "properties": {"dealname": "x"}})
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    assert result["results"][0]["status"] == "skipped"
    assert ace.create_opportunity.call_count == 0


def test_failure_records_batch_item_failure(event_factory, deal_payload) -> None:
    ace, state, hubspot = _patches(deal_payload)
    ace.create_opportunity.side_effect = RuntimeError("boom")
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]


def test_invalid_json_body_records_failure() -> None:
    event = {"Records": [{"messageId": "bad", "body": "{not json"}]}
    ace, state, hubspot = _patches({})
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event, context=None)
    assert result["batchItemFailures"] == [{"itemIdentifier": "bad"}]


def test_associate_conflict_is_treated_as_success(event_factory, deal_payload) -> None:
    from src.ace.client import ACEAPIError

    ace, state, hubspot = _patches(deal_payload)
    ace.associate_opportunity.side_effect = ACEAPIError("dup", code="ConflictException")
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    assert result["results"][0]["status"] == "submitted"
    assert ace.start_engagement_from_opportunity_task.call_count == 1
