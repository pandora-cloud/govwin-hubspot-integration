"""Tests for the update_sync_state Lambda handler."""

from __future__ import annotations

import re

import boto3


def _env_vars(monkeypatch):
    """Set environment variables for load_config."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SYNC_STATE_TABLE", "test-sync-state")
    monkeypatch.setenv("ENTITY_MAPPINGS_TABLE", "test-entity-mappings")
    monkeypatch.setenv("GOVWIN_SECRET_NAME", "test/govwin")
    monkeypatch.setenv("HUBSPOT_SECRET_NAME", "test/hubspot")
    monkeypatch.setenv("GOVWIN_TOKENS_SECRET_NAME", "test/govwin-tokens")


class TestUpdateSyncState:
    def test_timestamp_format_date_range_mode(self, app_config, mock_aws_env, monkeypatch):
        """In date-range mode, verify cursor format is MM/DD/YYYY."""
        _env_vars(monkeypatch)
        monkeypatch.setenv("GOVWIN_MARKED_VERSION", "")  # date-range mode

        from src.lambdas.update_sync_state import handler

        result = handler({}, None)

        timestamp = result["last_sync_timestamp"]
        assert re.match(r"^\d{2}/\d{2}/\d{4}$", timestamp), (
            f"Expected MM/DD/YYYY format, got {timestamp!r}"
        )

    def test_state_updated_date_range_mode(self, app_config, mock_aws_env, monkeypatch):
        """In date-range mode, verify DynamoDB gets the timestamp."""
        _env_vars(monkeypatch)
        monkeypatch.setenv("GOVWIN_MARKED_VERSION", "")  # date-range mode

        from src.lambdas.update_sync_state import handler

        result = handler({}, None)

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        item = table.get_item(Key={"pk": "SYNC_CURSOR", "sk": "METADATA"})
        assert "Item" in item
        assert item["Item"]["last_sync_timestamp"] == result["last_sync_timestamp"]
        assert result["status"] == "updated"

    def test_marked_mode_skips_cursor(self, app_config, mock_aws_env, monkeypatch):
        """In marked mode (default), cursor is NOT written to DynamoDB."""
        _env_vars(monkeypatch)
        # Default GOVWIN_MARKED_VERSION is "2.2" (marked mode)

        from src.lambdas.update_sync_state import handler

        result = handler({}, None)

        assert result["status"] == "updated"
        assert result["mode"] == "marked"
        assert "last_sync_timestamp" not in result

        # Verify no cursor was written
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        item = table.get_item(Key={"pk": "SYNC_CURSOR", "sk": "METADATA"})
        assert "Item" not in item

    def test_failed_batches_skip_cursor(self, app_config, mock_aws_env, monkeypatch):
        """When batches fail, cursor is NOT advanced regardless of mode."""
        _env_vars(monkeypatch)
        monkeypatch.setenv("GOVWIN_MARKED_VERSION", "")  # date-range mode

        from src.lambdas.update_sync_state import handler

        event = {
            "sync_results": [
                {"deals_synced": 5},
                {"status": "failed"},
            ]
        }
        result = handler(event, None)

        assert result["status"] == "partial_failure"
        assert result["failed_batches"] == 1
