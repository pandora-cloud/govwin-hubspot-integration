"""One-time Lambda to register HubSpot webhook subscriptions.

Triggered manually after Terraform produces the API Gateway URL. Calls the
HubSpot ``/webhooks/v3/{appId}/settings`` and ``/subscriptions`` endpoints
so the static-auth app starts delivering deal-property webhooks to our
receiver. Idempotent: if a subscription already exists with the same
property name we leave it alone.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from src.config import load_config
from src.hubspot.client import HubSpotClient

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


_SUBSCRIPTIONS: list[dict[str, Any]] = [
    {"subscriptionType": "deal.propertyChange", "propertyName": "dealstage"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "amount"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "closedate"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "dealname"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "govwin_ace_delivery_model"},
    {"subscriptionType": "deal.propertyChange", "propertyName": "govwin_ace_partner_need"},
]


def _load_app_id_secret(secret_name: str) -> dict[str, str]:
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    raw = response.get("SecretString", "{}")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Webhook secret must be a JSON object")
    return parsed


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config()
    target_url = event.get("targetUrl") or os.environ.get("HUBSPOT_WEBHOOK_TARGET_URL")
    if not target_url:
        raise ValueError("targetUrl must be supplied via event or HUBSPOT_WEBHOOK_TARGET_URL")

    secret = _load_app_id_secret(config.aws.hubspot_webhook_secret_name)
    app_id = secret.get("app_id") or secret.get("appId")
    if not app_id:
        raise ValueError("Webhook secret missing app_id field")

    created: list[dict[str, Any]] = []
    with HubSpotClient(config) as hubspot:
        hubspot._post(  # noqa: SLF001 -- private app webhook config endpoint
            f"webhooks/v3/{app_id}/settings",
            {
                "targetUrl": target_url,
                "throttling": {"period": "SECONDLY", "maxConcurrentRequests": 10},
            },
        )
        for sub in _SUBSCRIPTIONS:
            response = hubspot._post(  # noqa: SLF001
                f"webhooks/v3/{app_id}/subscriptions",
                {"subscriptionDetails": sub, "active": True},
            )
            created.append(response)

    logger.info("setup_ace_webhooks: registered %d subscriptions", len(created))
    return {"status": "ok", "subscriptions": created}
