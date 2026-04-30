"""GovWin sync worker (v2.1: replaces fetch_opp_details + sync_to_hubspot).

Triggered by SQS. Each message carries one batch of opportunity references
(``[{"id", "updateDate"}, ...]``) produced by ``govwin_orchestrator``. The
worker fetches the full bundle for each opportunity from GovWin and syncs
companies / contacts / deals / associations to HubSpot.

Concurrency is governed by Lambda reservedConcurrency rather than a Step
Function Map state. Permanent per-message failures are dropped (and surfaced
to SNS); transient failures (rate limit, HubSpot 5xx) are reported as batch
item failures so SQS redelivers.

The 256KB cross-boundary serialization workaround that lived in v1's
``fetch_opp_details`` is gone: bundles never leave this Lambda's memory.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import load_config
from src.govwin.auth import GovWinAuth
from src.govwin.client import GovWinClient, GovWinRateLimitError
from src.hubspot.client import HubSpotClient
from src.models import GovWinOpportunityBundle
from src.sync.orchestrator import SyncOrchestrator
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_OPP_ID_PATTERN = re.compile(r"^[A-Z]{2,3}\d+$")
_sns_client: Any | None = None


def _publish_failure_alert(
    *, config: Any, message_id: str, summary: str, detail: str
) -> None:
    """Best-effort SNS alert for terminal sync failures. Never raises."""
    topic_arn = config.aws.sns_topic_arn
    if not topic_arn:
        return
    global _sns_client
    if _sns_client is None:
        _sns_client = boto3.client("sns", region_name=config.aws.region)
    try:
        _sns_client.publish(
            TopicArn=topic_arn,
            Subject=f"GovWin sync error: {summary}"[:100],
            Message=json.dumps(
                {"message_id": message_id, "summary": summary, "detail": detail},
                indent=2,
                default=str,
            ),
        )
    except ClientError as exc:
        logger.exception("sns publish failed: %s", exc)


def _decode_batch(record: dict[str, Any]) -> list[dict[str, Any]]:
    body = record.get("body", "{}")
    payload = json.loads(body)
    if isinstance(payload, dict):
        batch = payload.get("opportunity_batch", [])
    else:
        batch = payload
    if not isinstance(batch, list):
        return []
    return [r for r in batch if isinstance(r, dict)]


def _fetch_bundles(
    client: GovWinClient, refs: list[dict[str, Any]]
) -> tuple[list[GovWinOpportunityBundle], list[str]]:
    bundles: list[GovWinOpportunityBundle] = []
    errors: list[str] = []
    for ref in refs:
        opp_id = ref.get("id")
        if not isinstance(opp_id, str) or not _OPP_ID_PATTERN.match(opp_id):
            errors.append(f"invalid opportunity id: {opp_id!r}")
            continue
        try:
            bundle = client.get_opportunity_bundle(opp_id)
        except GovWinRateLimitError:
            raise
        except Exception as exc:  # noqa: BLE001 -- per-id error capture
            errors.append(f"{opp_id}: {type(exc).__name__}")
            logger.exception("govwin.fetch failed for %s", opp_id)
            continue
        if bundle is None:
            errors.append(f"{opp_id}: not found")
            continue
        bundles.append(bundle)
    return bundles, errors


def _process_record(
    record: dict[str, Any],
    *,
    config: Any,
    state: SyncStateManager,
    govwin: GovWinClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    refs = _decode_batch(record)
    if not refs:
        return {"status": "empty"}

    bundles, fetch_errors = _fetch_bundles(govwin, refs)
    if not bundles:
        return {"status": "no_bundles", "errors": fetch_errors}

    orchestrator = SyncOrchestrator(
        config=config,
        govwin_client=govwin,
        hubspot_client=hubspot,
        state_manager=state,
    )
    stats = orchestrator.sync_opportunity_batch(bundles)
    if fetch_errors:
        stats.setdefault("errors", []).extend(fetch_errors)
    return stats


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SQS event source mapping entry point.

    Returns the standard ``batchItemFailures`` shape so SQS only retries
    messages whose processing actually failed.
    """
    config = load_config()
    state = SyncStateManager(config)
    auth = GovWinAuth(config)
    failures: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []

    with GovWinClient(config, auth) as govwin, HubSpotClient(config) as hubspot:
        hubspot.ensure_pipeline()
        for record in event.get("Records", []):
            message_id = str(record.get("messageId", "?"))
            try:
                result = _process_record(
                    record,
                    config=config,
                    state=state,
                    govwin=govwin,
                    hubspot=hubspot,
                )
                results.append(result)
            except json.JSONDecodeError:
                logger.warning("worker: invalid JSON in message %s", message_id)
                # Permanent error -- drop without retry.
                continue
            except GovWinRateLimitError:
                logger.warning(
                    "worker: GovWin rate limit hit on message %s; deferring batch",
                    message_id,
                )
                failures.append({"itemIdentifier": message_id})
            except Exception as exc:  # noqa: BLE001 -- batch-failure path
                logger.exception("worker: failed for message %s", message_id)
                _publish_failure_alert(
                    config=config,
                    message_id=message_id,
                    summary=type(exc).__name__,
                    detail=str(exc),
                )
                failures.append({"itemIdentifier": message_id})

    logger.info(
        "worker.complete records=%d failures=%d", len(results), len(failures)
    )
    return {"results": results, "batchItemFailures": failures}
