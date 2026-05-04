"""Verify the offline signature fixture matches the receiver's validator.

The fixture in ``tests/fixtures/hubspot_signature.py`` produces signatures
that ``src/lambdas/hubspot_webhook_receiver.py:_validate_signature`` must
accept. If the fixture and the validator ever drift apart (e.g. body
encoding, timestamp format), every test that relies on the fixture breaks
quietly — these tests are the canary.
"""

from __future__ import annotations

import time

from src.lambdas.hubspot_webhook_receiver import _validate_signature
from tests.fixtures.hubspot_signature import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    sign,
    signed_request,
)

_SECRET = "0xCAFEBABE-not-a-real-hubspot-client-secret"
_URL = "https://example.execute-api.us-east-1.amazonaws.com/hubspot"
_MAX_AGE = 300  # match webhook_max_age_seconds default


def test_fixture_signature_validates_positive():
    body = b'[{"objectId":1,"subscriptionType":"object.propertyChange"}]'
    ts_ms = int(time.time() * 1000)
    sig = sign(method="POST", url=_URL, body=body, secret=_SECRET, timestamp_ms=ts_ms)

    assert _validate_signature(
        method="POST",
        url=_URL,
        raw_body=body,
        signature_header=sig,
        timestamp_header=str(ts_ms),
        secret=_SECRET,
        max_age_seconds=_MAX_AGE,
    )


def test_fixture_rejected_with_wrong_secret():
    body = b'{"a":1}'
    ts_ms = int(time.time() * 1000)
    sig = sign(method="POST", url=_URL, body=body, secret=_SECRET, timestamp_ms=ts_ms)

    assert not _validate_signature(
        method="POST",
        url=_URL,
        raw_body=body,
        signature_header=sig,
        timestamp_header=str(ts_ms),
        secret="different-secret",
        max_age_seconds=_MAX_AGE,
    )


def test_fixture_rejected_when_body_tampered():
    body = b'{"original":"value"}'
    ts_ms = int(time.time() * 1000)
    sig = sign(method="POST", url=_URL, body=body, secret=_SECRET, timestamp_ms=ts_ms)

    assert not _validate_signature(
        method="POST",
        url=_URL,
        raw_body=b'{"tampered":"value"}',
        signature_header=sig,
        timestamp_header=str(ts_ms),
        secret=_SECRET,
        max_age_seconds=_MAX_AGE,
    )


def test_fixture_rejected_when_timestamp_outside_window():
    body = b'{}'
    # 10 minutes in the past, well outside the 5-minute replay window
    ts_ms = int(time.time() * 1000) - 10 * 60 * 1000
    sig = sign(method="POST", url=_URL, body=body, secret=_SECRET, timestamp_ms=ts_ms)

    assert not _validate_signature(
        method="POST",
        url=_URL,
        raw_body=body,
        signature_header=sig,
        timestamp_header=str(ts_ms),
        secret=_SECRET,
        max_age_seconds=_MAX_AGE,
    )


def test_signed_request_envelope_carries_both_headers():
    req = signed_request(url=_URL, body='{"x":1}', secret=_SECRET)
    assert SIGNATURE_HEADER in req.headers
    assert TIMESTAMP_HEADER in req.headers
    assert req.headers["Content-Type"] == "application/json"
    assert req.body == '{"x":1}'


def test_signed_request_extra_headers_merged():
    req = signed_request(
        url=_URL,
        body="{}",
        secret=_SECRET,
        extra_headers={"X-Trace-Id": "abc-123"},
    )
    assert req.headers["X-Trace-Id"] == "abc-123"
    assert SIGNATURE_HEADER in req.headers
