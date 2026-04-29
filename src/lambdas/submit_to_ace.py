"""Submit a HubSpot deal to AWS Partner Central via the three-call flow.

Triggered by SQS (events enqueued by ``hubspot_webhook_receiver``). For each
event we:

1. Fetch the full HubSpot deal record.
2. Reserve a ClientToken in DynamoDB (idempotent on retry).
3. Call ``CreateOpportunity`` -> persist ``Id`` + ``LastModifiedDate``.
4. Call ``AssociateOpportunity`` with the configured Solution.
5. Call ``StartEngagementFromOpportunityTask`` to submit.

Steps 3-5 are idempotent on SQS redelivery: the DynamoDB ACE mapping is
checked at each step so a partial failure resumes from the last successful
step instead of starting over.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.ace.client import ACEAPIError, ACEClient
from src.ace.mapper import (
    ACEMappingError,
    map_hubspot_deal_to_ace_create_payload,
    resolve_solution_id,
)
from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_TRIGGER_STAGES: set[str] = {
    s.strip().lower()
    for s in os.environ.get("ACE_TRIGGER_STAGES", "submit_to_aws,submitted_to_aws").split(",")
    if s.strip()
}


def _is_submit_trigger(hs_event: dict[str, Any]) -> bool:
    """Decide whether an inbound HubSpot event represents a submit-to-ACE intent."""
    if hs_event.get("subscriptionType") != "object.propertyChange":
        return False
    if hs_event.get("propertyName") != "dealstage":
        return False
    new_value = str(hs_event.get("propertyValue") or "").strip().lower()
    return new_value in _TRIGGER_STAGES


def _load_deal(hubspot: HubSpotClient, deal_id: str) -> dict[str, Any]:
    """Fetch a deal with the properties we need for ACE mapping."""
    properties = [
        "dealname",
        "amount",
        "closedate",
        "description",
        "dealstage",
        "govwin_opp_id",
        "govwin_iq_opp_id",
        "govwin_agency",
        "govwin_industry",
        "govwin_primary_requirement",
        "govwin_ace_partner_need",
        "govwin_ace_delivery_model",
        "govwin_ace_solution_id",
        "govwin_ace_opportunity_type",
    ]
    return hubspot.get_deal(deal_id, properties=properties)


def _process_event(
    hs_event: dict[str, Any],
    *,
    config: Any,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    deal_id = str(hs_event.get("objectId") or "")
    if not deal_id:
        return {"status": "skipped", "reason": "no objectId"}
    if not _is_submit_trigger(hs_event):
        return {"status": "skipped", "reason": "not a submit-to-aws stage change"}

    deal = _load_deal(hubspot, deal_id)
    properties = deal.get("properties", deal)
    govwin_id = properties.get("govwin_opp_id") or properties.get("govwin_iq_opp_id")
    if not govwin_id:
        return {"status": "skipped", "reason": "deal missing govwin_opp_id"}

    existing = state.get_ace_mapping(str(govwin_id)) or {}
    ace_opportunity_id = existing.get("ace_opportunity_id") or ""
    last_modified_date = existing.get("last_modified_date")

    # Step 1: reserve ClientToken (idempotent on retry).
    client_token = state.reserve_client_token(str(govwin_id), ACEClient.new_client_token())

    # Step 2: CreateOpportunity if we don't already have an Id.
    if not ace_opportunity_id:
        try:
            payload = map_hubspot_deal_to_ace_create_payload(
                deal, config, client_token=client_token
            )
        except ACEMappingError as exc:
            logger.warning("ACE mapping failed for deal %s: %s", deal_id, exc)
            return {"status": "rejected", "reason": str(exc)}

        response = ace.create_opportunity(payload)
        ace_opportunity_id = response["Id"]
        last_modified_date = response.get("LastModifiedDate")
        state.set_ace_mapping(
            govwin_id=str(govwin_id),
            ace_opportunity_id=ace_opportunity_id,
            last_modified_date=str(last_modified_date) if last_modified_date else None,
            client_token=client_token,
            hubspot_deal_id=deal_id,
        )
        logger.info("ace.created opportunity_id=%s govwin_id=%s", ace_opportunity_id, govwin_id)

    # Step 3: AssociateOpportunity (skip if already associated previously; AWS
    # responds with ConflictException for duplicates which we treat as success).
    if not existing.get("ace_engagement_invitation_id"):
        try:
            solution_id = resolve_solution_id(deal, config)
            ace.associate_opportunity(
                opportunity_identifier=ace_opportunity_id,
                related_entity_identifier=solution_id,
                related_entity_type="Solutions",
            )
            logger.info("ace.associated solution=%s opp=%s", solution_id, ace_opportunity_id)
        except ACEAPIError as exc:
            if exc.code != "ConflictException":
                raise
            logger.info("ace.associate already exists; continuing")

    # Step 4: StartEngagementFromOpportunityTask.
    if not existing.get("ace_task_id"):
        task_token = ACEClient.new_client_token()
        task_response = ace.start_engagement_from_opportunity_task(
            opportunity_identifier=ace_opportunity_id,
            client_token=task_token,
        )
        state.set_ace_mapping(
            govwin_id=str(govwin_id),
            ace_opportunity_id=ace_opportunity_id,
            last_modified_date=str(last_modified_date) if last_modified_date else None,
            ace_engagement_invitation_id=task_response.get("EngagementInvitationId"),
            ace_task_id=task_response.get("TaskId"),
            client_token=client_token,
            hubspot_deal_id=deal_id,
        )
        logger.info(
            "ace.engagement_started task=%s opp=%s",
            task_response.get("TaskId"),
            ace_opportunity_id,
        )

    return {
        "status": "submitted",
        "ace_opportunity_id": ace_opportunity_id,
        "govwin_id": govwin_id,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS event source mapping entry point."""
    config = load_config()
    state = SyncStateManager(config)
    ace = ACEClient(config)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    with HubSpotClient(config) as hubspot:
        for record in event.get("Records", []):
            message_id = record.get("messageId", "?")
            try:
                hs_event = json.loads(record.get("body", "{}"))
            except json.JSONDecodeError:
                logger.warning("submit_to_ace: invalid JSON in message %s", message_id)
                failures.append({"itemIdentifier": message_id})
                continue
            try:
                result = _process_event(
                    hs_event,
                    config=config,
                    state=state,
                    ace=ace,
                    hubspot=hubspot,
                )
                results.append(result)
            except Exception:  # noqa: BLE001 -- DLQ via partial-batch failure
                logger.exception("submit_to_ace failed for message %s", message_id)
                failures.append({"itemIdentifier": message_id})

    return {"results": results, "batchItemFailures": failures}
