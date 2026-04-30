"""Apply HubSpot deal field changes to a previously-submitted ACE opportunity.

Triggered by SQS for property-change events on already-mapped deals
(``amount``, ``closedate``, ``dealname``, ``description``). Each event:

1. Looks up the mapped GovWin id (preferring the ACE mapping by HubSpot
   deal id; falls back to fetching the deal and reading
   ``govwin_opp_id``).
2. Builds an ACE update kwargs dict from the changed property.
3. Calls ``UpdateOpportunity`` with optimistic locking.

Permanent errors (ValidationException, AccessDeniedException) are logged
and the SQS message is allowed to be deleted (no batch failure entry) so
poison messages do not loop indefinitely. Transient errors (Throttling,
InternalServer, Conflict) propagate as batch failures for SQS redelivery.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.ace.client import ACEAPIError, ACEClient
from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_PERMANENT_ERROR_CODES: set[str] = {
    "ValidationException",
    "AccessDeniedException",
    "ResourceNotFoundException",
}


def _build_update(prop: str, value: Any) -> dict[str, Any] | None:
    """Translate a single HubSpot property change into ACE update kwargs."""
    if value is None or value == "":
        return None
    if prop == "amount":
        try:
            spend = float(value)
        except (TypeError, ValueError):
            return None
        return {
            "Project": {
                "ExpectedCustomerSpend": [
                    {
                        "Amount": f"{spend:.2f}",
                        "CurrencyCode": "USD",
                        "Frequency": "Monthly",
                        "TargetCompany": "Pandora Cloud LLC",
                    }
                ]
            }
        }
    if prop == "closedate":
        return {"LifeCycle": {"TargetCloseDate": str(value)[:10]}}
    if prop == "dealname":
        return {"Project": {"Title": str(value)[:255]}}
    if prop == "description":
        # CustomerBusinessProblem is free text; CustomerUseCase is an
        # AWS-published enum, so we never write the description into it.
        # CustomerUseCase changes flow through the dedicated
        # govwin_ace_use_case property handler below.
        return {"Project": {"CustomerBusinessProblem": str(value)[:1500]}}
    if prop == "govwin_ace_use_case":
        return {"Project": {"CustomerUseCase": str(value)}}
    return None


def _resolve_govwin_id(
    state: SyncStateManager, hubspot: HubSpotClient, deal_id: str
) -> str | None:
    """Find the GovWin id for a HubSpot deal, preferring the ACE mapping."""
    direct = state.find_govwin_by_hubspot_deal_id(deal_id)
    if direct:
        return direct
    try:
        deal = hubspot.get_deal(deal_id, properties=["govwin_opp_id", "govwin_iq_opp_id"])
    except Exception:  # noqa: BLE001 -- best-effort fallback
        logger.exception("update_in_ace: get_deal %s failed", deal_id)
        return None
    properties = deal.get("properties") or {}
    govwin_id = properties.get("govwin_opp_id") or properties.get("govwin_iq_opp_id")
    return str(govwin_id) if govwin_id else None


def _process_event(
    hs_event: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    raw_deal_id = str(hs_event.get("objectId") or "")
    if not raw_deal_id.isdigit():
        return {"status": "skipped", "reason": "invalid objectId"}
    deal_id = raw_deal_id

    prop = hs_event.get("propertyName")
    update = _build_update(str(prop or ""), hs_event.get("propertyValue"))
    if not update:
        return {"status": "skipped", "reason": f"no relevant field for {prop}"}

    govwin_id = _resolve_govwin_id(state, hubspot, deal_id)
    if not govwin_id:
        return {"status": "skipped", "reason": "no govwin mapping"}

    mapping = state.get_ace_mapping(govwin_id) or {}
    ace_id = mapping.get("ace_opportunity_id")
    if not ace_id:
        return {"status": "skipped", "reason": "no ace mapping yet"}

    last_modified = mapping.get("last_modified_date")
    response = ace.update_with_retry(
        identifier=str(ace_id),
        updates=update,
        known_last_modified_date=last_modified,
    )
    state.update_ace_mapping(
        govwin_id=govwin_id,
        last_modified_date=str(response.get("LastModifiedDate"))
        if response.get("LastModifiedDate")
        else None,
        hubspot_deal_id=deal_id,
    )
    return {"status": "updated", "ace_opportunity_id": str(ace_id)}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
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
                logger.warning("update_in_ace: invalid JSON in message %s", message_id)
                # Permanent error: do not retry.
                continue
            try:
                results.append(
                    _process_event(hs_event, state=state, ace=ace, hubspot=hubspot)
                )
            except ACEAPIError as exc:
                if exc.code in _PERMANENT_ERROR_CODES:
                    logger.warning(
                        "update_in_ace: permanent error %s for message %s; dropping",
                        exc.code,
                        message_id,
                    )
                    continue
                logger.warning(
                    "update_in_ace: transient %s for message %s; retrying via SQS",
                    exc.code,
                    message_id,
                )
                failures.append({"itemIdentifier": message_id})
            except Exception:  # noqa: BLE001 -- batch-failure path
                logger.exception("update_in_ace failed for message %s", message_id)
                failures.append({"itemIdentifier": message_id})

    return {"results": results, "batchItemFailures": failures}
