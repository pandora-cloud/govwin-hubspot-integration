"""Tests for the HubSpot webhook receiver Lambda."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from src.lambdas import hubspot_webhook_receiver as receiver

SECRET = "topsecret"
TARGET_URL = "https://api.example.com/hubspot"


def _signed_headers(method: str, url: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time() * 1000))
    raw = method.encode() + url.encode() + body + ts.encode()
    sig = base64.b64encode(
        hmac.new(SECRET.encode(), raw, hashlib.sha256).digest()
    ).decode()
    return {
        "x-hubspot-signature-v3": sig,
        "x-hubspot-request-timestamp": ts,
    }


def _api_event(method: str, body: str, headers: dict[str, str]) -> dict:
    return {
        "requestContext": {
            "http": {"method": method, "path": "/hubspot"},
            "domainName": "api.example.com",
        },
        "rawPath": "/hubspot",
        "headers": headers,
        "body": body,
        "isBase64Encoded": False,
    }


@pytest.fixture(autouse=True)
def _reset_secret_cache():
    receiver._secret_cache.clear()
    yield
    receiver._secret_cache.clear()


@pytest.fixture
def mock_clients() -> tuple[MagicMock, MagicMock]:
    secrets = MagicMock()
    secrets.get_secret_value.return_value = {
        "SecretString": json.dumps({"client_secret": SECRET})
    }
    sqs = MagicMock()
    with patch.object(receiver, "_secrets_client", secrets), \
         patch.object(receiver, "_sqs_client", sqs), \
         patch.object(receiver, "_ensure_clients", lambda *_: None):
        yield secrets, sqs


@pytest.fixture
def mock_secrets(mock_clients) -> MagicMock:
    return mock_clients[0]


@pytest.fixture
def mock_sqs(mock_clients) -> MagicMock:
    return mock_clients[1]


@pytest.fixture(autouse=True)
def _config_target_url(monkeypatch):
    monkeypatch.setenv("HUBSPOT_WEBHOOK_TARGET_URL", TARGET_URL)
    monkeypatch.setenv("HUBSPOT_WEBHOOK_SECRET_NAME", "test/hubspot-webhook")
    monkeypatch.setenv(
        "ACE_SUBMISSION_QUEUE_URL",
        "https://sqs.us-east-1.amazonaws.com/000000000000/test-ace-submit",
    )


def test_valid_signature_returns_200(mock_secrets, mock_sqs) -> None:
    body = json.dumps([{"objectId": 1, "subscriptionType": "deal.propertyChange"}])
    headers = _signed_headers("POST", TARGET_URL, body.encode())
    response = receiver.handler(_api_event("POST", body, headers), context=None)
    assert response["statusCode"] == 200
    assert mock_sqs.send_message.call_count == 1


def test_missing_signature_rejected(mock_secrets, mock_sqs) -> None:
    body = "[]"
    response = receiver.handler(_api_event("POST", body, {}), context=None)
    assert response["statusCode"] == 401
    assert mock_sqs.send_message.call_count == 0


def test_signature_mismatch_rejected(mock_secrets, mock_sqs) -> None:
    body = "[{}]"
    headers = _signed_headers("POST", TARGET_URL, body.encode())
    headers["x-hubspot-signature-v3"] = "tampered"
    response = receiver.handler(_api_event("POST", body, headers), context=None)
    assert response["statusCode"] == 401


def test_replay_old_timestamp_rejected(mock_secrets, mock_sqs) -> None:
    body = "[]"
    old_ts = str(int((time.time() - 10 * 60) * 1000))
    raw = b"POST" + TARGET_URL.encode() + body.encode() + old_ts.encode()
    sig = base64.b64encode(
        hmac.new(SECRET.encode(), raw, hashlib.sha256).digest()
    ).decode()
    headers = {
        "x-hubspot-signature-v3": sig,
        "x-hubspot-request-timestamp": old_ts,
    }
    response = receiver.handler(_api_event("POST", body, headers), context=None)
    assert response["statusCode"] == 401


def test_non_post_method_rejected(mock_secrets, mock_sqs) -> None:
    response = receiver.handler(_api_event("GET", "[]", {}), context=None)
    assert response["statusCode"] == 405


def test_invalid_json_body_rejected(mock_secrets, mock_sqs) -> None:
    body = "{not json"
    headers = _signed_headers("POST", TARGET_URL, body.encode())
    response = receiver.handler(_api_event("POST", body, headers), context=None)
    assert response["statusCode"] == 400


def test_multiple_events_enqueue_separately(mock_secrets, mock_sqs) -> None:
    body = json.dumps([
        {"objectId": 1, "subscriptionType": "deal.propertyChange"},
        {"objectId": 2, "subscriptionType": "deal.propertyChange"},
    ])
    headers = _signed_headers("POST", TARGET_URL, body.encode())
    response = receiver.handler(_api_event("POST", body, headers), context=None)
    assert response["statusCode"] == 200
    assert mock_sqs.send_message.call_count == 2
