"""Deduplication logic for filtering out already-synced opportunities."""

from __future__ import annotations

import logging

from src.models import GovWinOpportunity
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)


def filter_changed_opportunities(
    opportunities: list[GovWinOpportunity],
    state_manager: SyncStateManager,
) -> list[GovWinOpportunity]:
    """Filter out opportunities that haven't changed since last sync.

    Compares each opportunity's updateDate against the stored value.
    Returns only opportunities that are new or have a newer updateDate.
    """
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
        elif opp.update_date and opp.update_date > stored_date:
            # Updated since last sync
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
