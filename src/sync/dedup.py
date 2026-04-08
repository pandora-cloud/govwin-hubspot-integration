"""Deduplication logic for filtering out already-synced opportunities."""

from __future__ import annotations

import logging

from dateutil.parser import parse as parse_date

from src.models import GovWinOpportunity
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)


def _parse_date_safe(date_str: str | None) -> float:
    """Parse a date string to a UTC timestamp for comparison.

    Handles ISO-8601 with timezone offsets (e.g., '2025-03-09T02:30:00-05:00')
    by converting to UTC epoch seconds. Returns 0 on parse failure.
    """
    if not date_str:
        return 0.0
    try:
        return parse_date(date_str).timestamp()
    except (ValueError, OverflowError):
        return 0.0


def filter_changed_opportunities(
    opportunities: list[GovWinOpportunity],
    state_manager: SyncStateManager,
) -> list[GovWinOpportunity]:
    """Return only opportunities that are new or updated since last sync."""
    if not opportunities:
        return []

    opp_ids = [o.id for o in opportunities if o.id]
    stored_dates = state_manager.batch_get_opp_update_dates(opp_ids)

    changed: list[GovWinOpportunity] = []
    for opp in opportunities:
        if not opp.id:
            continue

        stored_date = stored_dates.get(opp.id)
        if stored_date is None:
            # New opportunity, never synced
            changed.append(opp)
        elif opp.update_date and _parse_date_safe(opp.update_date) > _parse_date_safe(stored_date):
            # Updated since last sync (timezone-aware comparison)
            changed.append(opp)

    logger.info(
        "Filtered %d opportunities: %d changed, %d unchanged",
        len(opportunities),
        len(changed),
        len(opportunities) - len(changed),
    )
    return changed


def batch_opportunities(
    opportunities: list[GovWinOpportunity],
    batch_size: int = 10,
) -> list[list[GovWinOpportunity]]:
    """Split opportunities into batches for Step Function Map state processing."""
    return [
        opportunities[i : i + batch_size]
        for i in range(0, len(opportunities), batch_size)
    ]
