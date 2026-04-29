"""Receive HubSpot webhook deliveries, validate the signature, and enqueue.

Triggered by API Gateway HTTP API. Validates ``X-HubSpot-Signature-v3`` and
pushes events onto SQS for asynchronous processing. Must respond within the
documented 5-second budget so heavy lifting (CreateOpportunity etc.) happens
off the webhook critical path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import load_config

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# Hard limits to keep DoS exposure bounded. HubSpot batches up to ~100
# events per delivery (per the developer docs), so 100 events / 1 MiB body
# is a generous ceiling that still constrains the Lambda runtime.
MAX_BODY_BYTES = 1 * 1024 * 1024
MAX_EVENTS_PER_DELIVERY = 100
SQS_BATCH_SIZE = 10
SECRET_CACHE_TTL_SECONDS = 300

_secrets_client: Any | None = None
_sqs_client: Any | None = None
_secret_cache: dict[str, tuple[str, float]] = {}


def _ensure_clients(region: str) -> None:
    """Lazy-initialize boto3 clients (avoids no-region errors at import time)."""
    global _secrets_client, _sqs_client
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager", region_name=region)
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=region)


class _ConfigError(Exception):
    """Raised when a required webhook config value is missing or malformed."""


def _get_signing_secret(secret_name: str) -> str:
    """Return the signing secret, refreshing the cache every TTL seconds."""
    cached = _secret_cache.get(secret_name)
    now = time.time()
    if cached and (now - cached[1]) < SECRET_CACHE_TTL_SECONDS:
        return cached[0]
    assert _secrets_client is not None
    response = _secrets_client.get_secret_value(SecretId=secret_name)
    raw = response.get("SecretString", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _ConfigError("hubspot webhook secret is not valid JSON") from exc
    secret = parsed.get("client_secret") or parsed.get("clientSecret")
    if not isinstance(secret, str) or not secret:
        raise _ConfigError("hubspot webhook secret missing client_secret")
    _secret_cache[secret_name] = (secret, now)
    return secret


def _validate_signature(
    method: str,
    url: str,
    raw_body: bytes,
    signature_header: str,
    timestamp_header: str,
    secret: str,
    max_age_seconds: int,
) -> bool:
    """Constant-time validation of an X-HubSpot-Signature-v3 header."""
    try:
        ts_ms = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    if ts_ms <= 0:
        return False
    # Reject anything older than the policy window. Mild future-tolerance for
    # clock skew across HubSpot edge nodes.
    age_ms = time.time() * 1000 - ts_ms
    if age_ms > max_age_seconds * 1000 or age_ms < -max_age_seconds * 1000:
        return False
    raw = method.encode() + url.encode() + raw_body + timestamp_header.encode()
    expected = base64.b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)


def _lower(headers: dict[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


def _required_target_url() -> str:
    """Return the configured webhook URL or raise. The URL must match what
    HubSpot signed against, so we never reconstruct it from request headers.
    """
    url = os.environ.get("HUBSPOT_WEBHOOK_TARGET_URL", "").strip()
    if not url:
        raise _ConfigError("HUBSPOT_WEBHOOK_TARGET_URL is not configured")
    return url


_UPDATE_PROPERTIES: frozenset[str] = frozenset(
    {"amount", "closedate", "dealname", "description"}
)


def _route_event(ev: Any) -> str:
    """Decide whether an event belongs on the submit queue or update queue.

    Returns "submit" for dealstage transitions, "update" for content
    property changes, or "drop" for events we do not act on.
    """
    if not isinstance(ev, dict):
        return "drop"
    if ev.get("subscriptionType") != "object.propertyChange":
        return "drop"
    prop = ev.get("propertyName")
    if prop == "dealstage":
        return "submit"
    if prop in _UPDATE_PROPERTIES:
        return "update"
    if isinstance(prop, str) and prop.startswith("govwin_ace_"):
        # ACE manual fields (delivery model, partner need): treat as update
        # so the submission picks up the latest values.
        return "update"
    return "drop"


def _send_sqs_batches(queue_url: str, events: list[Any]) -> int:
    """Enqueue events using SendMessageBatch (10 per call). Returns count sent."""
    if not events:
        return 0
    assert _sqs_client is not None
    sent = 0
    for offset in range(0, len(events), SQS_BATCH_SIZE):
        chunk = events[offset : offset + SQS_BATCH_SIZE]
        entries = [
            {
                "Id": str(offset + i),
                "MessageBody": json.dumps(ev),
                "MessageAttributes": {
                    "subscriptionType": {
                        "DataType": "String",
                        "StringValue": str(
                            (ev or {}).get("subscriptionType", "unknown")
                            if isinstance(ev, dict)
                            else "unknown"
                        ),
                    }
                },
            }
            for i, ev in enumerate(chunk)
        ]
        try:
            response = _sqs_client.send_message_batch(QueueUrl=queue_url, Entries=entries)
            sent += len(response.get("Successful", []))
            failed = response.get("Failed", [])
            if failed:
                logger.warning("sqs batch had %d failed entries", len(failed))
        except ClientError as exc:
            logger.exception("send_message_batch failed: %s", exc)
    return sent


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Gateway HTTP API -> Lambda integration entry point."""
    config = load_config()
    _ensure_clients(config.aws.region)
    headers = _lower(event.get("headers"))
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "POST"
    ).upper()

    if method != "POST":
        return {"statusCode": 405, "body": "Method Not Allowed"}

    raw_body_str = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body_str)
    else:
        raw_body = raw_body_str.encode("utf-8")

    if len(raw_body) > MAX_BODY_BYTES:
        logger.warning("hubspot webhook rejected: body %d bytes exceeds cap", len(raw_body))
        return {"statusCode": 413, "body": "payload too large"}

    signature = headers.get("x-hubspot-signature-v3", "")
    timestamp = headers.get("x-hubspot-request-timestamp", "")
    if not signature or not timestamp:
        logger.warning("hubspot webhook rejected: missing signature/timestamp headers")
        return {"statusCode": 401, "body": "missing signature"}

    try:
        target_url = _required_target_url()
        secret = _get_signing_secret(config.aws.hubspot_webhook_secret_name)
    except _ConfigError as exc:
        logger.error("hubspot webhook config error: %s", exc)
        return {"statusCode": 500, "body": "misconfigured"}
    except ClientError as exc:
        logger.error("Failed to fetch webhook signing secret: %s", exc)
        return {"statusCode": 500, "body": "secret unavailable"}

    if not _validate_signature(
        method=method,
        url=target_url,
        raw_body=raw_body,
        signature_header=signature,
        timestamp_header=timestamp,
        secret=secret,
        max_age_seconds=config.ace.webhook_max_age_seconds,
    ):
        logger.warning("hubspot webhook rejected: signature mismatch")
        return {"statusCode": 401, "body": "invalid signature"}

    submit_queue = config.aws.ace_submission_queue_url
    update_queue = config.aws.ace_update_queue_url
    if not submit_queue or not update_queue:
        logger.error("ACE submission/update queue URLs are not configured")
        return {"statusCode": 500, "body": "misconfigured"}

    try:
        events = json.loads(raw_body.decode("utf-8")) if raw_body else []
    except json.JSONDecodeError:
        logger.warning("hubspot webhook rejected: invalid JSON body")
        return {"statusCode": 400, "body": "invalid json"}
    if not isinstance(events, list):
        events = [events]

    if len(events) > MAX_EVENTS_PER_DELIVERY:
        logger.warning("hubspot webhook rejected: %d events exceeds cap", len(events))
        return {"statusCode": 413, "body": "too many events"}

    submit_events: list[Any] = []
    update_events: list[Any] = []
    dropped = 0
    for ev in events:
        target = _route_event(ev)
        if target == "submit":
            submit_events.append(ev)
        elif target == "update":
            update_events.append(ev)
        else:
            dropped += 1

    enqueued_submit = _send_sqs_batches(submit_queue, submit_events)
    enqueued_update = _send_sqs_batches(update_queue, update_events)
    logger.info(
        "hubspot webhook accepted: submit=%d update=%d dropped=%d",
        enqueued_submit,
        enqueued_update,
        dropped,
    )
    return {
        "statusCode": 200,
        "body": json.dumps(
            {"submit": enqueued_submit, "update": enqueued_update, "dropped": dropped}
        ),
    }
