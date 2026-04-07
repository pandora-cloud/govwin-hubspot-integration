"""Lambda: Handle errors from the Step Function — notify and DLQ."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from src.config import load_config

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_SAFE_KEYS = {"error", "cause", "status"}
_SENSITIVE_SUBSTRINGS = {"token", "secret", "password", "credential"}
_MAX_VALUE_LEN = 500


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Create a safe copy of the event, stripping sensitive data."""
    safe: dict[str, Any] = {}
    for key, value in event.items():
        key_lower = key.lower()
        # Skip keys containing sensitive substrings
        if any(s in key_lower for s in _SENSITIVE_SUBSTRINGS):
            continue
        # Keep only safe keys and keys ending in _count or _synced
        if key in _SAFE_KEYS or key_lower.endswith("_count") or key_lower.endswith("_synced"):
            if isinstance(value, str) and len(value) > _MAX_VALUE_LEN:
                safe[key] = value[:_MAX_VALUE_LEN]
            else:
                safe[key] = value
    return safe


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle sync errors: send SNS notification and write to SQS DLQ.

    Input:
        event: {error: str, cause: str, ...} from Step Function Catch
    """
    config = load_config()

    error_type = event.get("error", "Unknown")
    error_cause = event.get("cause", "No details available")

    logger.error("Sync error: %s — %s", error_type, error_cause)

    sanitized = _sanitize_event(event)

    # Send SNS notification
    if config.aws.sns_topic_arn:
        try:
            sns = boto3.client("sns", region_name=config.aws.region)
            sns.publish(
                TopicArn=config.aws.sns_topic_arn,
                Subject=f"GovWin-HubSpot Sync Error: {error_type}",
                Message=json.dumps(
                    {
                        "error": error_type,
                        "cause": error_cause,
                        "raw_event": sanitized,
                    },
                    indent=2,
                    default=str,
                ),
            )
            logger.info("Error notification sent to SNS")
        except Exception:
            logger.exception("Failed to send SNS notification")

    # Write to DLQ
    if config.aws.dlq_url:
        try:
            sqs = boto3.client("sqs", region_name=config.aws.region)
            sqs.send_message(
                QueueUrl=config.aws.dlq_url,
                MessageBody=json.dumps(sanitized, default=str),
            )
            logger.info("Error details written to DLQ")
        except Exception:
            logger.exception("Failed to write to DLQ")

    return {
        "status": "error_handled",
        "error": error_type,
    }
