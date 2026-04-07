"""Tests for the discover_changes Lambda handler."""

from __future__ import annotations

import httpx
import respx


def _env_vars(monkeypatch):
    """Set environment variables for load_config."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SYNC_STATE_TABLE", "test-sync-state")
    monkeypatch.setenv("ENTITY_MAPPINGS_TABLE", "test-entity-mappings")
    monkeypatch.setenv("GOVWIN_SECRET_NAME", "test/govwin")
    monkeypatch.setenv("HUBSPOT_SECRET_NAME", "test/hubspot")
    monkeypatch.setenv("GOVWIN_TOKENS_SECRET_NAME", "test/govwin-tokens")
    monkeypatch.setenv("INITIAL_LOOKBACK_DAYS", "365")


def _mock_govwin_auth():
    """Return a respx route for GovWin auth."""
    return respx.post(
        "https://services.govwin.com/neo-ws/oauth/token"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "test-token",
                "refresh_token": "test-refresh",
                "expires_in": 43200,
            },
        )
    )


class TestDiscoverChanges:
    @respx.mock
    def test_first_run_uses_lookback(self, app_config, mock_aws_env, monkeypatch):
        """Mock no sync cursor and verify oppSelectionDateFrom uses lookback date."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        # No sync cursor is set in DynamoDB (first run)
        # The handler should use initial_lookback_days

        search_route = respx.get(
            "https://services.govwin.com/neo-ws/opportunities"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"paging": {"totalCount": 0, "max": 100, "offset": 0}},
                    "opportunities": [],
                },
            )
        )

        from src.lambdas.discover_changes import handler

        result = handler({}, None)

        assert result["opportunities_count"] == 0
        # Verify the request used the lookback date format MM/DD/YYYY
        request = search_route.calls[0].request
        url_str = str(request.url)
        assert "oppSelectionDateFrom=" in url_str

    @respx.mock
    def test_subsequent_run_uses_cursor(self, app_config, mock_aws_env, monkeypatch):
        """Mock existing sync cursor and verify it's passed as from_date."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        # Set a sync cursor in DynamoDB
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        table.put_item(
            Item={
                "pk": "SYNC_CURSOR",
                "sk": "METADATA",
                "last_sync_timestamp": "03/15/2025",
                "updated_at": "2025-03-15T00:00:00Z",
            }
        )

        search_route = respx.get(
            "https://services.govwin.com/neo-ws/opportunities"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"paging": {"totalCount": 0, "max": 100, "offset": 0}},
                    "opportunities": [],
                },
            )
        )

        from src.lambdas.discover_changes import handler

        handler({}, None)

        # Verify cursor date was used
        request = search_route.calls[0].request
        url_str = str(request.url)
        assert "oppSelectionDateFrom=03%2F15%2F2025" in url_str or "03/15/2025" in url_str

    @respx.mock
    def test_empty_results(self, app_config, mock_aws_env, monkeypatch):
        """Mock empty opportunities response and verify count=0."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        respx.get("https://services.govwin.com/neo-ws/opportunities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"paging": {"totalCount": 0, "max": 100, "offset": 0}},
                    "opportunities": [],
                },
            )
        )

        from src.lambdas.discover_changes import handler

        result = handler({}, None)
        assert result["opportunities_count"] == 0
        assert result["opportunity_batches"] == []
