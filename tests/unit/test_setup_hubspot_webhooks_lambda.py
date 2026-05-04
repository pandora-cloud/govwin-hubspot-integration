"""Tests for the setup_hubspot_webhooks Lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.lambdas import setup_hubspot_webhooks


@pytest.fixture
def fake_secret_value() -> dict[str, Any]:
    return {
        "SecretString": json.dumps(
            {"app_id": "12345678", "client_secret": "shhh-not-a-real-secret"}
        )
    }


@pytest.fixture
def fake_secrets_client(fake_secret_value):
    client = MagicMock()
    client.get_secret_value.return_value = fake_secret_value
    return client


def test_handler_dry_run_skips_hubspot_mutations(
    monkeypatch, app_config, fake_secrets_client
):
    """dryRun=True must NOT call configure_webhook_settings or create any
    subscription, but must still resolve the app_id and report what it
    *would* have done.
    """
    monkeypatch.setattr(setup_hubspot_webhooks, "load_config", lambda: app_config)
    monkeypatch.setattr(
        setup_hubspot_webhooks, "make_client", lambda *_a, **_kw: fake_secrets_client
    )
    hubspot_mock = MagicMock()
    hubspot_mock.__enter__.return_value = hubspot_mock
    hubspot_mock.__exit__.return_value = False
    monkeypatch.setattr(
        setup_hubspot_webhooks, "HubSpotClient", lambda _config: hubspot_mock
    )

    event = {
        "targetUrl": "https://example.execute-api.us-east-1.amazonaws.com/hubspot",
        "dryRun": True,
    }
    result = setup_hubspot_webhooks.handler(event, context=None)

    assert result["status"] == "dry-run"
    assert result["app_id"] == "12345678"
    assert result["target_url"].startswith("https://")
    assert len(result["would_register"]) >= 1
    assert all(item["would_activate"] is True for item in result["would_register"])
    hubspot_mock.configure_webhook_settings.assert_not_called()
    hubspot_mock.create_webhook_subscription.assert_not_called()


def test_handler_dry_run_accepts_snake_case_alias(
    monkeypatch, app_config, fake_secrets_client
):
    """dry_run is the documented snake_case alias of dryRun."""
    monkeypatch.setattr(setup_hubspot_webhooks, "load_config", lambda: app_config)
    monkeypatch.setattr(
        setup_hubspot_webhooks, "make_client", lambda *_a, **_kw: fake_secrets_client
    )
    hubspot_mock = MagicMock()
    hubspot_mock.__enter__.return_value = hubspot_mock
    hubspot_mock.__exit__.return_value = False
    monkeypatch.setattr(
        setup_hubspot_webhooks, "HubSpotClient", lambda _config: hubspot_mock
    )

    result = setup_hubspot_webhooks.handler(
        {"targetUrl": "https://x.example.com/hubspot", "dry_run": True},
        context=None,
    )
    assert result["status"] == "dry-run"
    hubspot_mock.create_webhook_subscription.assert_not_called()


def test_handler_rejects_missing_target_url(monkeypatch, app_config):
    monkeypatch.setattr(setup_hubspot_webhooks, "load_config", lambda: app_config)
    monkeypatch.delenv("HUBSPOT_WEBHOOK_TARGET_URL", raising=False)
    with pytest.raises(ValueError, match="targetUrl"):
        setup_hubspot_webhooks.handler({}, context=None)


def test_handler_rejects_non_https_target_url(monkeypatch, app_config):
    monkeypatch.setattr(setup_hubspot_webhooks, "load_config", lambda: app_config)
    with pytest.raises(ValueError, match="https"):
        setup_hubspot_webhooks.handler(
            {"targetUrl": "http://insecure.example.com/hubspot"}, context=None
        )


def test_resolve_app_id_validates_numeric():
    """app_id must be a numeric string (HubSpot's app id format)."""
    assert setup_hubspot_webhooks._resolve_app_id({"app_id": "12345678"}) == "12345678"
    assert setup_hubspot_webhooks._resolve_app_id({"appId": "98765"}) == "98765"
    with pytest.raises(ValueError, match="numeric app_id"):
        setup_hubspot_webhooks._resolve_app_id({"app_id": "not-numeric"})
    with pytest.raises(ValueError, match="numeric app_id"):
        setup_hubspot_webhooks._resolve_app_id({})


@patch.object(setup_hubspot_webhooks, "HubSpotClient")
def test_handler_live_invocation_registers_subscriptions(
    hubspot_cls, monkeypatch, app_config, fake_secrets_client
):
    """Without dryRun, the handler must call create_webhook_subscription
    once per declared subscription and treat HubSpot 409 as success.
    """
    monkeypatch.setattr(setup_hubspot_webhooks, "load_config", lambda: app_config)
    monkeypatch.setattr(
        setup_hubspot_webhooks, "make_client", lambda *_a, **_kw: fake_secrets_client
    )
    hubspot_mock = MagicMock()
    hubspot_mock.__enter__.return_value = hubspot_mock
    hubspot_mock.__exit__.return_value = False
    hubspot_mock.create_webhook_subscription.return_value = {"id": "sub_xyz"}
    hubspot_cls.return_value = hubspot_mock

    result = setup_hubspot_webhooks.handler(
        {"targetUrl": "https://x.example.com/hubspot"}, context=None
    )

    assert result["status"] == "ok"
    hubspot_mock.configure_webhook_settings.assert_called_once()
    assert hubspot_mock.create_webhook_subscription.call_count == len(
        setup_hubspot_webhooks._SUBSCRIPTIONS
    )
