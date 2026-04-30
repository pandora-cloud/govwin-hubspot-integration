"""One-time Lambda to register HubSpot webhook subscriptions.

Triggered manually after Terraform produces the API Gateway URL. Calls the
HubSpot ``/webhooks/v3/{appId}/settings`` and ``/subscriptions`` endpoints
so the static-auth app starts delivering deal-property webhooks to our
receiver. Idempotent: HubSpot's POST to /subscriptions returns 409 for an
existing subscription, which we treat as success.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import load_config
from src.hubspot.client import HubSpotAPIError, HubSpotClient

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# Webhook subscriptions split by purpose:
#   * dealstage triggers initial submission (Submit to AWS stage transition).
#   * amount, closedate, dealname, description trigger UpdateOpportunity
#     for content edits while the opp is still editable.
#   * govwin_ace_use_case triggers UpdateOpportunity for the ACE-only
#     CustomerUseCase override.
#
# We deliberately do NOT subscribe to govwin_ace_partner_need or
# govwin_ace_delivery_model: those are CreateOpportunity-time inputs and
# AWS rejects updates to them after StartEngagementFromOpportunityTask.
_SUBSCRIPTIONS: list[dict[str, Any]] = [
    {"subscriptionType": "deal.propertyChange", "propertyName": "dealstage"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "amount"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "closedate"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "dealname"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "description"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "govwin_ace_use_case"},
]


def _load_app_secret(secret_name: str, region: str) -> dict[str, Any]:
    client = boto3.client("secretsmanager", region_name=region)
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        raise ValueError(f"failed to fetch webhook secret: {exc}") from exc
    raw = response.get("SecretString", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("webhook secret is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("webhook secret must be a JSON object")
    return parsed


def _resolve_app_id(secret: dict[str, Any]) -> str:
    """Validate and return a numeric HubSpot app id from the secret."""
    raw = secret.get("app_id") or secret.get("appId")
    if not isinstance(raw, str) or not raw.isdigit():
        raise ValueError("webhook secret missing numeric app_id field")
    return raw


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config()
    target_url = (
        event.get("targetUrl") or os.environ.get("HUBSPOT_WEBHOOK_TARGET_URL", "")
    ).strip()
    if not target_url:
        raise ValueError("targetUrl must be supplied via event or HUBSPOT_WEBHOOK_TARGET_URL")
    if not target_url.startswith("https://"):
        raise ValueError("targetUrl must be an https URL")

    secret = _load_app_secret(config.aws.hubspot_webhook_secret_name, config.aws.region)
    app_id = _resolve_app_id(secret)

    created: list[dict[str, Any]] = []
    with HubSpotClient(config) as hubspot:
        hubspot.configure_webhook_settings(app_id, target_url)
        for sub in _SUBSCRIPTIONS:
            try:
                response = hubspot.create_webhook_subscription(
                    app_id=app_id, subscription_details=sub, active=True
                )
                created.append(response)
            except HubSpotAPIError as exc:
                if exc.status_code == 409:
                    logger.info("subscription %s already exists", sub.get("propertyName"))
                    continue
                raise

    logger.info("setup_hubspot_webhooks: registered %d subscriptions", len(created))
    return {"status": "ok", "subscriptions": created}
