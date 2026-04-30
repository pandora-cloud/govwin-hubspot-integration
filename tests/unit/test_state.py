"""Tests for DynamoDB sync state management."""

from decimal import Decimal

import boto3
import pytest

from src.sync.state import SyncStateManager


@pytest.fixture
def state_manager(app_config, mock_aws_env):
    return SyncStateManager(app_config)


class TestSyncCursor:
    def test_get_no_cursor(self, state_manager: SyncStateManager):
        assert state_manager.get_last_sync_timestamp() is None

    def test_set_and_get_cursor(self, state_manager: SyncStateManager):
        # WSAPI oppSelectionDateFrom requires MM/DD/YYYY exactly.
        state_manager.set_last_sync_timestamp("03/20/2025")
        result = state_manager.get_last_sync_timestamp()
        assert result == "03/20/2025"

    def test_update_cursor(self, state_manager: SyncStateManager):
        state_manager.set_last_sync_timestamp("03/20/2025")
        state_manager.set_last_sync_timestamp("03/21/2025")
        result = state_manager.get_last_sync_timestamp()
        assert result == "03/21/2025"

    def test_set_cursor_default_now(self, state_manager: SyncStateManager):
        import re

        state_manager.set_last_sync_timestamp()
        result = state_manager.get_last_sync_timestamp()
        assert result is not None and re.fullmatch(r"\d{2}/\d{2}/\d{4}", result)

    def test_set_cursor_rejects_non_wsapi_format(self, state_manager: SyncStateManager):
        import pytest

        # ISO-8601 would silently break discovery; assertion must catch it.
        with pytest.raises(ValueError):
            state_manager.set_last_sync_timestamp("2025-03-20T14:30:00Z")
        with pytest.raises(ValueError):
            state_manager.set_last_sync_timestamp("03/20/2025 14:30:00")


class TestOpportunityState:
    def test_get_no_opp(self, state_manager: SyncStateManager):
        assert state_manager.get_opp_update_date("OPP99999") is None

    def test_set_and_get_opp(self, state_manager: SyncStateManager):
        state_manager.set_opp_state(
            govwin_opp_id="OPP12345",
            govwin_update_date="2025-03-20T14:30:00Z",
            hubspot_deal_id="hs-deal-001",
        )
        assert state_manager.get_opp_update_date("OPP12345") == "2025-03-20T14:30:00Z"
        assert state_manager.get_opp_hubspot_id("OPP12345") == "hs-deal-001"

    def test_batch_get_opp_dates(self, state_manager: SyncStateManager):
        state_manager.set_opp_state("OPP001", "2025-01-01T00:00:00Z")
        state_manager.set_opp_state("OPP002", "2025-02-01T00:00:00Z")

        result = state_manager.batch_get_opp_update_dates(["OPP001", "OPP002", "OPP003"])
        assert result["OPP001"] == "2025-01-01T00:00:00Z"
        assert result["OPP002"] == "2025-02-01T00:00:00Z"
        assert "OPP003" not in result


class TestEntityMappings:
    def test_get_no_mapping(self, state_manager: SyncStateManager):
        assert state_manager.get_entity_hubspot_id("GOVENTITY", "100") is None

    def test_set_and_get_mapping(self, state_manager: SyncStateManager):
        state_manager.set_entity_mapping("GOVENTITY", "100", "hs-company-001")
        result = state_manager.get_entity_hubspot_id("GOVENTITY", "100")
        assert result == "hs-company-001"

    def test_batch_set_mappings(self, state_manager: SyncStateManager):
        mappings = [
            ("GOVENTITY", "100", "hs-co-001"),
            ("CONTACT", "C001", "hs-ct-001"),
            ("COMPANY", "200", "hs-co-002"),
        ]
        state_manager.batch_set_entity_mappings(mappings)

        assert state_manager.get_entity_hubspot_id("GOVENTITY", "100") == "hs-co-001"
        assert state_manager.get_entity_hubspot_id("CONTACT", "C001") == "hs-ct-001"
        assert state_manager.get_entity_hubspot_id("COMPANY", "200") == "hs-co-002"


class TestTTLBehavior:
    def test_set_opp_state_includes_ttl(self, state_manager: SyncStateManager, app_config):
        """Verify TTL field is set on DynamoDB items."""
        state_manager.set_opp_state("OPP001", "2025-03-20T14:00:00Z", "hs-deal-001")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table(app_config.aws.sync_state_table)
        response = table.get_item(Key={"pk": "OPP#OPP001", "sk": "METADATA"})
        item = response["Item"]

        assert "ttl" in item
        # DynamoDB returns numbers as Decimal
        assert isinstance(item["ttl"], (int, Decimal))
        # TTL should be ~180 days in the future
        import time

        assert int(item["ttl"]) > int(time.time())

    def test_set_entity_mapping_includes_ttl(self, state_manager: SyncStateManager, app_config):
        """Verify TTL field is set on entity mapping items."""
        state_manager.set_entity_mapping("GOVENTITY", "100", "hs-co-001")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table(app_config.aws.entity_mappings_table)
        response = table.get_item(
            Key={"pk": "GOVENTITY#100", "sk": "HUBSPOT_MAPPING"}
        )
        item = response["Item"]

        assert "ttl" in item
        # DynamoDB returns numbers as Decimal
        assert isinstance(item["ttl"], (int, Decimal))
        import time

        assert int(item["ttl"]) > int(time.time())

    def test_sync_cursor_has_no_ttl(self, state_manager: SyncStateManager, app_config):
        """Verify sync cursor item does NOT have TTL."""
        state_manager.set_last_sync_timestamp("03/20/2025")

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table(app_config.aws.sync_state_table)
        response = table.get_item(Key={"pk": "SYNC_CURSOR", "sk": "METADATA"})
        item = response["Item"]

        assert "ttl" not in item


class TestWebhookReplayProtection:
    def test_reserve_first_call_returns_true(self, state_manager: SyncStateManager):
        assert state_manager.reserve_webhook_signature("fingerprint-abc") is True

    def test_reserve_replay_returns_false(self, state_manager: SyncStateManager):
        assert state_manager.reserve_webhook_signature("fingerprint-xyz") is True
        # Second sighting of the same fingerprint within the TTL window:
        # caller must reject.
        assert state_manager.reserve_webhook_signature("fingerprint-xyz") is False

    def test_reserve_distinct_fingerprints_independent(
        self, state_manager: SyncStateManager
    ):
        assert state_manager.reserve_webhook_signature("fp1") is True
        assert state_manager.reserve_webhook_signature("fp2") is True
        assert state_manager.reserve_webhook_signature("fp1") is False
