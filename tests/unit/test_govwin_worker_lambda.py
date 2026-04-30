"""Tests for the v2.1 govwin_worker Lambda.

Covers SQS batch decode, fetch + sync delegation, partial-batch failure
reporting, GovWin rate-limit deferral, invalid-id rejection, and the
SNS terminal-failure alert.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from src.govwin.client import GovWinRateLimitError
from src.lambdas import govwin_worker
from src.models import GovWinOpportunity, GovWinOpportunityBundle


def _bundle(opp_id: str) -> GovWinOpportunityBundle:
    opp = GovWinOpportunity.model_validate(
        {
            "id": opp_id,
            "title": f"Opp {opp_id}",
            "status": "Pre-RFP",
            "updateDate": "2026-04-01T00:00:00Z",
        }
    )
    return GovWinOpportunityBundle(opportunity=opp, contacts=[])


def _record(message_id: str, ids: list[str]) -> dict[str, Any]:
    return {
        "messageId": message_id,
        "body": json.dumps(
            {
                "opportunity_batch": [
                    {"id": i, "updateDate": "2026-04-01T00:00:00Z"} for i in ids
                ]
            }
        ),
    }


def _patch_clients(
    monkeypatch,
    *,
    govwin_bundles: dict[str, GovWinOpportunityBundle | Exception | None] | None = None,
    sync_stats: dict[str, Any] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Replace GovWinClient + HubSpotClient with context-manager mocks."""
    govwin = MagicMock()

    def _bundle_lookup(opp_id: str):
        if govwin_bundles is None:
            return _bundle(opp_id)
        result = govwin_bundles.get(opp_id, _bundle(opp_id))
        if isinstance(result, Exception):
            raise result
        return result

    govwin.get_opportunity_bundle.side_effect = _bundle_lookup
    govwin.__enter__ = MagicMock(return_value=govwin)
    govwin.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(
        govwin_worker, "GovWinClient", lambda *_a, **_kw: govwin
    )
    monkeypatch.setattr(govwin_worker, "GovWinAuth", lambda *_a, **_kw: MagicMock())

    hubspot = MagicMock()
    hubspot.__enter__ = MagicMock(return_value=hubspot)
    hubspot.__exit__ = MagicMock(return_value=None)
    monkeypatch.setattr(
        govwin_worker, "HubSpotClient", lambda *_a, **_kw: hubspot
    )

    monkeypatch.setattr(
        govwin_worker, "SyncStateManager", lambda *_a, **_kw: MagicMock()
    )

    orch = MagicMock()
    orch.sync_opportunity_batch.return_value = sync_stats or {
        "deals_synced": 1,
        "companies_synced": 0,
        "contacts_synced": 0,
        "associations_created": 0,
        "errors": [],
    }
    monkeypatch.setattr(
        govwin_worker, "SyncOrchestrator", lambda **_kw: orch
    )
    return govwin, hubspot


def test_happy_path_no_failures(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    govwin, hubspot = _patch_clients(monkeypatch)
    event = {"Records": [_record("m1", ["OPP1", "OPP2"])]}

    result = govwin_worker.handler(event, None)

    assert result["batchItemFailures"] == []
    assert len(result["results"]) == 1
    hubspot.ensure_pipeline.assert_called_once()
    assert govwin.get_opportunity_bundle.call_count == 2


def test_invalid_opp_id_filtered_into_errors(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    _patch_clients(monkeypatch)
    event = {"Records": [_record("m1", ["lowercase", "OPP1"])]}

    result = govwin_worker.handler(event, None)
    assert result["batchItemFailures"] == []
    stats = result["results"][0]
    assert any("invalid opportunity id" in e for e in stats.get("errors", []))


def test_rate_limit_deferred_as_batch_failure(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    _patch_clients(
        monkeypatch,
        govwin_bundles={"OPP1": GovWinRateLimitError(wait_seconds=60)},
    )
    event = {"Records": [_record("m1", ["OPP1"])]}

    result = govwin_worker.handler(event, None)
    assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]


def test_per_id_fetch_error_recorded_but_does_not_fail_batch(
    monkeypatch, app_config, mock_aws_env
):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    _patch_clients(
        monkeypatch,
        govwin_bundles={
            "OPP1": ValueError("boom"),
            "OPP2": _bundle("OPP2"),
        },
    )
    event = {"Records": [_record("m1", ["OPP1", "OPP2"])]}

    result = govwin_worker.handler(event, None)
    assert result["batchItemFailures"] == []
    stats = result["results"][0]
    assert any("OPP1: ValueError" in e for e in stats.get("errors", []))


def test_no_bundles_skips_orchestrator(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    _patch_clients(monkeypatch, govwin_bundles={"OPP1": None})
    orch_calls: list[Any] = []
    monkeypatch.setattr(
        govwin_worker,
        "SyncOrchestrator",
        lambda **_kw: orch_calls.append("created") or MagicMock(),
    )
    event = {"Records": [_record("m1", ["OPP1"])]}

    result = govwin_worker.handler(event, None)
    assert result["results"][0]["status"] == "no_bundles"
    assert orch_calls == []


def test_invalid_json_dropped_without_retry(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    _patch_clients(monkeypatch)
    event = {"Records": [{"messageId": "m1", "body": "not json"}]}

    result = govwin_worker.handler(event, None)
    assert result["batchItemFailures"] == []
    assert result["results"] == []


def test_unexpected_error_publishes_sns_alert(monkeypatch, app_config, mock_aws_env):
    monkeypatch.setattr(govwin_worker, "load_config", lambda: app_config)
    object.__setattr__(app_config.aws, "sns_topic_arn", "arn:aws:sns:us-east-1:0:test")
    _patch_clients(monkeypatch)
    sns = MagicMock()
    govwin_worker._sns_client = sns

    # Force the orchestrator to blow up on processing.
    monkeypatch.setattr(
        govwin_worker,
        "SyncOrchestrator",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    event = {"Records": [_record("m1", ["OPP1"])]}

    result = govwin_worker.handler(event, None)
    assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    sns.publish.assert_called_once()
    args = sns.publish.call_args.kwargs
    assert "RuntimeError" in args["Subject"]
    govwin_worker._sns_client = None


def test_decode_batch_handles_list_payload(monkeypatch, app_config, mock_aws_env):
    payload = [{"id": "OPP1"}, {"id": "OPP2"}]
    record = {"messageId": "m1", "body": json.dumps(payload)}
    refs = govwin_worker._decode_batch(record)
    assert [r["id"] for r in refs] == ["OPP1", "OPP2"]


def test_decode_batch_returns_empty_for_unexpected_shape():
    refs = govwin_worker._decode_batch({"body": json.dumps({"opportunity_batch": "?"})})
    assert refs == []
