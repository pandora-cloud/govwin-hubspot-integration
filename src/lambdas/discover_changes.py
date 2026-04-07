"""Lambda: Discover opportunities updated since last sync."""

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
        # Determine the search window
        last_sync = state.get_last_sync_timestamp()
        if last_sync:
            # last_sync is already in MM/DD/YYYY format (GovWin search param format)
            from_date = last_sync
        else:
            # First run: look back N days
            lookback = datetime.now(UTC) - timedelta(
                days=config.sync.initial_lookback_days
            )
            from_date = lookback.strftime("%m/%d/%Y")

        logger.info("Searching for opportunities updated since %s", from_date)

        # Search for all opportunities updated in the window
        opportunities = client.search_all_opportunities(
            opp_type=config.govwin.opp_types,
            market=config.govwin.market,
            opp_selection_date_from=from_date,
            saved_search_id=config.govwin.saved_search_id,
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
