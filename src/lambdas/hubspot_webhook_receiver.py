"""Receive HubSpot webhook deliveries, validate the signature, and enqueue.

Triggered by API Gateway HTTP API. Signs validation headers per
``X-HubSpot-Signature-v3`` and pushes the raw body onto SQS for asynchronous
processing. Must respond within the documented 5-second budget so the heavy
lifting (CreateOpportunity, AssociateOpportunity, etc.) happens off the
webhook critical path.
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


_secrets_client: Any | None = None
_sqs_client: Any | None = None
_secret_cache: dict[str, str] = {}


def _ensure_clients(region: str) -> None:
    """Lazy-initialize boto3 clients (avoids no-region errors at import time)."""
    global _secrets_client, _sqs_client
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager", region_name=region)
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs", region_name=region)


def _get_signing_secret(secret_name: str) -> str:
    """Cache the signing secret for the lifetime of the warm Lambda container."""
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]
    assert _secrets_client is not None
    response = _secrets_client.get_secret_value(SecretId=secret_name)
    raw = response.get("SecretString", "{}")
    try:
        parsed = json.loads(raw)
        secret = parsed.get("client_secret") or parsed.get("clientSecret") or raw
    except json.JSONDecodeError:
        secret = raw
    _secret_cache[secret_name] = secret
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
    if abs(time.time() * 1000 - ts_ms) > max_age_seconds * 1000:
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


def _build_target_url(event: dict[str, Any]) -> str:
    """Reconstruct the URL HubSpot used so the signature payload matches.

    We honor ``HUBSPOT_WEBHOOK_TARGET_URL`` first because API Gateway behind a
    custom domain may report a different host than HubSpot saw.
    """
    override = os.environ.get("HUBSPOT_WEBHOOK_TARGET_URL")
    if override:
        return override
    request_context = event.get("requestContext", {})
    domain = request_context.get("domainName", "")
    path = event.get("rawPath") or request_context.get("http", {}).get("path", "/")
    return f"https://{domain}{path}"


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

    signature = headers.get("x-hubspot-signature-v3", "")
    timestamp = headers.get("x-hubspot-request-timestamp", "")
    if not signature or not timestamp:
        logger.warning("hubspot webhook rejected: missing signature/timestamp headers")
        return {"statusCode": 401, "body": "missing signature"}

    secret_name = config.aws.hubspot_webhook_secret_name
    try:
        secret = _get_signing_secret(secret_name)
    except ClientError as exc:
        logger.error("Failed to fetch webhook signing secret: %s", exc)
        return {"statusCode": 500, "body": "secret unavailable"}

    target_url = _build_target_url(event)
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

    queue_url = config.aws.ace_submission_queue_url
    if not queue_url:
        logger.error("ACE_SUBMISSION_QUEUE_URL is not configured")
        return {"statusCode": 500, "body": "misconfigured"}

    try:
        events = json.loads(raw_body.decode("utf-8")) if raw_body else []
    except json.JSONDecodeError:
        logger.warning("hubspot webhook rejected: invalid JSON body")
        return {"statusCode": 400, "body": "invalid json"}
    if not isinstance(events, list):
        events = [events]

    assert _sqs_client is not None
    enqueued = 0
    for hs_event in events:
        try:
            _sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(hs_event),
                MessageAttributes={
                    "subscriptionType": {
                        "DataType": "String",
                        "StringValue": str(hs_event.get("subscriptionType", "unknown")),
                    }
                },
            )
            enqueued += 1
        except ClientError as exc:
            logger.exception("failed to enqueue hubspot webhook event: %s", exc)

    logger.info("hubspot webhook accepted: enqueued=%d", enqueued)
    return {"statusCode": 200, "body": json.dumps({"enqueued": enqueued})}
