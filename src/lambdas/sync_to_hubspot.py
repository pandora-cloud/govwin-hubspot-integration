"""Lambda: Push fetched opportunity data to HubSpot."""

from __future__ import annotations

import logging
import os
from typing import Any

from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.models import GovWinOpportunityBundle
from src.sync.orchestrator import SyncOrchestrator
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Sync opportunity bundles to HubSpot.

    Input:
        event: {bundles: [...], rate_limit_calls_used: int, errors: [...]}

    Returns:
        Sync statistics.
    """
    config = load_config()
    state = SyncStateManager(config)

    raw_bundles = event.get("bundles", [])
    fetch_errors = event.get("errors", [])

    if not raw_bundles:
        logger.info("No bundles to sync")
        return {"deals_synced": 0, "companies_synced": 0, "contacts_synced": 0}

    # Deserialize bundles
    bundles = [GovWinOpportunityBundle.model_validate(b) for b in raw_bundles]

    with HubSpotClient(config) as hubspot:
        # Ensure pipeline exists and stage IDs are cached
        hubspot.ensure_pipeline()

        orchestrator = SyncOrchestrator(
            config=config,
            govwin_client=None,
            hubspot_client=hubspot,
            state_manager=state,
        )

        stats = orchestrator.sync_opportunity_batch(bundles)

    logger.info(
        "Synced %d deals, %d companies, %d contacts, %d associations",
        stats["deals_synced"],
        stats["companies_synced"],
        stats["contacts_synced"],
        stats["associations_created"],
    )

    # Propagate fetch errors so update_sync_state knows about skipped IDs
    if fetch_errors:
        stats.setdefault("errors", []).extend(fetch_errors)

    # Signal partial failure if there were any errors (fetch or sync)
    if stats.get("errors"):
        stats["status"] = "partial"

    return stats
