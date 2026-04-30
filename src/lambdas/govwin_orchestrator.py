"""GovWin sync orchestrator (v2.1: replaces Step Functions Map state).

Triggered by EventBridge Scheduler. Refreshes the GovWin OAuth token,
discovers opportunities to sync (via the existing discovery modes:
marked / saved-search / bookmarked / date-range), filters out unchanged
ones, and fans the work out across SQS messages where each message
carries one batch of opportunity IDs to a worker Lambda.

This Lambda does NOT call HubSpot or fetch opportunity details. The
worker (govwin_worker.py) handles per-batch fetch+sync. Splitting the
roles keeps the orchestrator's run time bounded by a single
discovery pass and an SQS fan-out, while parallelism is governed by
worker reservedConcurrency rather than Step Functions Map maxConcurrency.

Replaces the v1 chain:
  authenticate -> discover_changes -> Map(fetch_opp_details + sync_to_hubspot) -> update_sync_state
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import load_config
from src.govwin.auth import GovWinAuth
from src.govwin.client import GovWinClient
from src.sync.dedup import batch_opportunities, filter_changed_opportunities
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_sqs_client: Any | None = None


def _ensure_sqs(region: str) -> Any:
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=region)
    return _sqs_client


def _serialize_batch(batch: list[Any]) -> list[dict[str, str | None]]:
    return [
        {"id": opp.id, "updateDate": opp.update_date}
        for opp in batch
        if opp.id
    ]


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Discover GovWin changes, refresh tokens, and fan out batches to SQS.

    Returns a summary of discovery and enqueue counts. Per-batch fetch +
    HubSpot sync happens in govwin_worker after SQS delivery.
    """
    config = load_config()
    queue_url = os.environ.get("GOVWIN_SYNC_QUEUE_URL", "")
    if not queue_url:
        logger.error("GOVWIN_SYNC_QUEUE_URL is not configured")
        return {"status": "misconfigured"}

    auth = GovWinAuth(config)
    state = SyncStateManager(config)

    with GovWinClient(config, auth) as client:
        if config.govwin.marked_version:
            logger.info(
                "discover.marked version=%s opp_type=%s",
                config.govwin.marked_version,
                config.govwin.opp_types,
            )
            opportunities = client.get_all_marked_opportunities(
                marked_version=config.govwin.marked_version,
                opp_type=config.govwin.opp_types,
            )
            if not opportunities:
                logger.warning(
                    "No opportunities marked for sync (version=%s). Ensure "
                    "the BD team has marked opps in GovWin IQ for "
                    "'Web Services Download', or set GOVWIN_MARKED_VERSION='' "
                    "to sync all opportunities.",
                    config.govwin.marked_version,
                )
        else:
            last_sync = state.get_last_sync_timestamp()
            if last_sync:
                from_date = last_sync
            else:
                lookback = datetime.now(UTC) - timedelta(
                    days=config.sync.initial_lookback_days
                )
                from_date = lookback.strftime("%m/%d/%Y")
            logger.info("discover.search from=%s", from_date)
            opportunities = client.search_all_opportunities(
                opp_type=config.govwin.opp_types,
                market=config.govwin.market,
                opp_selection_date_from=from_date,
                saved_search_id=config.govwin.saved_search_id,
                bookmarked_only=config.govwin.bookmarked_only,
            )

        changed = filter_changed_opportunities(opportunities, state)
        batches = batch_opportunities(changed, config.sync.batch_size)
        sqs = _ensure_sqs(config.aws.region)

        enqueued = 0
        for batch in batches:
            payload = _serialize_batch(batch)
            if not payload:
                continue
            try:
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({"opportunity_batch": payload}),
                )
                enqueued += 1
            except ClientError as exc:
                logger.exception("sqs.send_message failed for batch: %s", exc)

        # In date-range mode the cursor is advanced eagerly because each
        # worker is independent and we don't want stragglers to block.
        # Marked mode does not use the cursor. (v1 deferred this to a
        # separate update_sync_state Lambda; here the orchestrator owns it
        # because every other state transition is co-located.)
        if not config.govwin.marked_version:
            state.set_last_sync_timestamp(datetime.now(UTC).strftime("%m/%d/%Y"))

        result = {
            "status": "ok",
            "discovered_total": len(opportunities),
            "discovered_changed": len(changed),
            "batches_enqueued": enqueued,
            "rate_limit_calls_used": client.rate_limiter.calls_in_window,
        }
        logger.info("orchestrator.complete %s", result)
        return result
