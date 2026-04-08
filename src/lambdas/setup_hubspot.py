"""One-time HubSpot setup: create custom properties, groups, and pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any

from src.config import load_config
from src.hubspot.client import HubSpotClient

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run one-time HubSpot setup.

    Creates:
    - Property group "govwin" on deals, companies, contacts
    - All custom properties
    - GovWin deal pipeline with stages

    This Lambda is idempotent and safe to run multiple times.
    """
    config = load_config()

    with HubSpotClient(config) as client:
        result = client.setup()

    logger.info(
        "HubSpot setup complete: pipeline=%s, %d deal props, %d company props, %d contact props",
        result["pipeline_id"],
        result["deal_properties"],
        result["company_properties"],
        result["contact_properties"],
    )

    return result
