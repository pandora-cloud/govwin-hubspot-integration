"""React to inbound EventBridge events from ``aws.partnercentral-selling``.

Single Lambda dispatching by ``detail-type``:

* Opportunity Updated -> sync changes back into HubSpot.
* Engagement Invitation Created (Receiver) -> create a HubSpot deal.
* Engagement Invitation Accepted/Rejected/Expired -> move HubSpot stage.

Uses ``state.is_event_seen`` for at-least-once dedup with a 24h TTL.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_DEALSTAGE_BY_AWS_REVIEW: dict[str, str] = {
    "Approved": "approved_by_aws",
    "Action Required": "action_required",
    "Rejected": "closedlost",
    "Expired": "closedlost",
}


def _handle_opportunity_updated(
    detail: dict[str, Any],
    *,
    state: SyncStateManager,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    partner_id = detail.get("partnerOpportunityIdentifier")
    if not partner_id:
        return {"status": "skipped", "reason": "no partnerOpportunityIdentifier"}
    mapping = state.get_ace_mapping(str(partner_id)) or {}
    deal_id = mapping.get("hubspot_deal_id")
    if not deal_id:
        return {"status": "skipped", "reason": "no hubspot deal mapping"}
    review_status = detail.get("reviewStatus") or detail.get("ReviewStatus")
    target_stage = _DEALSTAGE_BY_AWS_REVIEW.get(str(review_status or ""))
    if not target_stage:
        return {"status": "skipped", "reason": f"no mapping for {review_status}"}
    stage_id = hubspot.get_stage_id(target_stage) or target_stage
    hubspot.update_deal(str(deal_id), {"dealstage": stage_id})
    return {"status": "updated", "deal_id": deal_id, "stage": target_stage}


def _handle_invitation_event(
    detail_type: str,
    detail: dict[str, Any],
    *,
    state: SyncStateManager,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    partner_id = detail.get("partnerOpportunityIdentifier")
    if not partner_id:
        return {"status": "skipped", "reason": "no partnerOpportunityIdentifier"}
    mapping = state.get_ace_mapping(str(partner_id)) or {}
    deal_id = mapping.get("hubspot_deal_id")
    if not deal_id:
        return {"status": "skipped", "reason": "no hubspot deal mapping"}

    if detail_type == "Engagement Invitation Accepted":
        target_stage = "approved_by_aws"
    elif detail_type in {"Engagement Invitation Rejected", "Engagement Invitation Expired"}:
        target_stage = "closedlost"
    else:
        return {"status": "skipped", "reason": f"unhandled detail-type {detail_type}"}

    stage_id = hubspot.get_stage_id(target_stage) or target_stage
    hubspot.update_deal(str(deal_id), {"dealstage": stage_id})
    return {"status": "updated", "deal_id": deal_id, "stage": target_stage}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config()
    state = SyncStateManager(config)
    event_id = str(event.get("id") or "")
    if event_id and state.is_event_seen(event_id):
        logger.info("handle_ace_event: dedup hit for %s", event_id)
        return {"status": "duplicate", "event_id": event_id}

    detail_type = str(event.get("detail-type") or "")
    detail = event.get("detail") or {}

    with HubSpotClient(config) as hubspot:
        if detail_type == "Opportunity Updated":
            result = _handle_opportunity_updated(detail, state=state, hubspot=hubspot)
        elif detail_type.startswith("Engagement Invitation"):
            result = _handle_invitation_event(
                detail_type, detail, state=state, hubspot=hubspot
            )
        else:
            result = {"status": "skipped", "reason": f"unhandled detail-type {detail_type}"}

    if event_id:
        state.mark_event_seen(event_id, ttl_seconds=config.ace.event_dedup_ttl_seconds)
    return result
