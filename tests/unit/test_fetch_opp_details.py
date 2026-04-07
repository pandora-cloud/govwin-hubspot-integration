"""Tests for the fetch_opp_details Lambda handler."""

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


def _mock_opportunity_bundle(opp_id: str, title: str = "Test Opp"):
    """Set up respx mocks for a full opportunity bundle fetch."""
    base = "https://services.govwin.com/neo-ws"
    respx.get(f"{base}/opportunities/{opp_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "opportunities": [
                    {"id": opp_id, "title": title, "status": "Pre-RFP"}
                ]
            },
        )
    )
    respx.get(f"{base}/opportunities/{opp_id}/contacts").mock(
        return_value=httpx.Response(200, json={"contacts": []})
    )
    respx.get(f"{base}/opportunities/{opp_id}/companies").mock(
        return_value=httpx.Response(200, json={"companies": []})
    )
    respx.get(f"{base}/opportunities/{opp_id}/contracts").mock(
        return_value=httpx.Response(200, json={"contracts": []})
    )
    respx.get(f"{base}/opportunities/{opp_id}/placesOfPerformance").mock(
        return_value=httpx.Response(200, json={"placesOfPerformance": []})
    )


class TestFetchOppDetails:
    @respx.mock
    def test_valid_opp_ids(self, app_config, mock_aws_env, monkeypatch):
        """Mock GovWin responses and verify bundles returned."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()
        _mock_opportunity_bundle("OPP001", "Cloud Services")

        from src.lambdas.fetch_opp_details import handler

        event = [{"id": "OPP001", "updateDate": "2025-03-20T14:00:00Z"}]
        result = handler(event, None)

        assert len(result["bundles"]) == 1
        assert result["bundles"][0]["opportunity"]["id"] == "OPP001"
        assert result["errors"] == []

    @respx.mock
    def test_invalid_opp_id_rejected(self, app_config, mock_aws_env, monkeypatch):
        """Pass event with id='INVALID' and verify it's skipped with error."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        from src.lambdas.fetch_opp_details import handler

        event = [{"id": "INVALID", "updateDate": "2025-03-20T14:00:00Z"}]
        result = handler(event, None)

        assert len(result["bundles"]) == 0
        assert len(result["errors"]) == 1
        assert "Invalid opportunity ID format" in result["errors"][0]

    @respx.mock
    def test_payload_size_limit(self, app_config, mock_aws_env, monkeypatch):
        """Mock enough large bundles to exceed 200KB and verify early break."""
        _env_vars(monkeypatch)
        _mock_govwin_auth()

        base = "https://services.govwin.com/neo-ws"
        # Create 20 opportunity IDs with very long descriptions
        opp_ids = [f"OPP{i:03d}" for i in range(20)]
        long_description = "x" * 50000  # ~50KB per opp

        for opp_id in opp_ids:
            respx.get(f"{base}/opportunities/{opp_id}").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "opportunities": [
                            {
                                "id": opp_id,
                                "title": "Large Opp",
                                "status": "Pre-RFP",
                                "description": long_description,
                            }
                        ]
                    },
                )
            )
            respx.get(f"{base}/opportunities/{opp_id}/contacts").mock(
                return_value=httpx.Response(200, json={"contacts": []})
            )
            respx.get(f"{base}/opportunities/{opp_id}/companies").mock(
                return_value=httpx.Response(200, json={"companies": []})
            )
            respx.get(f"{base}/opportunities/{opp_id}/contracts").mock(
                return_value=httpx.Response(200, json={"contracts": []})
            )
            respx.get(f"{base}/opportunities/{opp_id}/placesOfPerformance").mock(
                return_value=httpx.Response(200, json={"placesOfPerformance": []})
            )

        from src.lambdas.fetch_opp_details import handler

        event = [{"id": opp_id, "updateDate": "2025-01-01"} for opp_id in opp_ids]
        result = handler(event, None)

        # Should have broken early before processing all 20
        assert len(result["bundles"]) < 20
        # The handler breaks AFTER exceeding, so the payload may be slightly over
        # but it should have fewer than 20 bundles
        assert len(result["bundles"]) > 0
