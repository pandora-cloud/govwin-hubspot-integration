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
    def test_default_uses_marked_version(self, app_config, mock_aws_env, monkeypatch):
        """Default config uses markedVersion=2.2 (BD team marks opps for sync)."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

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
        request = search_route.calls[0].request
        url_str = str(request.url)
        assert "markedVersion=2.2" in url_str
        # Should NOT use date-range search when marked mode is active
        assert "oppSelectionDateFrom" not in url_str

    @respx.mock
    def test_disabled_marking_uses_date_search(self, app_config, mock_aws_env, monkeypatch):
        """When marked_version is empty, falls back to date-range search."""
        _env_vars(monkeypatch)
        monkeypatch.setenv("GOVWIN_MARKED_VERSION", "")
        _mock_govwin_auth()

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
        request = search_route.calls[0].request
        url_str = str(request.url)
        assert "oppSelectionDateFrom=" in url_str
        assert "markedVersion" not in url_str

    @respx.mock
    def test_cursor_used_in_date_search_mode(self, app_config, mock_aws_env, monkeypatch):
        """When marked_version is empty and a cursor exists, it's used as from_date."""
        _env_vars(monkeypatch)
        monkeypatch.setenv("GOVWIN_MARKED_VERSION", "")
        _mock_govwin_auth()

        # Set a sync cursor
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

        request = search_route.calls[0].request
        url_str = str(request.url)
        assert "oppSelectionDateFrom" in url_str

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

    @respx.mock
    def test_marked_mode_with_actual_opps(self, app_config, mock_aws_env, monkeypatch):
        """Marked mode returning actual opportunities that pass dedup."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        respx.get("https://services.govwin.com/neo-ws/opportunities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"paging": {"totalCount": 1, "max": 100, "offset": 0}},
                    "opportunities": [
                        {
                            "id": "OPP12345",
                            "title": "Test Opp",
                            "updateDate": "2025-03-20T14:30:00Z",
                        }
                    ],
                },
            )
        )

        from src.lambdas.discover_changes import handler

        result = handler({}, None)
        assert result["opportunities_count"] == 1
        assert len(result["opportunity_batches"]) == 1
        assert result["opportunity_batches"][0][0]["id"] == "OPP12345"

    @respx.mock
    def test_marked_mode_dedup_filters_unchanged(
        self, app_config, mock_aws_env, monkeypatch
    ):
        """Marked mode returns all marked opps; dedup filters out unchanged ones."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        # Pre-populate DynamoDB with an existing sync record
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        table.put_item(
            Item={
                "pk": "OPP#OPP12345",
                "sk": "METADATA",
                "govwin_update_date": "2025-03-20T14:30:00Z",
            }
        )

        respx.get("https://services.govwin.com/neo-ws/opportunities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"paging": {"totalCount": 1, "max": 100, "offset": 0}},
                    "opportunities": [
                        {
                            "id": "OPP12345",
                            "title": "Test Opp",
                            "updateDate": "2025-03-20T14:30:00Z",
                        }
                    ],
                },
            )
        )

        from src.lambdas.discover_changes import handler

        result = handler({}, None)
        # Same updateDate - should be filtered out by dedup
        assert result["opportunities_count"] == 0

    @respx.mock
    def test_unmarked_opp_drops_out_silently(self, app_config, mock_aws_env, monkeypatch):
        """When BD unmarks an opp in GovWin, it disappears from the marked-version response.

        The integration's design intentionally retains the existing HubSpot deal in this
        case (so manually-edited deal data isn't destroyed). This test pins that contract:
          1. discover_changes returns no opportunity for the unmarked id, and
          2. the previously-stored opp_state in DynamoDB is left untouched.
        """
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        # Pre-populate state as if the opp was synced previously
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        table.put_item(
            Item={
                "pk": "OPP#OPP-UNMARKED",
                "sk": "METADATA",
                "govwin_update_date": "2026-03-01T00:00:00Z",
                "hubspot_deal_id": "hs-deal-prior",
            }
        )

        # GovWin's marked-version response omits the unmarked opp entirely
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

        # No batches emitted, and crucially no delete/archive intent surfaced
        assert result["opportunities_count"] == 0
        assert result["opportunity_batches"] == []
        assert "to_delete" not in result
        assert "to_archive" not in result

        # State for the previously-synced opp is left intact
        item = table.get_item(Key={"pk": "OPP#OPP-UNMARKED", "sk": "METADATA"})
        assert item["Item"]["hubspot_deal_id"] == "hs-deal-prior"

    @respx.mock
    def test_remark_after_unmark_does_not_duplicate(
        self, app_config, mock_aws_env, monkeypatch
    ):
        """Re-marking an opp later must not create a duplicate in HubSpot.

        ``govwin_id`` (``hasUniqueValue=true`` in HubSpot) keeps the upsert idempotent,
        but the dedup layer must still emit the opp when its ``updateDate`` changes,
        so the existing deal is updated rather than left stale.
        """
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        # State reflects the prior sync
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table("test-sync-state")
        table.put_item(
            Item={
                "pk": "OPP#OPP-REMARK",
                "sk": "METADATA",
                "govwin_update_date": "2026-03-01T00:00:00Z",
                "hubspot_deal_id": "hs-deal-prior",
            }
        )

        # GovWin re-includes the opp with a newer updateDate
        respx.get("https://services.govwin.com/neo-ws/opportunities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {"paging": {"totalCount": 1, "max": 100, "offset": 0}},
                    "opportunities": [
                        {
                            "id": "OPP-REMARK",
                            "title": "Remarked Opp",
                            "updateDate": "2026-04-15T00:00:00Z",
                        }
                    ],
                },
            )
        )

        from src.lambdas.discover_changes import handler

        result = handler({}, None)
        assert result["opportunities_count"] == 1
        # Same govwin_id flows through; downstream batch_upsert keys on it
        assert result["opportunity_batches"][0][0]["id"] == "OPP-REMARK"

    @respx.mock
    def test_bookmarked_only_mode(self, app_config, mock_aws_env, monkeypatch):
        """Bookmarked-only mode passes markedOpps=true parameter."""
        _env_vars(monkeypatch)
        monkeypatch.setenv("GOVWIN_MARKED_VERSION", "")
        monkeypatch.setenv("GOVWIN_BOOKMARKED_ONLY", "true")
        _mock_govwin_auth()

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

        request = search_route.calls[0].request
        url_str = str(request.url)
        assert "markedOpps=true" in url_str
