"""End-to-end failure-path verification.

Confirms that the DLQ + SNS + EventBridge dedup paths actually fire when
abuse / malformed input / synthetic events land in the system. Run this
before flipping ``ace_catalog`` to ``AWS`` and after any change to the
monitoring stack.

Usage::

    PYTHONPATH=. .venv/bin/python scripts/fault_inject.py --suite all
    PYTHONPATH=. .venv/bin/python scripts/fault_inject.py --suite dlq
    PYTHONPATH=. .venv/bin/python scripts/fault_inject.py --suite webhook
    PYTHONPATH=. .venv/bin/python scripts/fault_inject.py --suite eventbridge
    PYTHONPATH=. .venv/bin/python scripts/fault_inject.py --suite sns

Required env vars:
    SYNC_STATE_TABLE              DynamoDB sync-state table (for EventBridge dedup)
    ENTITY_MAPPINGS_TABLE         DynamoDB entity-mappings table
    HUBSPOT_WEBHOOK_TARGET_URL    Public API Gateway URL for the webhook receiver
    GOVWIN_SYNC_QUEUE_URL         SQS URL for the GovWin sync queue (to inject malformed messages)
    SNS_TOPIC_ARN                 (optional) SNS topic to subscribe a probe to

Each suite is independently runnable. Each prints PASS or FAIL with the
relevant resource ARN / message ID so a failure points directly at the
broken hop.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any

import httpx

from src.aws_clients import make_client


def _print(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {label}"
    if detail:
        line += f" :: {detail}"
    print(line, flush=True)


def suite_dlq(args: argparse.Namespace) -> int:
    """Inject a malformed SQS message and confirm it lands in the DLQ."""
    queue_url = os.environ["GOVWIN_SYNC_QUEUE_URL"]
    sqs = make_client("sqs", os.environ.get("AWS_REGION", "us-east-1"))

    # A message the worker cannot deserialize; SQS will retry up to maxReceiveCount,
    # then the redrive policy moves it to the DLQ.
    body = json.dumps({"intentionally": "malformed", "fault_inject": str(uuid.uuid4())})
    sqs.send_message(QueueUrl=queue_url, MessageBody=body)
    _print("dlq:inject malformed message", True, f"queue={queue_url}")

    print("    Waiting up to 90s for the message to exhaust retries and land in DLQ...")
    deadline = time.time() + 90
    dlq_url = queue_url.rstrip("/") + "-dlq"
    # The actual DLQ is named via the redrive policy; query SQS for it directly.
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["RedrivePolicy"])
    redrive = json.loads(attrs.get("Attributes", {}).get("RedrivePolicy", "{}"))
    dlq_arn = redrive.get("deadLetterTargetArn", "")
    if not dlq_arn:
        _print("dlq:redrive policy missing", False, "no DLQ configured on queue")
        return 1
    dlq_name = dlq_arn.rsplit(":", 1)[-1]
    dlq_url = sqs.get_queue_url(QueueName=dlq_name)["QueueUrl"]

    while time.time() < deadline:
        attrs = sqs.get_queue_attributes(
            QueueUrl=dlq_url, AttributeNames=["ApproximateNumberOfMessages"]
        )
        depth = int(attrs.get("Attributes", {}).get("ApproximateNumberOfMessages", "0"))
        if depth > 0:
            _print("dlq:message reached DLQ", True, f"queue={dlq_name}, depth={depth}")
            return 0
        time.sleep(5)
    _print("dlq:message reached DLQ", False, "DLQ remained empty after 90s")
    return 1


def suite_webhook(args: argparse.Namespace) -> int:
    """Send a forged-signature request and confirm 401."""
    url = os.environ["HUBSPOT_WEBHOOK_TARGET_URL"]
    body = json.dumps([{"objectId": 999, "subscriptionType": "object.propertyChange"}])
    headers = {
        "X-HubSpot-Signature-v3": "obviously-not-a-real-signature",
        "X-HubSpot-Request-Timestamp": str(int(time.time() * 1000)),
        "Content-Type": "application/json",
    }
    resp = httpx.post(url, content=body, headers=headers, timeout=10)
    if resp.status_code == 401:
        _print("webhook:forged signature returns 401", True, f"url={url}")
        return 0
    _print(
        "webhook:forged signature returns 401",
        False,
        f"got {resp.status_code} (expected 401); body={resp.text[:200]}",
    )
    return 1


def suite_eventbridge(args: argparse.Namespace) -> int:
    """Confirm the EventBridge dedup table accepts a synthetic seen event."""
    from src.config import load_config
    from src.sync.state import SyncStateManager

    config = load_config()
    state = SyncStateManager(config)
    event_id = f"fault-inject-{uuid.uuid4()}"
    first = state.mark_event_seen(event_id)
    second = state.mark_event_seen(event_id)
    if first and not second:
        _print("eventbridge:dedup first-call true, second false", True, f"event_id={event_id}")
        return 0
    _print(
        "eventbridge:dedup first-call true, second false",
        False,
        f"first={first}, second={second}",
    )
    return 1


def suite_sns(args: argparse.Namespace) -> int:
    """Publish a probe message to the configured SNS topic."""
    topic_arn = os.environ.get("SNS_TOPIC_ARN", "")
    if not topic_arn:
        _print("sns:topic configured", False, "SNS_TOPIC_ARN env var not set")
        return 1
    sns = make_client("sns", os.environ.get("AWS_REGION", "us-east-1"))
    response = sns.publish(
        TopicArn=topic_arn,
        Subject="[fault-inject] probe message"[:100],
        Message="This is a fault-injection probe. If you are receiving this, your SNS subscription works.",
    )
    _print(
        "sns:probe published",
        bool(response.get("MessageId")),
        f"topic={topic_arn}, message_id={response.get('MessageId')}",
    )
    return 0


SUITES = {
    "dlq": suite_dlq,
    "webhook": suite_webhook,
    "eventbridge": suite_eventbridge,
    "sns": suite_sns,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=[*SUITES.keys(), "all"],
        default="all",
    )
    args = parser.parse_args()

    suites = SUITES.values() if args.suite == "all" else [SUITES[args.suite]]
    failures = 0
    for fn in suites:
        try:
            failures += fn(args)
        except Exception as exc:  # noqa: BLE001 - we want every suite to keep going
            _print(f"{fn.__name__}:exception", False, str(exc))
            failures += 1
    if failures:
        print(f"\n{failures} suite(s) failed.")
        return 1
    print("\nAll fault-injection suites passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
