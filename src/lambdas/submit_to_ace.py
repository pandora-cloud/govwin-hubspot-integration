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

from botocore.exceptions import ClientError

from src.ace.client import ACEAPIError, ACEClient
from src.ace.mapper import (
    ACEMappingError,
    aws_products_for_deal,
    map_hubspot_deal_to_ace_create_payload,
    resolve_solution_id,
)
from src.ace.validators import is_valid_govwin_id, is_valid_hubspot_object_id
from src.aws_clients import make_client
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
        _sns_client = make_client("sns", config.aws.region)
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


_DEAL_PROPERTIES_FOR_MAPPING = [
    "dealname",
    "amount",
    "closedate",
    "description",
    "dealstage",
    "hubspot_owner_id",
    "govwin_opp_id",
    "govwin_iq_opp_id",
    "govwin_agency",
    "govwin_industry",
    "govwin_primary_requirement",
    "govwin_ace_partner_need",
    "govwin_ace_delivery_model",
    "govwin_ace_solution_id",
    "govwin_ace_solution",  # legacy alias
    "govwin_ace_use_case",
    "govwin_ace_other_solution_description",
    "govwin_ace_opportunity_type",
    # Extended BD-editable property surface for richer AWS submissions:
    "govwin_ace_marketing_source",
    "govwin_ace_marketing_campaign_name",
    "govwin_ace_marketing_use_cases",
    "govwin_ace_marketing_channel",
    "govwin_ace_marketing_dev_funded",
    "govwin_ace_competitor_name",
    "govwin_ace_additional_comments",
    "govwin_ace_aws_account_id",
    "govwin_ace_next_steps",
    "govwin_ace_related_opportunity_id",
    "govwin_ace_aws_products",
]

_COMPANY_PROPERTIES_FOR_MAPPING = [
    "name", "industry", "domain", "website",
    "address", "city", "state", "zip", "country",
]

_CONTACT_PROPERTIES_FOR_MAPPING = [
    "firstname", "lastname", "email", "phone", "jobtitle",
    # PII gate: only forward contacts whose lifecyclestage flags
    # customer-side intent. Hyperscaler-Contact records (AWS-side
    # participants the EventBridge handler created) are filtered out
    # via hs_lead_status.
    "lifecyclestage", "hs_lead_status",
]


def _load_deal(hubspot: HubSpotClient, deal_id: str) -> dict[str, Any]:
    """Fetch a deal with the properties we need for ACE mapping."""
    return hubspot.get_deal(deal_id, properties=_DEAL_PROPERTIES_FOR_MAPPING)


def _load_associated_records(
    hubspot: HubSpotClient, deal_id: str, deal: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    """Fetch the deal's associated company, contacts, and owner.

    Each fetch is best-effort: if HubSpot returns 404 or the association
    doesn't exist yet, we fall through with None / [] rather than blocking
    the submission. The mapper handles missing associated records by
    falling back to GovWin-derived deal properties.
    """
    company = hubspot.get_associated_company(
        deal_id, properties=_COMPANY_PROPERTIES_FOR_MAPPING
    )
    contacts = hubspot.get_associated_contacts(
        deal_id, properties=_CONTACT_PROPERTIES_FOR_MAPPING
    )
    owner_id = ""
    props = deal.get("properties") or deal
    if isinstance(props, dict):
        owner_id = str(props.get("hubspot_owner_id") or "")
    owner = hubspot.get_owner(owner_id) if owner_id else None
    return company, contacts, owner


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
        company, contacts, owner = _load_associated_records(hubspot, deal_id, deal)
        try:
            payload = map_hubspot_deal_to_ace_create_payload(
                deal,
                config,
                client_token=create_token,
                company=company,
                contacts=contacts,
                owner=owner,
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
        # Surface the AWS-side identifiers on the HubSpot deal immediately
        # so BD doesn't have to wait for an EventBridge round-trip to see
        # the opportunity in their CRM. handle_ace_event will update
        # govwin_aws_cosell_status on subsequent ReviewStatus changes.
        try:
            hubspot.update_deal(deal_id, {
                "govwin_aws_cosell_id": str(ace_opportunity_id),
                "govwin_aws_cosell_status": "Pending Submission",
            })
        except Exception:  # noqa: BLE001 -- write-back is best-effort
            logger.exception(
                "submit_to_ace: write-back of aws_cosell_id failed for deal %s",
                deal_id,
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

    # Step 3b: AssociateOpportunity for any BD-tagged AWS products. Idempotent
    # via ConflictException -- a redelivered SQS message won't re-associate.
    aws_products = aws_products_for_deal(deal)
    if aws_products and not mapping.get("ace_task_id"):
        product_failures: list[str] = []
        for product_id in aws_products:
            try:
                ace.associate_opportunity(
                    opportunity_identifier=str(ace_opportunity_id),
                    related_entity_identifier=product_id,
                    related_entity_type="AwsProducts",
                )
                logger.info(
                    "ace.associated awsproduct=%s opp=%s",
                    product_id,
                    ace_opportunity_id,
                )
            except ACEAPIError as exc:
                if exc.code == "ConflictException":
                    continue  # already associated
                # Real failure (typo'd identifier, ResourceNotFoundException,
                # ValidationException). Don't fail the whole submission
                # because one product is invalid -- but DO surface to BD
                # via SNS so the bad value gets fixed in HubSpot.
                logger.warning(
                    "ace.associate awsproduct=%s failed: %s",
                    product_id,
                    exc,
                )
                product_failures.append(f"{product_id}: {exc.code}")
        if product_failures:
            _publish_mapping_error_alert(
                config=config,
                deal_id=deal_id,
                govwin_id=govwin_id,
                error=(
                    f"AWS Products association failed for {len(product_failures)} "
                    f"value(s) on opp={ace_opportunity_id}: "
                    + "; ".join(product_failures)
                    + ". Check govwin_ace_aws_products on the deal "
                    "(Identifiers must match aws_products.json from "
                    "github.com/aws-samples/partner-crm-integration-samples)."
                ),
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
                    # Permanent errors silently delete the SQS message
                    # (SQS sees a clean return). Without an SNS alert, the
                    # only visibility is a single CloudWatch warning -- a
                    # stuck deal is invisible to BD. Publish to SNS so
                    # the on-call sees the rejection. Best-effort: a
                    # publish failure does not propagate.
                    try:
                        deal_id = str((hs_event or {}).get("objectId") or "?")
                        _publish_mapping_error_alert(
                            config=config,
                            deal_id=deal_id,
                            govwin_id="(unknown - AWS rejected before lookup)",
                            error=f"AWS {exc.code}: {exc}",
                        )
                    except Exception:  # noqa: BLE001 -- alert is best-effort
                        logger.exception(
                            "submit_to_ace: SNS publish for permanent error failed"
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
