"""Discover opportunities updated since last sync."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from src.config import load_config
from src.govwin.auth import GovWinAuth
from src.govwin.client import GovWinClient
from src.sync.dedup import batch_opportunities, filter_changed_opportunities
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Search GovWin for updated opportunities and return batched IDs.

    Supports three discovery modes (configurable, can combine):
      1. marked_version (default "2.2"): Only opps marked for sync in GovWin
      2. saved_search_id: Only opps matching a saved search
      3. bookmarked_only: Only bookmarked opps

    If marked_version is set, uses the marking API (BD team marks opps in GovWin).
    Otherwise falls back to broad date-range search with optional saved_search/bookmark filters.

    Returns:
        {
            "opportunities_count": int,
            "opportunity_batches": [[{id, updateDate}, ...], ...],
            "rate_limit_calls_used": int,
        }
    """
    config = load_config()
    auth = GovWinAuth(config)
    state = SyncStateManager(config)

    with GovWinClient(config, auth) as client:
        # Mode 1: Marked for sync (default - BD team marks opps in GovWin IQ)
        if config.govwin.marked_version:
            logger.info(
                "Discovering opportunities marked for sync (version=%s)",
                config.govwin.marked_version,
            )
            opportunities = client.get_all_marked_opportunities(
                marked_version=config.govwin.marked_version,
                opp_type=config.govwin.opp_types,
            )
            if not opportunities:
                logger.warning(
                    "No opportunities marked for sync (version=%s). "
                    "Ensure your BD team has marked opps in GovWin IQ for "
                    "'Web Services Download', or set GOVWIN_MARKED_VERSION='' "
                    "to sync all opportunities.",
                    config.govwin.marked_version,
                )
        else:
            # Mode 2/3: Date-range search with optional saved search or bookmark filter
            last_sync = state.get_last_sync_timestamp()
            if last_sync:
                from_date = last_sync
            else:
                lookback = datetime.now(UTC) - timedelta(
                    days=config.sync.initial_lookback_days
                )
                from_date = lookback.strftime("%m/%d/%Y")

            logger.info("Searching for opportunities updated since %s", from_date)

            opportunities = client.search_all_opportunities(
                opp_type=config.govwin.opp_types,
                market=config.govwin.market,
                opp_selection_date_from=from_date,
                saved_search_id=config.govwin.saved_search_id,
                bookmarked_only=config.govwin.bookmarked_only,
            )

        # Filter out opportunities that haven't actually changed
        changed = filter_changed_opportunities(opportunities, state)

        # Batch for Step Function Map state
        batches = batch_opportunities(changed, config.sync.batch_size)
        serialized_batches = [
            [
                {"id": opp.id, "updateDate": opp.update_date}
                for opp in batch
                if opp.id
            ]
            for batch in batches
        ]

        calls_used = client.rate_limiter.calls_in_window
        logger.info(
            "Discovered %d opportunities (%d changed, %d batches, %d API calls used)",
            len(opportunities),
            len(changed),
            len(serialized_batches),
            calls_used,
        )

        return {
            "opportunities_count": len(changed),
            "opportunity_batches": serialized_batches,
            "rate_limit_calls_used": calls_used,
        }
