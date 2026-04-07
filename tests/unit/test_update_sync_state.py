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
    def test_timestamp_format(self, app_config, mock_aws_env, monkeypatch):
        """Verify format is MM/DD/YYYY (no time component)."""
        _env_vars(monkeypatch)

        from src.lambdas.update_sync_state import handler

        result = handler({}, None)

        timestamp = result["last_sync_timestamp"]
        # Verify MM/DD/YYYY format
        assert re.match(r"^\d{2}/\d{2}/\d{4}$", timestamp), (
            f"Expected MM/DD/YYYY format, got {timestamp!r}"
        )

    def test_state_updated(self, app_config, mock_aws_env, monkeypatch):
        """Verify DynamoDB gets the timestamp."""
        _env_vars(monkeypatch)

        from src.lambdas.update_sync_state import handler

        result = handler({}, None)

        # Verify state was written to DynamoDB
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        item = table.get_item(Key={"pk": "SYNC_CURSOR", "sk": "METADATA"})
        assert "Item" in item
        assert item["Item"]["last_sync_timestamp"] == result["last_sync_timestamp"]
        assert result["status"] == "updated"
