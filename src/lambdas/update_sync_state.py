"""Update sync state after a successful sync run."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from src.config import load_config
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Update the global sync cursor after a run.

    Only advances the cursor if no batches failed. If any batch returned
    {"status": "failed"}, the cursor is NOT advanced so failed opportunities
    will be re-synced on the next run.

    Input:
        event: {sync_results: [...], ...} aggregated results from Map state
    """
    config = load_config()
    state = SyncStateManager(config)

    # Check for failed batches in Map results
    sync_results = event.get("sync_results", [])
    failed_batches = [
        r for r in sync_results
        if isinstance(r, dict) and r.get("status") in ("failed", "partial")
    ]

    if failed_batches:
        logger.warning(
            "Skipping cursor advance: %d of %d batches failed",
            len(failed_batches), len(sync_results),
        )
        return {
            "status": "partial_failure",
            "failed_batches": len(failed_batches),
            "total_batches": len(sync_results),
        }

    # Only write the sync cursor in date-range mode (not marked mode).
    # In marked mode the cursor is unused; writing it would create a stale
    # value that could cause issues if the deployment later switches modes.
    if config.govwin.marked_version:
        logger.info("Marked mode active - skipping cursor update (not needed)")
        return {"status": "updated", "mode": "marked"}

    timestamp = datetime.now(UTC).strftime("%m/%d/%Y")
    state.set_last_sync_timestamp(timestamp)

    logger.info("Updated sync cursor to %s", timestamp)

    return {
        "status": "updated",
        "last_sync_timestamp": timestamp,
    }
