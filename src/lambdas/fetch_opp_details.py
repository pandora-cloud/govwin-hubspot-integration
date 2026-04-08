"""Fetch full details for a batch of opportunities."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from src.config import load_config
from src.govwin.auth import GovWinAuth
from src.govwin.client import GovWinClient, GovWinRateLimitError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MAX_PAYLOAD_BYTES = 200_000  # 200KB safety margin under 256KB Step Function limit
OPP_ID_PATTERN = re.compile(r"^[A-Z]{2,3}\d+$")


def _validate_opp_id(opp_id: str) -> bool:
    """Validate that an opportunity ID matches expected format."""
    return bool(OPP_ID_PATTERN.match(opp_id))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Fetch full opportunity data including extended attributes.

    Input:
        event: list of {id, updateDate} from discover_changes

    Returns:
        {
            "bundles": [{opportunity, contacts, companies, ...}, ...],
            "rate_limit_calls_used": int,
            "errors": [str, ...],
        }
    """
    config = load_config()
    auth = GovWinAuth(config)

    opp_refs = event if isinstance(event, list) else event.get("opportunity_batch", [])

    bundles: list[dict[str, Any]] = []
    errors: list[str] = []

    with GovWinClient(config, auth) as client:
        for ref_idx, ref in enumerate(opp_refs):
            opp_id = ref.get("id") if isinstance(ref, dict) else None
            if not opp_id:
                continue
            if not _validate_opp_id(opp_id):
                errors.append(f"Invalid opportunity ID format: {opp_id!r}")
                continue

            try:
                bundle = client.get_opportunity_bundle(opp_id)
                if bundle:
                    serialized = bundle.model_dump(mode="json")
                    bundles.append(serialized)
                    logger.info("Fetched details for %s", opp_id)

                    # Check payload size to stay within Step Function limits
                    payload_size = len(json.dumps(bundles))
                    if payload_size > MAX_PAYLOAD_BYTES:
                        # Track skipped IDs using enumerate index (not list.index)
                        skipped = [
                            r.get("id") for r in opp_refs[ref_idx + 1:]
                            if r.get("id")
                        ]
                        for sid in skipped:
                            errors.append(f"Skipped {sid}: payload size limit exceeded")
                        logger.warning(
                            "Payload size %d exceeds limit, returning %d of %d bundles, "
                            "skipped %d opportunities",
                            payload_size, len(bundles), len(opp_refs), len(skipped),
                        )
                        break
                else:
                    logger.warning("Opportunity %s not found", opp_id)
            except GovWinRateLimitError:
                raise
            except Exception as e:
                error_msg = f"Failed to fetch {opp_id}: {type(e).__name__}"
                errors.append(error_msg)
                logger.exception(error_msg)

        calls_used = client.rate_limiter.calls_in_window

    logger.info(
        "Fetched %d opportunity bundles (%d errors, %d API calls)",
        len(bundles), len(errors), calls_used,
    )

    return {
        "bundles": bundles,
        "rate_limit_calls_used": calls_used,
        "errors": errors,
    }
