"""Tests for the EventBridge-driven ACE event handler Lambda."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.lambdas import handle_ace_event


@pytest.fixture
def state_mock() -> MagicMock:
    state = MagicMock()
    state.mark_event_seen_atomic.return_value = True  # first sighting
    state.get_ace_mapping.return_value = {
        "hubspot_deal_id": "deal-1",
        "ace_opportunity_id": "O1",
    }
    state.find_govwin_by_invitation_id.return_value = "OPP1"
    return state


@pytest.fixture
def ace_mock() -> MagicMock:
    ace = MagicMock()
    ace.get_opportunity.return_value = {
        "Id": "O1",
        "PartnerOpportunityIdentifier": "OPP1",
        "LifeCycle": {"ReviewStatus": "Approved"},
        "LastModifiedDate": "2026-04-29T00:00:00Z",
    }
    return ace


@pytest.fixture
def hubspot_mock() -> MagicMock:
    hs = MagicMock()
    hs.__enter__.return_value = hs
    hs.__exit__.return_value = False
    hs.get_stage_id_by_label.return_value = "stage-id-123"
    # Default: deal is active (not archived). Tests that need the
    # archived path override this on the fixture.
    hs.is_deal_archived.return_value = False
    return hs


def _opportunity_event(aws_id: str = "O1", event_id: str = "e1") -> dict:
    return {
        "id": event_id,
        "detail-type": "Opportunity Updated",
        "source": "aws.partnercentral-selling",
        "detail": {
            "schemaVersion": "1.0",
            "catalog": "AWS",
            "opportunity": {"identifier": aws_id},
        },
    }


def _invitation_event(
    detail_type: str,
    invitation_id: str = "engi-1",
    participant: str = "Sender",
) -> dict:
    return {
        "id": "ev-inv-1",
        "detail-type": detail_type,
        "source": "aws.partnercentral-selling",
        "detail": {
            "catalog": "AWS",
            "engagementInvitation": {
                "id": invitation_id,
                "engagementId": "eng-1",
                "participantType": participant,
                "payloadType": "OpportunityInvitation",
            },
        },
    }


def test_opportunity_updated_with_approved_status(state_mock, ace_mock, hubspot_mock) -> None:
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "updated"
    assert result["stage"] == "Approved by AWS"
    ace_mock.get_opportunity.assert_called_once_with("O1")
    # Two update_deal calls now: write-back of cosell_id + status, then dealstage.
    assert hubspot_mock.update_deal.call_count == 2
    writeback = hubspot_mock.update_deal.call_args_list[0]
    assert writeback.args[1]["govwin_aws_cosell_id"] == "O1"
    assert writeback.args[1]["govwin_aws_cosell_status"] == "Approved"


def test_opportunity_updated_skips_when_no_partner_id(state_mock, ace_mock, hubspot_mock) -> None:
    ace_mock.get_opportunity.return_value = {"Id": "O1"}
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "skipped"


def test_opportunity_updated_skips_when_review_status_unmapped(
    state_mock, ace_mock, hubspot_mock
) -> None:
    """ReviewStatus 'Pending Submission' is the initial state after Create
    and is intentionally not mapped to a HubSpot stage transition. The
    handler reports it as a 'no-op' (vs 'skipped') so an operator scanning
    CloudWatch can distinguish the expected initial-create case from a
    real mapping miss."""
    ace_mock.get_opportunity.return_value = {
        "PartnerOpportunityIdentifier": "OPP1",
        "LifeCycle": {"ReviewStatus": "Pending Submission"},
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "no-op"
    assert "Pending Submission" in result["reason"]
    # The write-back path still runs (and surfaces 'Pending Submission' on
    # the deal) even though no stage change happens.
    hubspot_mock.update_deal.assert_called_once()
    assert (
        hubspot_mock.update_deal.call_args.args[1]["govwin_aws_cosell_status"]
        == "Pending Submission"
    )


def test_opportunity_updated_routes_submitted_to_aws(
    state_mock, ace_mock, hubspot_mock
) -> None:
    """Submitted is the AWS-side status right after StartEngagement; should
    route to the 'Submitted to AWS' HubSpot stage label."""
    ace_mock.get_opportunity.return_value = {
        "PartnerOpportunityIdentifier": "OPP1",
        "LifeCycle": {"ReviewStatus": "Submitted"},
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "updated"
    assert result["stage"] == "Submitted to AWS"


def test_opportunity_updated_routes_in_review_lowercase(
    state_mock, ace_mock, hubspot_mock
) -> None:
    """boto3 enum uses 'In review' (lowercase 'r'); confirm key matches."""
    ace_mock.get_opportunity.return_value = {
        "PartnerOpportunityIdentifier": "OPP1",
        "LifeCycle": {"ReviewStatus": "In review"},
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "updated"
    assert result["stage"] == "Under AWS Review"


def test_invitation_accepted_updates_stage(state_mock, ace_mock, hubspot_mock) -> None:
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(
            _invitation_event("Engagement Invitation Accepted"), context=None
        )
    assert result["status"] == "updated"
    assert result["stage"] == "Approved by AWS"


def test_invitation_rejected_moves_to_closed_lost(state_mock, ace_mock, hubspot_mock) -> None:
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(
            _invitation_event("Engagement Invitation Rejected"), context=None
        )
    assert result["stage"] == "Closed Lost"


def test_invitation_created_receiver_is_logged_only(state_mock, ace_mock, hubspot_mock) -> None:
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(
            _invitation_event("Engagement Invitation Created", participant="Receiver"),
            context=None,
        )
    assert result["status"] == "logged"
    hubspot_mock.update_deal.assert_not_called()


def test_dedup_short_circuits_processing(state_mock, ace_mock, hubspot_mock) -> None:
    state_mock.mark_event_seen_atomic.return_value = False  # already-seen
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "duplicate"
    ace_mock.get_opportunity.assert_not_called()
    hubspot_mock.update_deal.assert_not_called()


def test_unmapped_partner_opportunity_skipped(state_mock, ace_mock, hubspot_mock) -> None:
    state_mock.get_ace_mapping.return_value = None
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "skipped"
    hubspot_mock.update_deal.assert_not_called()


def test_unhandled_detail_type_skipped(state_mock, ace_mock, hubspot_mock) -> None:
    event = {
        "id": "ev-x",
        "detail-type": "Engagement Member Added",
        "source": "aws.partnercentral-selling",
        "detail": {},
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(event, context=None)
    assert result["status"] == "skipped"


def test_invitation_without_mapping_skipped(state_mock, ace_mock, hubspot_mock) -> None:
    state_mock.find_govwin_by_invitation_id.return_value = None
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(
            _invitation_event("Engagement Invitation Accepted"), context=None
        )
    assert result["status"] == "skipped"


def test_stage_label_missing_in_pipeline_warns_and_skips(
    state_mock, ace_mock, hubspot_mock
) -> None:
    hubspot_mock.get_stage_id_by_label.return_value = None
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "skipped"
    # Write-back still runs even when the stage label can't be resolved.
    # update_deal called once for the write-back, never for dealstage.
    assert hubspot_mock.update_deal.call_count == 1
    assert "dealstage" not in hubspot_mock.update_deal.call_args.args[1]


def test_archived_deal_is_skipped_no_alert(
    state_mock, ace_mock, hubspot_mock, caplog
) -> None:
    """An EventBridge event for a HubSpot-archived deal must be a clean
    no-op: no update_deal call, no SNS-worthy log level, no exception. The
    BD team has dispositioned the deal in HubSpot; further AWS-side state
    changes are expected to be ignored.
    """
    hubspot_mock.is_deal_archived.return_value = True
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        with caplog.at_level("INFO"):
            result = handle_ace_event.handler(_opportunity_event(), context=None)
    assert result["status"] == "skipped"
    assert result["reason"] == "deal archived in HubSpot"
    hubspot_mock.update_deal.assert_not_called()
    # is_deal_archived is now consulted twice: once by the AWS write-back
    # pre-flight (which short-circuits the cosell_id/status patch) and once
    # by _update_hubspot_stage. Both must see the archived state.
    assert hubspot_mock.is_deal_archived.call_count >= 1
    # Nothing higher than INFO should fire -- this is an expected end-state.
    high_severity = [r for r in caplog.records if r.levelno >= 30]
    assert not high_severity, (
        f"unexpected WARNING/ERROR for archived deal: "
        f"{[r.message for r in high_severity]}"
    )


def test_archived_deal_skipped_for_invitation_events_too(
    state_mock, ace_mock, hubspot_mock
) -> None:
    """Same archived-deal short-circuit applies to invitation lifecycle
    events, not just Opportunity Updated."""
    hubspot_mock.is_deal_archived.return_value = True
    state_mock.find_govwin_by_invitation_id.return_value = "OPP1"
    state_mock.get_ace_mapping.return_value = {"hubspot_deal_id": "deal123"}
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        result = handle_ace_event.handler(
            _invitation_event("Engagement Invitation Accepted"), context=None
        )
    assert result["status"] == "skipped"
    assert "archived" in result["reason"]
    hubspot_mock.update_deal.assert_not_called()
