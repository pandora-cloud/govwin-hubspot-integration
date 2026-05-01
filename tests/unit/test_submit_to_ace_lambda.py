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
    """Test deal with a per-deal Solution override so the three-call flow
    (including AssociateOpportunity) runs regardless of catalog."""
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
            "govwin_ace_solution_id": "S-0051246",
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
    # The new associated-record reads (Company / Contacts / Owner) default
    # to "no association" so the mapper falls back to deal-level GovWin
    # values. Tests that need rich associated data override these.
    hubspot.get_associated_company.return_value = None
    hubspot.get_associated_contacts.return_value = []
    hubspot.get_owner.return_value = None

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


def test_invalid_json_body_dropped_not_retried() -> None:
    """Invalid JSON is a permanent error; do not loop the message via SQS."""
    event = {"Records": [{"messageId": "bad", "body": "{not json"}]}
    ace, state, hubspot = _patches({})
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event, context=None)
    assert result["batchItemFailures"] == []


def test_resume_from_engagement_skips_all_three_calls(event_factory, deal_payload) -> None:
    """Already-engaged deal should be a no-op clean replay."""
    ace, state, hubspot = _patches(deal_payload)
    state.get_ace_mapping.return_value = {
        "ace_opportunity_id": "O-DONE",
        "ace_task_id": "T-DONE",
        "ace_engagement_invitation_id": "EI-DONE",
        "last_modified_date": "2026-04-29T00:00:00Z",
        "client_token": "tok-old",
    }
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    assert ace.create_opportunity.call_count == 0
    assert ace.associate_opportunity.call_count == 0
    assert ace.start_engagement_from_opportunity_task.call_count == 0
    assert result["results"][0]["status"] == "submitted"


def test_permanent_validation_error_is_dropped(event_factory, deal_payload) -> None:
    from src.ace.client import ACEAPIError

    ace, state, hubspot = _patches(deal_payload)
    ace.create_opportunity.side_effect = ACEAPIError("bad", code="ValidationException")
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    # Permanent errors must not be retried via SQS.
    assert result["batchItemFailures"] == []


def test_transient_throttling_is_retried(event_factory, deal_payload) -> None:
    from src.ace.client import ACEAPIError

    ace, state, hubspot = _patches(deal_payload)
    ace.create_opportunity.side_effect = ACEAPIError("slow", code="ThrottlingException")
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(event_factory(), context=None)
    assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]


def test_invalid_objectid_skipped(event_factory, deal_payload) -> None:
    ace, state, hubspot = _patches(deal_payload)
    bad_event = {
        "Records": [
            {
                "messageId": "m1",
                "body": json.dumps({
                    "objectId": "../etc/passwd",
                    "subscriptionType": "object.propertyChange",
                    "propertyName": "dealstage",
                    "propertyValue": "submit_to_aws",
                }),
            }
        ]
    }
    with patch.object(submit_to_ace, "ACEClient", return_value=ace), \
         patch.object(submit_to_ace, "SyncStateManager", return_value=state), \
         patch.object(submit_to_ace, "HubSpotClient", return_value=hubspot):
        result = submit_to_ace.handler(bad_event, context=None)
    assert result["results"][0]["status"] == "skipped"


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
