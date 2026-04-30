"""React to inbound EventBridge events from ``aws.partnercentral-selling``.

Per the AWS reference, event payloads carry only IDs in ``detail.opportunity``
and ``detail.engagementInvitation``. The handler resolves those to the local
HubSpot deal via ``PartnerOpportunityIdentifier`` (which our CreateOpportunity
populated with the GovWin opp ID) and updates the deal stage accordingly.

Idempotency: each event id is recorded atomically via
``mark_event_seen_atomic`` on first sighting; concurrent retries see the
existing record and return early.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.ace.client import ACEAPIError, ACEClient
from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# AWS review status -> HubSpot stage label. The label values are looked up
# at runtime via get_stage_id_by_label so deployments can rename or
# re-create stages without touching code; only the labels matter.
_DEALSTAGE_BY_AWS_REVIEW: dict[str, str] = {
    "Approved": "Approved by AWS",
    "Action Required": "Action Required",
    "Rejected": "Closed Lost",
    "Expired": "Closed Lost",
}


def _update_hubspot_stage(
    hubspot: HubSpotClient, deal_id: str, target_label: str
) -> bool:
    """Resolve a stage label to its pipeline ID and patch the deal.

    Returns False if the label is not present in the configured pipeline.
    """
    stage_id = hubspot.get_stage_id_by_label(target_label)
    if not stage_id:
        logger.warning(
            "handle_ace_event: stage label %r not in pipeline; skipping update of %s",
            target_label,
            deal_id,
        )
        return False
    hubspot.update_deal(deal_id, {"dealstage": stage_id})
    return True


def _handle_opportunity_event(
    detail: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    """Opportunity Created / Updated.

    Detail carries only ``opportunity.identifier`` (the AWS Id). We must
    GetOpportunity to recover ``PartnerOpportunityIdentifier`` (our GovWin
    id) and the current ``LifeCycle.ReviewStatus``.
    """
    opp = detail.get("opportunity") or {}
    aws_id = opp.get("identifier")
    if not aws_id:
        return {"status": "skipped", "reason": "no opportunity.identifier"}
    try:
        full = ace.get_opportunity(str(aws_id))
    except ACEAPIError as exc:
        logger.warning("get_opportunity %s failed: %s", aws_id, exc)
        return {"status": "skipped", "reason": f"get_opportunity {exc.code}"}

    partner_id = full.get("PartnerOpportunityIdentifier")
    if not partner_id:
        return {"status": "skipped", "reason": "no PartnerOpportunityIdentifier on opportunity"}
    mapping = state.get_ace_mapping(str(partner_id)) or {}
    deal_id = mapping.get("hubspot_deal_id")
    if not deal_id:
        return {"status": "skipped", "reason": "no hubspot deal mapping"}

    review_status = (full.get("LifeCycle") or {}).get("ReviewStatus")
    target_stage = _DEALSTAGE_BY_AWS_REVIEW.get(str(review_status or ""))
    if not target_stage:
        return {"status": "skipped", "reason": f"no mapping for {review_status}"}
    if not _update_hubspot_stage(hubspot, str(deal_id), target_stage):
        return {"status": "skipped", "reason": "stage missing in pipeline"}

    last_modified = full.get("LastModifiedDate")
    state.update_ace_mapping(
        govwin_id=str(partner_id),
        last_modified_date=str(last_modified) if last_modified else None,
    )
    return {"status": "updated", "deal_id": deal_id, "stage": target_stage}


def _handle_invitation_event(
    detail_type: str,
    detail: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    invitation = detail.get("engagementInvitation") or {}
    invitation_id = invitation.get("id")
    if not invitation_id:
        return {"status": "skipped", "reason": "no engagementInvitation.id"}

    if detail_type == "Engagement Invitation Created":
        # Receiver-side referrals from AWS: we don't auto-create the deal in
        # v1 (BD approval in HubSpot is required first). Notify via log; the
        # Phase 4 referral handler will pick this up.
        if invitation.get("participantType") == "Receiver":
            logger.info(
                "ace.invitation.created.receiver invitation_id=%s engagementId=%s",
                invitation_id,
                invitation.get("engagementId"),
            )
        return {"status": "logged", "invitation_id": invitation_id}

    if detail_type == "Engagement Invitation Accepted":
        target_stage = "Approved by AWS"
    elif detail_type in {"Engagement Invitation Rejected", "Engagement Invitation Expired"}:
        target_stage = "Closed Lost"
    else:
        return {"status": "skipped", "reason": f"unhandled detail-type {detail_type}"}

    # Resolve invitation_id -> partner_id by scanning recent ACE mappings via
    # the engagement_invitation_id we persisted at submit time. v1 does this
    # via a get_opportunity round-trip from any associated opportunity.
    try:
        # AWS does not return the opportunity from the invitation event, so
        # we query our own DynamoDB by the invitation id we stored.
        partner_id = state.find_govwin_by_invitation_id(str(invitation_id))
    except Exception:  # noqa: BLE001 -- defensive, lookup is best-effort
        logger.exception("invitation lookup failed for %s", invitation_id)
        partner_id = None
    if not partner_id:
        return {"status": "skipped", "reason": "no mapping for invitation"}
    mapping = state.get_ace_mapping(partner_id) or {}
    deal_id = mapping.get("hubspot_deal_id")
    if not deal_id:
        return {"status": "skipped", "reason": "no hubspot deal mapping"}
    if not _update_hubspot_stage(hubspot, str(deal_id), target_stage):
        return {"status": "skipped", "reason": "stage missing in pipeline"}
    return {"status": "updated", "deal_id": deal_id, "stage": target_stage}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config()
    state = SyncStateManager(config)
    event_id = str(event.get("id") or "")
    detail_type = str(event.get("detail-type") or "")
    logger.info(
        "handle_ace_event.received id=%s detail-type=%s source=%s",
        event_id,
        detail_type,
        event.get("source"),
    )
    if event_id and not state.mark_event_seen_atomic(
        event_id, ttl_seconds=config.ace.event_dedup_ttl_seconds
    ):
        logger.info("handle_ace_event: dedup hit for %s", event_id)
        return {"status": "duplicate", "event_id": event_id}

    detail = event.get("detail") or {}
    ace = ACEClient(config)

    with HubSpotClient(config) as hubspot:
        if detail_type in {"Opportunity Created", "Opportunity Updated"}:
            result = _handle_opportunity_event(
                detail, state=state, ace=ace, hubspot=hubspot
            )
        elif detail_type.startswith("Engagement Invitation"):
            result = _handle_invitation_event(
                detail_type, detail, state=state, ace=ace, hubspot=hubspot
            )
        else:
            result = {"status": "skipped", "reason": f"unhandled detail-type {detail_type}"}
    logger.info("handle_ace_event.result %s", result)
    return result
