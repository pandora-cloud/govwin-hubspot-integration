"""Tests for the authenticate Lambda handler."""

from __future__ import annotations

import httpx
import pytest
import respx

from src.govwin.auth import GovWinAuthError


def _env_vars(monkeypatch):
    """Set environment variables for load_config."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SYNC_STATE_TABLE", "test-sync-state")
    monkeypatch.setenv("ENTITY_MAPPINGS_TABLE", "test-entity-mappings")
    monkeypatch.setenv("GOVWIN_SECRET_NAME", "test/govwin")
    monkeypatch.setenv("HUBSPOT_SECRET_NAME", "test/hubspot")
    monkeypatch.setenv("GOVWIN_TOKENS_SECRET_NAME", "test/govwin-tokens")


class TestAuthenticateHandler:
    @respx.mock
    def test_handler_success(self, app_config, mock_aws_env, monkeypatch):
        """Mock AWS secrets + httpx auth and verify returns {status: authenticated}."""
        _env_vars(monkeypatch)

        respx.post("https://services.govwin.com/neo-ws/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "test-token-123",
                    "refresh_token": "test-refresh-123",
                    "expires_in": 43200,
                },
            )
        )

        from src.lambdas.authenticate import handler

        result = handler({}, None)

        assert result["status"] == "authenticated"
        assert result["token_available"] is True

    @respx.mock
    def test_handler_failure(self, app_config, mock_aws_env, monkeypatch):
        """Mock auth failure and verify exception propagates."""
        _env_vars(monkeypatch)

        respx.post("https://services.govwin.com/neo-ws/oauth/token").mock(
            return_value=httpx.Response(
                401,
                json={"error": "invalid_grant"},
            )
        )

        from src.lambdas.authenticate import handler

        with pytest.raises(GovWinAuthError):
            handler({}, None)
