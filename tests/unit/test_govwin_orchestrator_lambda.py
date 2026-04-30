"""Tests for the v2.1 govwin_orchestrator Lambda.

Covers the marked-version path (default discovery), the date-range path
(cursor advance), filter -> batch -> SQS fan-out wiring, and the
misconfigured-queue short-circuit.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from src.lambdas import govwin_orchestrator
from src.models import GovWinOpportunity


def _opp(opp_id: str) -> GovWinOpportunity:
    return GovWinOpportunity.model_validate(
        {
            "id": opp_id,
            "title": f"Opp {opp_id}",
            "status": "Pre-RFP",
            "updateDate": "2026-04-01T00:00:00Z",
        }
    )


def _setup_client(monkeypatch, opportunities: list[GovWinOpportunity]) -> MagicMock:
    """Replace GovWinClient with a context manager returning a mock with the given results."""
    client = MagicMock()
    client.get_all_marked_opportunities.return_value = opportunities
    client.search_all_opportunities.return_value = opportunities
    client.rate_limiter.calls_in_window = len(opportunities)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(
        govwin_orchestrator, "GovWinClient", lambda *_a, **_kw: client
    )
    return client


def _setup_state(monkeypatch, *, last_sync: str | None = None) -> MagicMock:
    state = MagicMock()
    state.get_last_sync_timestamp.return_value = last_sync
    monkeypatch.setattr(
        govwin_orchestrator, "SyncStateManager", lambda *_a, **_kw: state
    )
    return state


def _setup_sqs(monkeypatch) -> MagicMock:
    sqs = MagicMock()
    monkeypatch.setattr(govwin_orchestrator, "_ensure_sqs", lambda *_a, **_kw: sqs)
    govwin_orchestrator._sqs_client = None
    return sqs


def _filter_passthrough(monkeypatch) -> None:
    monkeypatch.setattr(
        govwin_orchestrator,
        "filter_changed_opportunities",
        lambda opps, _state: opps,
    )


def _auth_passthrough(monkeypatch) -> None:
    monkeypatch.setattr(govwin_orchestrator, "GovWinAuth", lambda *_a, **_kw: MagicMock())


def test_misconfigured_queue_returns_status(monkeypatch):
    monkeypatch.delenv("GOVWIN_SYNC_QUEUE_URL", raising=False)
    result = govwin_orchestrator.handler({}, None)
    assert result == {"status": "misconfigured"}


def test_marked_version_path_fans_out_to_sqs(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_orchestrator, "load_config", lambda: app_config)
    monkeypatch.setenv(
        "GOVWIN_SYNC_QUEUE_URL", "https://sqs/test"
    )
    _auth_passthrough(monkeypatch)
    state = _setup_state(monkeypatch)
    _filter_passthrough(monkeypatch)
    sqs = _setup_sqs(monkeypatch)
    opps = [_opp(f"OPP{i}") for i in range(25)]
    client = _setup_client(monkeypatch, opps)

    result = govwin_orchestrator.handler({}, None)

    # Default batch_size=10 -> 3 batches.
    assert result["status"] == "ok"
    assert result["discovered_total"] == 25
    assert result["discovered_changed"] == 25
    assert result["batches_enqueued"] == 3
    assert client.get_all_marked_opportunities.called
    assert sqs.send_message.call_count == 3
    # Marked-version mode does not advance the cursor.
    state.set_last_sync_timestamp.assert_not_called()

    body = json.loads(sqs.send_message.call_args_list[0].kwargs["MessageBody"])
    assert "opportunity_batch" in body
    assert all("id" in entry for entry in body["opportunity_batch"])


def test_date_range_path_does_not_advance_cursor_eagerly(
    monkeypatch, app_config, mock_aws_env
):
    """The orchestrator must NOT advance the global SYNC_CURSOR row when it
    dispatches batches. Per-opp watermarks (written by the worker after a
    successful sync) are the source of truth; advancing the global cursor
    eagerly would silently lose un-synced opportunities when a worker DLQs
    after exhausting redeliveries.
    """
    cfg = app_config
    object.__setattr__(cfg.govwin, "marked_version", "")  # disable marked-version branch
    monkeypatch.setattr(govwin_orchestrator, "load_config", lambda: cfg)
    monkeypatch.setenv("GOVWIN_SYNC_QUEUE_URL", "https://sqs/test")
    _auth_passthrough(monkeypatch)
    state = _setup_state(monkeypatch, last_sync="04/01/2026")
    _filter_passthrough(monkeypatch)
    _setup_sqs(monkeypatch)
    _setup_client(monkeypatch, [_opp("OPP1")])

    result = govwin_orchestrator.handler({}, None)

    assert result["status"] == "ok"
    assert result["batches_enqueued"] == 1
    state.set_last_sync_timestamp.assert_not_called()


def test_empty_marked_results_short_circuits_no_sqs(
    monkeypatch, app_config, mock_aws_env
):
    monkeypatch.setattr(govwin_orchestrator, "load_config", lambda: app_config)
    monkeypatch.setenv("GOVWIN_SYNC_QUEUE_URL", "https://sqs/test")
    _auth_passthrough(monkeypatch)
    _setup_state(monkeypatch)
    _filter_passthrough(monkeypatch)
    sqs = _setup_sqs(monkeypatch)
    _setup_client(monkeypatch, [])

    result = govwin_orchestrator.handler({}, None)

    assert result["batches_enqueued"] == 0
    assert sqs.send_message.call_count == 0


def test_sqs_failure_logged_and_other_batches_continue(
    monkeypatch, app_config, mock_aws_env, caplog
):
    from botocore.exceptions import ClientError

    monkeypatch.setattr(govwin_orchestrator, "load_config", lambda: app_config)
    monkeypatch.setenv("GOVWIN_SYNC_QUEUE_URL", "https://sqs/test")
    _auth_passthrough(monkeypatch)
    _setup_state(monkeypatch)
    _filter_passthrough(monkeypatch)
    sqs = _setup_sqs(monkeypatch)

    # 20 opps -> 2 batches with default batch_size=10. Fail the first SendMessage.
    err = ClientError({"Error": {"Code": "ServiceUnavailable"}}, "SendMessage")
    sqs.send_message.side_effect = [err, {"MessageId": "ok"}]
    _setup_client(monkeypatch, [_opp(f"OPP{i}") for i in range(20)])

    with caplog.at_level("ERROR"):
        result = govwin_orchestrator.handler({}, None)
    assert result["batches_enqueued"] == 1
    assert any("sqs.send_message failed" in r.message for r in caplog.records)


def test_batch_serialization_drops_entries_without_id(
    monkeypatch, app_config, mock_aws_env
):
    monkeypatch.setattr(govwin_orchestrator, "load_config", lambda: app_config)
    monkeypatch.setenv("GOVWIN_SYNC_QUEUE_URL", "https://sqs/test")
    _auth_passthrough(monkeypatch)
    _setup_state(monkeypatch)
    _filter_passthrough(monkeypatch)
    sqs = _setup_sqs(monkeypatch)

    bad = MagicMock()
    bad.id = None
    bad.update_date = "2026-04-01"
    good = _opp("OPP1")
    _setup_client(monkeypatch, [bad, good])

    result = govwin_orchestrator.handler({}, None)
    assert result["batches_enqueued"] == 1
    body: dict[str, Any] = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    ids = [e["id"] for e in body["opportunity_batch"]]
    assert ids == ["OPP1"]


@patch.object(govwin_orchestrator, "boto3")
def test_ensure_sqs_caches_client(boto3_mod, monkeypatch):
    govwin_orchestrator._sqs_client = None
    boto3_mod.client.return_value = MagicMock()
    a = govwin_orchestrator._ensure_sqs("us-east-1")
    b = govwin_orchestrator._ensure_sqs("us-east-1")
    assert a is b
    assert boto3_mod.client.call_count == 1
