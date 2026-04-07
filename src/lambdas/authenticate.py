"""Lambda: Authenticate with GovWin and return token info for the Step Function."""

from __future__ import annotations

import logging
import os
from typing import Any

from src.config import load_config
from src.govwin.auth import GovWinAuth

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Get or refresh GovWin OAuth token.

    Returns token status in the Step Function execution context.
    The actual token is stored in Secrets Manager, not passed in the state.
    """
    config = load_config()
    auth = GovWinAuth(config)

    # Accessing the property triggers authentication if needed
    token = auth.access_token

    logger.info("GovWin authentication successful")
    return {
        "status": "authenticated",
        "token_available": bool(token),
    }
