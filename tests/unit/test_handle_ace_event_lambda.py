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
    # Default: no existing HubSpot contact with the same email -- safe
    # to upsert. Tests that exercise the existing-contact protection
    # override this on the fixture.
    hs.find_contact_by_email.return_value = None
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
    # Unified PATCH: cosell_id + status + dealstage all sent in one call.
    hubspot_mock.update_deal.assert_called_once()
    body = hubspot_mock.update_deal.call_args.args[1]
    assert body["govwin_aws_cosell_id"] == "O1"
    assert body["govwin_aws_cosell_status"] == "Approved"
    assert body["dealstage"] == "stage-id-123"


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
    # Unified write-back: status is set on the deal even though no stage
    # change happens. Single PATCH carries cosell_id + status only.
    hubspot_mock.update_deal.assert_called_once()
    body = hubspot_mock.update_deal.call_args.args[1]
    assert body["govwin_aws_cosell_status"] == "Pending Submission"
    assert "dealstage" not in body


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
    # Unified write-back: when the stage label doesn't resolve, dealstage
    # is omitted from the PATCH but cosell_id + status still update.
    hubspot_mock.update_deal.assert_called_once()
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


def test_hyperscaler_contact_rejects_non_aws_email_domain(
    state_mock, ace_mock, hubspot_mock, caplog
) -> None:
    """CRITICAL fix: an EngagementInvitation event carrying an email
    outside the AWS allowlist must NOT trigger upsert_contact. Otherwise
    AWS-supplied data could clobber a real customer-side contact in
    HubSpot."""
    invitation = {
        "id": "inv-1",
        "engagementId": "eng-1",
        "participantType": "Sender",
        "invitationContacts": [
            {"email": "isi@pandoracloud.net", "firstName": "Isi", "lastName": "L"},
            {"email": "rogue@evil.example", "firstName": "X", "lastName": "Y"},
        ],
    }
    state_mock.find_govwin_by_invitation_id.return_value = "OPP1"
    state_mock.get_ace_mapping.return_value = {"hubspot_deal_id": "deal-1"}
    hubspot_mock.get_associated_company.return_value = {"id": "co-1"}
    event = {
        "id": "ev-inv",
        "detail-type": "Engagement Invitation Created",
        "source": "aws.partnercentral-selling",
        "detail": {
            "catalog": "AWS",
            "engagementInvitation": invitation,
        },
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        with caplog.at_level("WARNING"):
            handle_ace_event.handler(event, context=None)
    # Neither non-AWS email triggered upsert.
    hubspot_mock.upsert_contact.assert_not_called()
    # Both rejections logged at WARNING level for audit visibility.
    rejection_msgs = [r.message for r in caplog.records if "domain not in allowlist" in r.message]
    assert len(rejection_msgs) == 2


def test_hyperscaler_contact_skips_overwrite_of_real_existing_contact(
    state_mock, ace_mock, hubspot_mock
) -> None:
    """Even an aws.com / amazon.com email is NOT upserted onto an
    existing HubSpot contact that wasn't previously created by this
    Lambda. Only the deal/company association is added."""
    invitation = {
        "id": "inv-2", "engagementId": "eng-2", "participantType": "Sender",
        "invitationContacts": [{
            "email": "shared@amazon.com",
            "firstName": "AWS", "lastName": "Person",
        }],
    }
    state_mock.find_govwin_by_invitation_id.return_value = "OPP1"
    state_mock.get_ace_mapping.return_value = {"hubspot_deal_id": "deal-1"}
    hubspot_mock.get_associated_company.return_value = {"id": "co-1"}
    # Existing HubSpot contact NOT marked as hyperscaler.
    hubspot_mock.find_contact_by_email.return_value = {
        "id": "contact-99",
        "properties": {"email": "shared@amazon.com", "hs_lead_status": "OPEN"},
    }
    event = {
        "id": "ev-inv-2",
        "detail-type": "Engagement Invitation Created",
        "source": "aws.partnercentral-selling",
        "detail": {"catalog": "AWS", "engagementInvitation": invitation},
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        handle_ace_event.handler(event, context=None)
    # No upsert: real contact protected.
    hubspot_mock.upsert_contact.assert_not_called()
    # But association still made -- visibility for the AWS reviewer linkage.
    assert hubspot_mock.associate_objects.call_count >= 1


def test_hyperscaler_contact_email_masked_in_logs(
    state_mock, ace_mock, hubspot_mock, caplog
) -> None:
    invitation = {
        "id": "inv-3", "engagementId": "eng-3", "participantType": "Sender",
        "invitationContacts": [{"email": "evil@evil.example", "firstName": "X", "lastName": "Y"}],
    }
    state_mock.find_govwin_by_invitation_id.return_value = "OPP1"
    state_mock.get_ace_mapping.return_value = {"hubspot_deal_id": "deal-1"}
    hubspot_mock.get_associated_company.return_value = None
    event = {
        "id": "ev-inv-3",
        "detail-type": "Engagement Invitation Created",
        "source": "aws.partnercentral-selling",
        "detail": {"catalog": "AWS", "engagementInvitation": invitation},
    }
    with patch.object(handle_ace_event, "SyncStateManager", return_value=state_mock), \
         patch.object(handle_ace_event, "ACEClient", return_value=ace_mock), \
         patch.object(handle_ace_event, "HubSpotClient", return_value=hubspot_mock):
        with caplog.at_level("WARNING"):
            handle_ace_event.handler(event, context=None)
    log_text = " ".join(r.message for r in caplog.records)
    # Raw email never appears in logs; masked form does.
    assert "evil@evil.example" not in log_text
    assert "e***@evil.example" in log_text
