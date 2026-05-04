"""Synthesize a HubSpot ``X-HubSpot-Signature-v3`` for offline testing.

HubSpot signs every webhook delivery with HMAC-SHA256 over
``method + url + body + timestamp``, base64-encoded, using the developer-
platform app's ``clientSecret`` as the key. Reproducing that here lets us:

* unit-test ``hubspot_webhook_receiver._validate_signature`` against a
  signature we computed ourselves, without spinning up real HubSpot;
* drive end-to-end smoke tests (``scripts/sandbox_smoke.py`` and
  ``scripts/fault_inject.py``) without a live HubSpot account.

The signing recipe and constant-time comparison live in
``src/lambdas/hubspot_webhook_receiver.py``; this module is the inverse,
producing the value the receiver expects to see.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Final

# Per HubSpot's published spec.
SIGNATURE_HEADER: Final[str] = "X-HubSpot-Signature-v3"
TIMESTAMP_HEADER: Final[str] = "X-HubSpot-Request-Timestamp"


def now_ms() -> int:
    """Current Unix time in milliseconds (HubSpot's timestamp format)."""
    return int(time.time() * 1000)


def sign(
    *,
    method: str,
    url: str,
    body: bytes,
    secret: str,
    timestamp_ms: int | None = None,
) -> str:
    """Return the base64-encoded HMAC-SHA256 over method + url + body + ts.

    :param method: HTTP method as it arrives at the receiver (typically ``POST``).
    :param url: full URL HubSpot delivered to (must include scheme + host + path).
    :param body: raw request body bytes (the receiver compares against the
        unparsed body, so pass the exact bytes the wire carries).
    :param secret: developer-platform app's ``clientSecret``.
    :param timestamp_ms: defaults to :func:`now_ms`. Override to test the
        replay-window rejection branch.
    :returns: a string suitable for the ``X-HubSpot-Signature-v3`` header.
    """
    ts = str(timestamp_ms if timestamp_ms is not None else now_ms())
    raw = method.encode() + url.encode() + body + ts.encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@dataclass(frozen=True)
class SignedRequest:
    """A pre-signed request envelope ready to feed to the receiver Lambda.

    All fields are strings (not bytes) because that is the shape the
    Lambda's API Gateway proxy event uses.
    """

    method: str
    url: str
    body: str
    headers: dict[str, str]


def signed_request(
    *,
    method: str = "POST",
    url: str,
    body: str,
    secret: str,
    timestamp_ms: int | None = None,
    extra_headers: dict[str, str] | None = None,
) -> SignedRequest:
    """Build a :class:`SignedRequest` with the signature + timestamp headers
    already populated. Convenient for end-to-end test assertions like::

        req = signed_request(url=..., body=..., secret=...)
        response = receiver.handler({
            "requestContext": {"http": {"method": req.method}},
            "rawPath": ...,
            "headers": req.headers,
            "body": req.body,
        }, context=None)
    """
    body_bytes = body.encode()
    ts_ms = timestamp_ms if timestamp_ms is not None else now_ms()
    sig = sign(
        method=method,
        url=url,
        body=body_bytes,
        secret=secret,
        timestamp_ms=ts_ms,
    )
    headers: dict[str, str] = {
        SIGNATURE_HEADER: sig,
        TIMESTAMP_HEADER: str(ts_ms),
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    return SignedRequest(method=method, url=url, body=body, headers=headers)
