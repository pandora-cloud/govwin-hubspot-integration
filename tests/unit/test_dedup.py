"""Tests for deduplication logic."""

import pytest

from src.models import GovWinOpportunity
from src.sync.dedup import batch_opportunities, filter_changed_opportunities
from src.sync.state import SyncStateManager


@pytest.fixture
def state_manager(app_config, mock_aws_env):
    return SyncStateManager(app_config)


def _make_opp(opp_id: str, update_date: str) -> GovWinOpportunity:
    return GovWinOpportunity(id=opp_id, updateDate=update_date, title=f"Opp {opp_id}")


def test_filter_all_new(state_manager: SyncStateManager):
    opps = [
        _make_opp("OPP001", "2025-03-20T14:00:00Z"),
        _make_opp("OPP002", "2025-03-20T15:00:00Z"),
    ]
    changed = filter_changed_opportunities(opps, state_manager)
    assert len(changed) == 2


def test_filter_unchanged(state_manager: SyncStateManager):
    state_manager.set_opp_state("OPP001", "2025-03-20T14:00:00Z")

    opps = [_make_opp("OPP001", "2025-03-20T14:00:00Z")]
    changed = filter_changed_opportunities(opps, state_manager)
    assert len(changed) == 0


def test_filter_updated(state_manager: SyncStateManager):
    state_manager.set_opp_state("OPP001", "2025-03-20T14:00:00Z")

    opps = [_make_opp("OPP001", "2025-03-21T10:00:00Z")]
    changed = filter_changed_opportunities(opps, state_manager)
    assert len(changed) == 1


def test_filter_mixed(state_manager: SyncStateManager):
    state_manager.set_opp_state("OPP001", "2025-03-20T14:00:00Z")

    opps = [
        _make_opp("OPP001", "2025-03-20T14:00:00Z"),  # Unchanged
        _make_opp("OPP002", "2025-03-21T10:00:00Z"),  # New
        _make_opp("OPP001", "2025-03-22T10:00:00Z"),  # Updated (duplicate ID, newer)
    ]
    # Note: in practice there wouldn't be duplicate IDs in a single search result
    changed = filter_changed_opportunities(opps, state_manager)
    # OPP001 appears twice: first unchanged, second updated. Both get evaluated.
    assert len(changed) >= 2


def test_filter_empty(state_manager: SyncStateManager):
    """Test filter_changed_opportunities with empty list returns empty list."""
    result = filter_changed_opportunities([], state_manager)
    assert result == []


def test_batch_opportunities():
    opps = [_make_opp(f"OPP{i:03d}", "2025-01-01") for i in range(125)]
    batches = batch_opportunities(opps, batch_size=50)

    assert len(batches) == 3
    assert len(batches[0]) == 50
    assert len(batches[1]) == 50
    assert len(batches[2]) == 25


def test_batch_single():
    opps = [_make_opp("OPP001", "2025-01-01")]
    batches = batch_opportunities(opps, batch_size=50)
    assert len(batches) == 1
    assert len(batches[0]) == 1


def test_filter_handles_timezone_offsets(state_manager: SyncStateManager):
    """Production fix: stored UTC vs incoming -05:00 offset must compare correctly."""
    state_manager.set_opp_state("OPP001", "2025-03-09T07:30:00+00:00")

    # Incoming has an earlier UTC equivalent (06:30 UTC) — should be unchanged
    earlier = [_make_opp("OPP001", "2025-03-09T01:30:00-05:00")]
    assert filter_changed_opportunities(earlier, state_manager) == []

    # Incoming has a later UTC equivalent (08:30 UTC) — should be flagged updated
    later = [_make_opp("OPP001", "2025-03-09T03:30:00-05:00")]
    assert len(filter_changed_opportunities(later, state_manager)) == 1


def test_filter_handles_unparseable_date(state_manager: SyncStateManager):
    """A bad incoming date must not crash; with no stored date, it is treated as new."""
    opps = [_make_opp("OPP001", "not-a-real-date")]
    changed = filter_changed_opportunities(opps, state_manager)
    assert len(changed) == 1
