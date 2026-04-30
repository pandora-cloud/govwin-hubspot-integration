# HubSpot private app webhooks

> Synthesized from https://developers.hubspot.com/docs/guides/crm/private-apps/webhooks and https://developers.hubspot.com/docs/apps/legacy-apps/authentication/validating-requests captured 2026-04-28.

## Why we use them

To know when a HubSpot deal is "ready for ACE submission" — i.e. when BD has filled in the three manual fields and changed the deal stage to "Submit to AWS" — we need a real-time push from HubSpot. Webhooks are the only practical way to do this without polling.

This is in addition to (not replacing) the existing scheduled GovWin → HubSpot sync. The new flow:

```
BD edits deal in HubSpot → HubSpot webhook fires →
  API Gateway endpoint → Lambda validates signature →
    Lambda enqueues to SQS → Step Function processes →
      ACE Lambdas call CreateOpportunity / Associate / StartEngagement
```

## Setup mechanics

HubSpot private apps register webhook subscriptions in two ways:

1. **Via the HubSpot admin UI** — convenient for one-off setup; not reproducible
2. **Via the developer API** at `POST /webhooks/v3/{appId}/settings` and `POST /webhooks/v3/{appId}/subscriptions` — IaC-friendly; we'll use this

We'll add a one-shot setup Lambda (analogous to `setup_hubspot.py`) that creates the webhook subscriptions on deploy:

```python
# Conceptual; full code in src/lambdas/setup_ace_webhooks.py
client.post(
    f"/webhooks/v3/{APP_ID}/settings",
    json={
        "targetUrl": API_GATEWAY_URL,
        "throttling": {"period": "SECONDLY", "maxConcurrentRequests": 10},
    },
)
client.post(
    f"/webhooks/v3/{APP_ID}/subscriptions",
    json={
        "subscriptionDetails": {
            "subscriptionType": "deal.propertyChange",
            "propertyName": "dealstage",
        },
        "active": True,
    },
)
```

## Subscription types relevant to this project

| Subscription | Trigger | Used for |
|---|---|---|
| `deal.propertyChange` (filtered to `dealstage`) | When a deal moves between pipeline stages | Detect "ready to submit to AWS" stage transition |
| `deal.propertyChange` (filtered to `govwin_ace_delivery_model`, `govwin_ace_partner_need`) | BD fills in the three manual ACE fields | Optional: pre-validate before stage transition |
| `deal.propertyChange` (filtered to `amount`, `closedate`, `dealname`) | Material deal updates | Sync changes back to AWS via `UpdateOpportunity` |

## Payload schema

Webhook events arrive as JSON arrays (HubSpot batches up to ~100 events per delivery):

```json
[
  {
    "appId": 123456,
    "eventId": 7891011,
    "subscriptionId": 12131415,
    "portalId": 12345678,
    "occurredAt": 1714355200000,
    "subscriptionType": "deal.propertyChange",
    "attemptNumber": 0,
    "objectId": 323002366678,
    "propertyName": "dealstage",
    "propertyValue": "submit_to_aws",
    "changeSource": "CRM_UI",
    "isSensitive": false
  }
]
```

`objectId` is the HubSpot deal ID. We use that to fetch the full deal via `GET /crm/v3/objects/deals/{objectId}` (the existing HubSpot client supports this).

## Signature validation (X-HubSpot-Signature-v3)

Every webhook delivery includes two headers:

- `X-HubSpot-Signature-v3`: base64-encoded HMAC-SHA256
- `X-HubSpot-Request-Timestamp`: epoch milliseconds

To validate:

1. **Reject if timestamp > 5 minutes old** (defends against replay)
2. Build a UTF-8 string: `<HTTP method> + <URL> + <body> + <timestamp>`
3. Compute HMAC-SHA256 with the **HubSpot client secret** as key
4. Base64-encode the result
5. Compare to the header (constant-time comparison)

```python
import base64, hashlib, hmac, time

def validate_webhook(method: str, url: str, body: bytes, headers: dict, secret: str) -> bool:
    sig = headers.get("X-HubSpot-Signature-v3")
    ts = headers.get("X-HubSpot-Request-Timestamp")
    if not sig or not ts:
        return False
    # Reject anything older than 5 minutes
    if abs(time.time() * 1000 - int(ts)) > 5 * 60 * 1000:
        return False
    raw = method.encode() + url.encode() + body + ts.encode()
    expected = base64.b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, sig)
```

## Common pitfalls

1. **JSON whitespace.** HubSpot signs the raw body byte-for-byte. Python's `json.dumps()` adds spaces by default; if you re-serialize before signing, the signature won't match. Always sign over the **received raw bytes**.
2. **Case-sensitive header names.** API Gateway lowercases headers; AWS Lambda receives them in `event['headers']` already lowercased. Use `.get('x-hubspot-signature-v3')`.
3. **URL encoding.** The URL string used in the signature must match exactly what HubSpot sees as the `targetUrl` — no path normalization, no query-string reordering.

## Retry policy and timeout

- Endpoint must respond `200 OK` within **5 seconds** (HubSpot's documented limit)
- Failed deliveries (non-2xx, timeout, signature mismatch) are retried with exponential backoff over **24 hours**
- After 24 hours the event is dropped and you'll get an alert in the HubSpot app

The standard pattern: API Gateway → Lambda authorizer (signature check) → Lambda → enqueue SQS → respond 200 immediately. Process the SQS message asynchronously so timeout-sensitive work happens off the webhook critical path.

## Throttling

HubSpot enforces 10 concurrent requests per app by default. Adjustable in webhook settings. For this project the default is fine.

## Authentication context note

The webhook payload doesn't include a Bearer token; signature validation is the auth mechanism. After a valid webhook event is received, the receiving Lambda uses the **regular private-app token** (same one already used for HubSpot REST calls) to fetch the full deal record from the CRM API.
