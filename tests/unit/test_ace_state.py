"""Tests for ACE-related helpers on SyncStateManager."""

from __future__ import annotations

import pytest

from src.sync.state import SyncStateManager


@pytest.fixture
def state(app_config, mock_aws_env) -> SyncStateManager:
    return SyncStateManager(app_config)


class TestACEMapping:
    def test_get_returns_none_when_missing(self, state: SyncStateManager) -> None:
        assert state.get_ace_mapping("OPP-NONE") is None

    def test_set_then_get(self, state: SyncStateManager) -> None:
        state.set_ace_mapping(
            govwin_id="OPP1",
            ace_opportunity_id="O1",
            last_modified_date="2026-04-29T00:00:00Z",
            client_token="tok-1",
            hubspot_deal_id="deal-1",
        )
        record = state.get_ace_mapping("OPP1")
        assert record is not None
        assert record["ace_opportunity_id"] == "O1"
        assert record["last_modified_date"] == "2026-04-29T00:00:00Z"
        assert record["client_token"] == "tok-1"
        assert record["hubspot_deal_id"] == "deal-1"

    def test_set_overwrites_with_engagement_fields(self, state: SyncStateManager) -> None:
        state.set_ace_mapping(govwin_id="OPP1", ace_opportunity_id="O1")
        state.set_ace_mapping(
            govwin_id="OPP1",
            ace_opportunity_id="O1",
            ace_engagement_invitation_id="EI1",
            ace_task_id="T1",
        )
        record = state.get_ace_mapping("OPP1")
        assert record is not None
        assert record["ace_engagement_invitation_id"] == "EI1"
        assert record["ace_task_id"] == "T1"


class TestReserveClientToken:
    def test_returns_supplied_token_when_no_existing(self, state: SyncStateManager) -> None:
        result = state.reserve_client_token("OPP1", "tok-new")
        assert result == "tok-new"

    def test_returns_existing_token_on_retry(self, state: SyncStateManager) -> None:
        first = state.reserve_client_token("OPP1", "tok-1")
        second = state.reserve_client_token("OPP1", "tok-2")
        assert first == "tok-1"
        assert second == "tok-1"  # idempotent on redelivery


class TestEventDedup:
    def test_unseen_event_returns_false(self, state: SyncStateManager) -> None:
        assert state.is_event_seen("evt-x") is False

    def test_seen_after_mark(self, state: SyncStateManager) -> None:
        state.mark_event_seen("evt-x")
        assert state.is_event_seen("evt-x") is True
