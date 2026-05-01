"""GovWin OAuth2 authentication: token acquisition, refresh, and caching via Secrets Manager."""

from __future__ import annotations

import json
import logging
import time

import httpx
from botocore.exceptions import ClientError

from src.aws_clients import make_client
from src.config import AppConfig

logger = logging.getLogger(__name__)


class GovWinAuthError(Exception):
    """Raised when GovWin authentication fails."""


class GovWinAuth:
    """Manages GovWin OAuth2 tokens with Secrets Manager caching."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._base_url = config.govwin.base_url
        self._secrets_client = make_client("secretsmanager", config.aws.region)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0
        self._credentials: dict[str, str] | None = None

    @property
    def access_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if self._is_token_valid():
            return self._access_token  # type: ignore[return-value]

        # Try to load cached tokens from Secrets Manager
        cached = self._load_cached_tokens()
        buffer = self._config.govwin.token_expiry_buffer_seconds
        if cached and cached.get("expires_at", 0) > time.time() + buffer:
            self._access_token = cached["access_token"]
            self._refresh_token = cached.get("refresh_token")
            self._expires_at = cached["expires_at"]
            return self._access_token

        # Try refresh token first
        if cached and cached.get("refresh_token"):
            try:
                self._refresh_access_token(cached["refresh_token"])
                return self._access_token  # type: ignore[return-value]
            except GovWinAuthError:
                logger.warning("Refresh token expired or invalid, re-authenticating")

        # Full authentication
        self._authenticate()
        return self._access_token  # type: ignore[return-value]

    def _is_token_valid(self) -> bool:
        return (
            self._access_token is not None
            and self._expires_at > time.time() + self._config.govwin.token_expiry_buffer_seconds
        )

    def _authenticate(self) -> None:
        """Perform full OAuth2 password grant authentication."""
        creds = self._load_credentials()

        try:
            response = httpx.post(
                f"{self._base_url}/oauth/token",
                data={
                    "client_id": creds["client_id"],
                    "client_secret": creds["client_secret"],
                    "grant_type": "password",
                    "username": creds["username"],
                    "password": creds["password"],
                    "scope": "read",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.debug("Authentication error response: %s", e.response.text)
            if e.response.status_code == 401:
                raise GovWinAuthError(
                    "Authentication failed: invalid credentials. "
                    "Check credentials. Account locks after 5 failed attempts for 30 minutes."
                ) from e
            status = e.response.status_code
            raise GovWinAuthError(f"Authentication failed with status {status}") from e
        except httpx.RequestError as e:
            raise GovWinAuthError(f"Connection error during authentication: {e}") from e

        token_data = response.json()
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token")
        self._expires_at = time.time() + token_data.get("expires_in", 43200)

        self._cache_tokens()
        expires_in = token_data.get("expires_in", 43200)
        logger.info("GovWin authentication successful, token expires in %ds", expires_in)

    def _refresh_access_token(self, refresh_token: str) -> None:
        """Refresh the access token using a refresh token."""
        creds = self._load_credentials()

        try:
            response = httpx.post(
                f"{self._base_url}/oauth/token",
                data={
                    "client_id": creds["client_id"],
                    "client_secret": creds["client_secret"],
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": "read",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise GovWinAuthError(f"Token refresh failed: {e.response.status_code}") from e

        token_data = response.json()
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token", refresh_token)
        self._expires_at = time.time() + token_data.get("expires_in", 43200)

        self._cache_tokens()
        logger.info("GovWin token refreshed successfully")

    def _load_credentials(self) -> dict[str, str]:
        """Load GovWin credentials from Secrets Manager, caching after first load."""
        if self._credentials is not None:
            return self._credentials
        try:
            response = self._secrets_client.get_secret_value(
                SecretId=self._config.aws.govwin_secret_name
            )
            self._credentials = json.loads(response["SecretString"])
            return self._credentials
        except ClientError as e:
            raise GovWinAuthError(
                f"Failed to load GovWin credentials from Secrets Manager: {e}"
            ) from e

    def _load_cached_tokens(self) -> dict | None:
        """Load cached tokens from Secrets Manager."""
        try:
            response = self._secrets_client.get_secret_value(
                SecretId=self._config.aws.govwin_tokens_secret_name
            )
            return json.loads(response["SecretString"])
        except ClientError:
            return None

    def _cache_tokens(self) -> None:
        """Cache tokens in Secrets Manager for use across Lambda invocations."""
        token_data = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
        }
        try:
            self._secrets_client.put_secret_value(
                SecretId=self._config.aws.govwin_tokens_secret_name,
                SecretString=json.dumps(token_data),
            )
        except ClientError as e:
            logger.warning("Failed to cache tokens in Secrets Manager: %s", e)

    def get_auth_headers(self) -> dict[str, str]:
        """Return authorization headers for API requests."""
        return {"Authorization": f"Bearer {self.access_token}"}

    def invalidate(self) -> None:
        """Clear cached token, forcing re-auth on next use."""
        self._access_token = None
        self._refresh_token = None
        self._expires_at = 0
        # Clear Secrets Manager cache so _load_cached_tokens returns stale=true
        try:
            self._secrets_client.put_secret_value(
                SecretId=self._config.aws.govwin_tokens_secret_name,
                SecretString=json.dumps({
                    "access_token": "",
                    "refresh_token": "",
                    "expires_at": 0,
                }),
            )
        except ClientError:
            pass  # Best-effort; in-memory invalidation is the primary mechanism
