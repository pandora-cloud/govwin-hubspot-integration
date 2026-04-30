"""Submit a HubSpot deal to AWS Partner Central via the three-call flow.

Triggered by SQS (events from ``hubspot_webhook_receiver``). For each event:

1. Fetch the full HubSpot deal record.
2. Atomically reserve a ClientToken in DynamoDB (idempotent on retry).
3. Call ``CreateOpportunity`` -> persist ``Id`` + ``LastModifiedDate``.
4. Call ``AssociateOpportunity`` with the configured Solution.
5. Call ``StartEngagementFromOpportunityTask`` to submit (with a
   separately-reserved task ClientToken so retries reuse it).

The mapping is reloaded between steps and updated via merge semantics so a
SQS redelivery resumes from the last persisted step. Permanent ACE errors
(ValidationException, AccessDeniedException) are dropped from the SQS batch
without retry; transient errors are reported as batch item failures.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.ace.client import ACEAPIError, ACEClient
from src.ace.mapper import (
    ACEMappingError,
    map_hubspot_deal_to_ace_create_payload,
    resolve_solution_id,
)
from src.ace.validators import is_valid_govwin_id, is_valid_hubspot_object_id
from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_PERMANENT_ERROR_CODES: set[str] = {
    "ValidationException",
    "AccessDeniedException",
    "ResourceNotFoundException",
    "BadRequestException",
}


_sns_client: Any | None = None


def _publish_mapping_error_alert(
    *, config: Any, deal_id: str, govwin_id: str, error: str
) -> None:
    """Publish an SNS alert when a deal cannot be mapped to a valid ACE
    payload, so the BD team gets a visible signal instead of a silent drop.
    Best-effort: failures here do not fail the SQS message.
    """
    topic_arn = config.aws.sns_topic_arn
    if not topic_arn:
        logger.info("sns: no topic configured; skipping mapping-error alert")
        return
    global _sns_client
    if _sns_client is None:
        _sns_client = boto3.client("sns", region_name=config.aws.region)
    subject = f"ACE submission rejected (deal {deal_id})"[:100]
    message = (
        "A HubSpot deal could not be submitted to AWS Partner Central because "
        "the integration could not map it to a valid CreateOpportunity payload. "
        "The deal needs to be corrected in HubSpot before resubmission.\n\n"
        f"HubSpot deal id: {deal_id}\n"
        f"GovWin opp id: {govwin_id}\n"
        f"Catalog: {config.ace.catalog}\n"
        f"Reason: {error}\n"
    )
    try:
        _sns_client.publish(TopicArn=topic_arn, Subject=subject, Message=message)
    except ClientError as exc:
        logger.exception("sns publish failed for mapping-error alert: %s", exc)


def _trigger_stages() -> set[str]:
    raw = os.environ.get("ACE_TRIGGER_STAGES", "submit_to_aws,submitted_to_aws")
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def _is_submit_trigger(hs_event: dict[str, Any]) -> bool:
    """Decide whether an inbound HubSpot event represents a submit-to-ACE intent."""
    if hs_event.get("subscriptionType") != "object.propertyChange":
        return False
    if hs_event.get("propertyName") != "dealstage":
        return False
    new_value = str(hs_event.get("propertyValue") or "").strip().lower()
    return new_value in _trigger_stages()


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
        "govwin_ace_solution",  # legacy alias
        "govwin_ace_use_case",  # CustomerUseCase override
        "govwin_ace_other_solution_description",
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
    if not is_valid_hubspot_object_id(deal_id):
        return {"status": "skipped", "reason": "invalid objectId"}
    if not _is_submit_trigger(hs_event):
        return {"status": "skipped", "reason": "not a submit-to-aws stage change"}

    deal = _load_deal(hubspot, deal_id)
    properties = deal.get("properties") or deal
    govwin_id = properties.get("govwin_opp_id") or properties.get("govwin_iq_opp_id")
    if not govwin_id or not is_valid_govwin_id(str(govwin_id)):
        return {"status": "skipped", "reason": "deal missing or invalid govwin_opp_id"}
    govwin_id = str(govwin_id)

    # Step 1: reserve ClientToken atomically.
    create_token = state.reserve_client_token(govwin_id, ACEClient.new_client_token())

    # Reload the mapping so we operate on the post-reservation snapshot.
    mapping = state.get_ace_mapping(govwin_id) or {}
    ace_opportunity_id = mapping.get("ace_opportunity_id") or ""
    last_modified_date = mapping.get("last_modified_date")

    # Step 2: CreateOpportunity if we don't already have an Id.
    if not ace_opportunity_id:
        try:
            payload = map_hubspot_deal_to_ace_create_payload(
                deal, config, client_token=create_token
            )
        except ACEMappingError as exc:
            logger.warning("ACE mapping failed for deal %s: %s", deal_id, exc)
            _publish_mapping_error_alert(
                config=config,
                deal_id=deal_id,
                govwin_id=govwin_id,
                error=str(exc),
            )
            return {"status": "rejected", "reason": str(exc)}

        response = ace.create_opportunity(payload)
        ace_opportunity_id = response["Id"]
        last_modified_date = response.get("LastModifiedDate")
        state.update_ace_mapping(
            govwin_id=govwin_id,
            ace_opportunity_id=str(ace_opportunity_id),
            last_modified_date=str(last_modified_date) if last_modified_date else None,
            client_token=create_token,
            hubspot_deal_id=deal_id,
        )
        logger.info("ace.created opportunity_id=%s govwin_id=%s", ace_opportunity_id, govwin_id)
        mapping = state.get_ace_mapping(govwin_id) or mapping

    # Step 3: AssociateOpportunity. Skipped when no Solution ID is configured
    # (e.g. Sandbox where no Approved solution is registered); in that case
    # the create-opportunity payload included OtherSolutionDescription, which
    # AWS accepts as the alternative.
    solution_id = resolve_solution_id(deal, config)
    if solution_id and not mapping.get("ace_task_id"):
        try:
            ace.associate_opportunity(
                opportunity_identifier=str(ace_opportunity_id),
                related_entity_identifier=solution_id,
                related_entity_type="Solutions",
            )
            logger.info("ace.associated solution=%s opp=%s", solution_id, ace_opportunity_id)
        except ACEAPIError as exc:
            if exc.code != "ConflictException":
                raise
            # AWS does not return the existing associated solution from the
            # error, so we cannot distinguish "same solution" from "different
            # solution already associated." Log loudly so an operator notices
            # if the deal's intended solution was changed between attempts.
            logger.warning(
                "ace.associate conflict on opp=%s solution=%s; existing "
                "association assumed correct (verify if solution changed)",
                ace_opportunity_id,
                solution_id,
            )
    elif not solution_id:
        logger.info(
            "ace.associate skipped: no Solution ID configured; relying on "
            "OtherSolutionDescription on opp=%s",
            ace_opportunity_id,
        )

    # Step 4: StartEngagementFromOpportunityTask. Reuse a persisted task token
    # so that an SQS retry hits the same idempotency key on the AWS side.
    if not mapping.get("ace_task_id"):
        task_token = state.reserve_task_client_token(
            govwin_id, ACEClient.new_client_token()
        )
        task_response = ace.start_engagement_from_opportunity_task(
            opportunity_identifier=str(ace_opportunity_id),
            client_token=task_token,
        )
        state.update_ace_mapping(
            govwin_id=govwin_id,
            ace_engagement_invitation_id=task_response.get("EngagementInvitationId"),
            ace_task_id=task_response.get("TaskId"),
            hubspot_deal_id=deal_id,
        )
        logger.info(
            "ace.engagement_started task=%s opp=%s",
            task_response.get("TaskId"),
            ace_opportunity_id,
        )

    return {
        "status": "submitted",
        "ace_opportunity_id": str(ace_opportunity_id),
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
                # Permanent error: drop the message rather than retry.
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
            except ACEAPIError as exc:
                if exc.code in _PERMANENT_ERROR_CODES:
                    logger.warning(
                        "submit_to_ace: permanent error %s for message %s; dropping. detail=%s",
                        exc.code,
                        message_id,
                        str(exc),
                    )
                    continue
                logger.warning(
                    "submit_to_ace: transient %s for message %s; retrying via SQS",
                    exc.code,
                    message_id,
                )
                failures.append({"itemIdentifier": message_id})
            except Exception:  # noqa: BLE001 -- batch-failure path
                logger.exception("submit_to_ace failed for message %s", message_id)
                failures.append({"itemIdentifier": message_id})

    return {"results": results, "batchItemFailures": failures}
