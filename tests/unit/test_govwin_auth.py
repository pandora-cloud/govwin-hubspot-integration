"""Tests for GovWin OAuth2 authentication."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from src.config import AppConfig
from src.govwin.auth import GovWinAuth, GovWinAuthError


@pytest.fixture
def auth(app_config: AppConfig, mock_aws_env) -> GovWinAuth:
    return GovWinAuth(app_config)


class TestAuthenticate:
    def test_authenticate_success(self, auth: GovWinAuth, govwin_mock):
        """Mock httpx.post to return a valid token and verify it is stored."""
        govwin_mock.post("/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "fresh-access-token",
                    "refresh_token": "fresh-refresh-token",
                    "expires_in": 43200,
                },
            )
        )

        token = auth.access_token
        assert token == "fresh-access-token"
        assert auth._access_token == "fresh-access-token"
        assert auth._refresh_token == "fresh-refresh-token"

    def test_authenticate_401_raises(self, auth: GovWinAuth, govwin_mock):
        """Mock 401 and verify GovWinAuthError raised without leaking response body."""
        govwin_mock.post("/oauth/token").mock(
            return_value=httpx.Response(
                401,
                json={"error": "invalid_grant", "error_description": "bad creds"},
            )
        )

        with pytest.raises(GovWinAuthError) as exc_info:
            _ = auth.access_token

        error_message = str(exc_info.value)
        cred_check = "invalid credentials" in error_message.lower()
        auth_check = "Authentication failed" in error_message
        assert cred_check or auth_check
        # Must not leak the response body details
        assert "bad creds" not in error_message

    def test_refresh_token(self, auth: GovWinAuth, govwin_mock):
        """Mock refresh_token grant and verify new access_token is stored."""
        # Seed cached tokens with a valid refresh token but expired access token
        import boto3

        secrets = boto3.client("secretsmanager", region_name="us-east-1")
        secrets.put_secret_value(
            SecretId="test/govwin-tokens",
            SecretString=json.dumps({
                "access_token": "old-access-token",
                "refresh_token": "valid-refresh-token",
                "expires_at": time.time() - 100,  # Expired
            }),
        )

        govwin_mock.post("/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "refreshed-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 43200,
                },
            )
        )

        token = auth.access_token
        assert token == "refreshed-access-token"
        assert auth._refresh_token == "new-refresh-token"

    def test_token_caching(self, auth: GovWinAuth):
        """Verify _load_credentials caches after first call."""
        creds1 = auth._load_credentials()
        creds2 = auth._load_credentials()
        assert creds1 is creds2  # Same dict object returned
        assert auth._credentials is not None

    def test_invalidate(self, auth: GovWinAuth, govwin_mock):
        """Verify invalidate clears the token."""
        # First authenticate
        govwin_mock.post("/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "valid-token",
                    "refresh_token": "valid-refresh",
                    "expires_in": 43200,
                },
            )
        )
        _ = auth.access_token
        assert auth._access_token == "valid-token"

        auth.invalidate()
        assert auth._access_token is None
        assert auth._expires_at == 0
