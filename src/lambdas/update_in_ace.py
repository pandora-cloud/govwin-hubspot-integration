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
from src.ace.validators import is_valid_hubspot_object_id
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


def _apply_delta(payload: dict[str, Any], prop: str, value: Any) -> bool:
    """Mutate ``payload`` (an UpdateOpportunity body) for one property change.

    AWS UpdateOpportunity has PUT semantics; the caller has already fetched
    and scrubbed the current opportunity into ``payload``. This function
    only edits the field that changed. Returns True if the delta was
    applied; False to skip (irrelevant property or empty value).
    """
    if value is None or value == "":
        return False
    project = dict(payload.get("Project") or {})
    life_cycle = dict(payload.get("LifeCycle") or {})

    if prop == "amount":
        try:
            spend = float(value)
        except (TypeError, ValueError):
            return False
        project["ExpectedCustomerSpend"] = [
            {
                "Amount": f"{spend:.2f}",
                "CurrencyCode": "USD",
                "Frequency": "Monthly",
                "TargetCompany": "Pandora Cloud LLC",
            }
        ]
        payload["Project"] = project
        return True
    if prop == "closedate":
        life_cycle["TargetCloseDate"] = str(value)[:10]
        payload["LifeCycle"] = life_cycle
        return True
    if prop == "dealname":
        title = str(value)[:255]
        project["Title"] = title
        # CustomerBusinessProblem has a 20-char minimum; if the existing
        # value would fall below the minimum (or didn't exist), use the
        # new title to seed it so the PUT does not regress validation.
        existing_problem = project.get("CustomerBusinessProblem") or ""
        if len(existing_problem) < 20 and len(title) >= 20:
            project["CustomerBusinessProblem"] = title
        payload["Project"] = project
        return True
    if prop == "description":
        # CustomerBusinessProblem has a server-side regex (?s).{20,2000}.
        # If the new description is below the minimum, pad with the
        # existing project title (mirrors the create-path behavior). If
        # neither is long enough, skip the delta rather than write an
        # invalid value that AWS will reject as a permanent error.
        text = str(value)[:2000]
        if len(text) < 20:
            title = str(project.get("Title") or "")[:200]
            text = f"{title}: {text}"[:2000] if title else text
        if len(text) < 20:
            return False
        project["CustomerBusinessProblem"] = text
        payload["Project"] = project
        return True
    if prop == "govwin_ace_use_case":
        project["CustomerUseCase"] = str(value)
        payload["Project"] = project
        return True
    return False


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


# HubSpot webhooks include the changed property value in propertyValue,
# but for long string fields the value can be truncated by HubSpot. For
# these we ignore propertyValue and re-fetch the full deal record.
_REFETCH_FROM_HUBSPOT_PROPERTIES: frozenset[str] = frozenset({"description", "dealname"})


def _resolve_property_value(
    hs_event: dict[str, Any],
    hubspot: HubSpotClient,
    deal_id: str,
    prop: str,
) -> Any:
    """Return the authoritative value for the changed property.

    For free-text properties HubSpot may truncate ``propertyValue`` in the
    webhook delivery, so we fetch the deal directly. For other properties
    (enums, dates, numbers) the webhook value is authoritative.
    """
    if prop in _REFETCH_FROM_HUBSPOT_PROPERTIES:
        try:
            deal = hubspot.get_deal(deal_id, properties=[prop])
        except Exception:  # noqa: BLE001 -- best effort, fall back to webhook value
            logger.exception("update_in_ace: get_deal %s failed; using webhook value", deal_id)
            return hs_event.get("propertyValue")
        return (deal.get("properties") or {}).get(prop) or hs_event.get("propertyValue")
    return hs_event.get("propertyValue")


def _process_event(
    hs_event: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    raw_deal_id = str(hs_event.get("objectId") or "")
    if not is_valid_hubspot_object_id(raw_deal_id):
        return {"status": "skipped", "reason": "invalid objectId"}
    deal_id = raw_deal_id

    prop = hs_event.get("propertyName")
    if not prop:
        return {"status": "skipped", "reason": "no propertyName"}

    govwin_id = _resolve_govwin_id(state, hubspot, deal_id)
    if not govwin_id:
        return {"status": "skipped", "reason": "no govwin mapping"}

    mapping = state.get_ace_mapping(govwin_id) or {}
    ace_id = mapping.get("ace_opportunity_id")
    if not ace_id:
        return {"status": "skipped", "reason": "no ace mapping yet"}

    # AWS UpdateOpportunity has PUT semantics: any field omitted from the
    # request is treated as being cleared. Fetch the current opportunity,
    # whitelist to the subset of fields UpdateOpportunity accepts, and
    # apply only the property-change delta on top.
    current = ace.get_opportunity(str(ace_id))
    payload = ACEClient.scrub_for_update(current)
    value = _resolve_property_value(hs_event, hubspot, deal_id, str(prop))
    if not _apply_delta(payload, str(prop), value):
        return {"status": "skipped", "reason": f"no relevant field for {prop}"}

    response = ace.update_with_retry(
        identifier=str(ace_id),
        updates=payload,
        known_last_modified_date=current.get("LastModifiedDate"),
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
