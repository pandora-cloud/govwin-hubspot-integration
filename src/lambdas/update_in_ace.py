"""Apply HubSpot deal field changes to a previously-submitted ACE opportunity.

Triggered by SQS for property-change events on already-mapped deals
(``amount``, ``closedate``, ``dealname``, etc). Updates use optimistic
locking via the stored ``LastModifiedDate``; on ``ConflictException`` we
re-fetch and retry.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.ace.client import ACEClient
from src.config import load_config
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "amount": ("Project", "ExpectedCustomerSpend"),
    "closedate": ("LifeCycle", "TargetCloseDate"),
    "dealname": ("Project", "Title"),
    "description": ("Project", "CustomerUseCase"),
}


def _build_update(hs_event: dict[str, Any]) -> dict[str, Any] | None:
    """Translate a single property-change event into ACE update kwargs."""
    prop = hs_event.get("propertyName")
    value = hs_event.get("propertyValue")
    if not prop or value is None or prop not in _FIELD_MAP:
        return None
    section, field = _FIELD_MAP[prop]
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
    return {section: {field: value}}


def _process_event(
    hs_event: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
) -> dict[str, Any]:
    deal_id = str(hs_event.get("objectId") or "")
    govwin_id = hs_event.get("partnerOpportunityIdentifier") or _lookup_govwin_id(state, deal_id)
    if not govwin_id:
        return {"status": "skipped", "reason": "no govwin mapping"}
    mapping = state.get_ace_mapping(str(govwin_id)) or {}
    ace_id = mapping.get("ace_opportunity_id")
    if not ace_id:
        return {"status": "skipped", "reason": "no ace mapping yet"}
    update = _build_update(hs_event)
    if not update:
        return {"status": "skipped", "reason": "no relevant field"}

    response = ace.update_with_retry(identifier=ace_id, updates=update)
    state.set_ace_mapping(
        govwin_id=str(govwin_id),
        ace_opportunity_id=ace_id,
        last_modified_date=str(response.get("LastModifiedDate"))
        if response.get("LastModifiedDate")
        else None,
        ace_engagement_invitation_id=mapping.get("ace_engagement_invitation_id"),
        ace_task_id=mapping.get("ace_task_id"),
        client_token=mapping.get("client_token"),
        hubspot_deal_id=str(deal_id),
    )
    return {"status": "updated", "ace_opportunity_id": ace_id}


def _lookup_govwin_id(state: SyncStateManager, deal_id: str) -> str | None:
    """Best-effort lookup: scan ACE mappings for the deal_id.

    For v1 we expect ``hubspot_deal_id`` to be in the mapping. If not present
    we return None and the caller skips.
    """
    # No secondary index in v1; rely on caller-provided identifier or
    # fallback to nothing. (Phase 4 may add a GSI if needed.)
    return None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config()
    state = SyncStateManager(config)
    ace = ACEClient(config)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "?")
        try:
            hs_event = json.loads(record.get("body", "{}"))
            results.append(_process_event(hs_event, state=state, ace=ace))
        except Exception:  # noqa: BLE001 -- DLQ via partial-batch failure
            logger.exception("update_in_ace failed for message %s", message_id)
            failures.append({"itemIdentifier": message_id})

    return {"results": results, "batchItemFailures": failures}
