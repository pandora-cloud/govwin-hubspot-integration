#!/usr/bin/env python3
"""Pre-deployment validation script.

Tests connectivity and credentials for GovWin API, HubSpot API,
DynamoDB, and Secrets Manager. Works against real AWS or LocalStack.

Usage:
    python scripts/validate.py
    python scripts/validate.py --skip-govwin --skip-hubspot  # AWS-only checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import httpx
from botocore.exceptions import ClientError

from src.config import load_config


def _print_result(name: str, passed: bool, detail: str = "") -> None:
    status = "\033[32mPASS\033[0m" if passed else "\033[31mFAIL\033[0m"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def _get_credential(secret_name: str, key: str, env_fallback: str) -> str | None:
    """Try Secrets Manager first, then environment variable."""
    config = load_config()
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")

    try:
        kwargs = {"region_name": config.aws.region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        client = boto3.client("secretsmanager", **kwargs)
        response = client.get_secret_value(SecretId=secret_name)
        data = json.loads(response["SecretString"])
        return data.get(key)
    except (ClientError, KeyError):
        return os.environ.get(env_fallback)


def check_govwin(config) -> bool:
    """Test GovWin API connectivity: OAuth2 auth + list 1 opportunity."""
    print("\n--- GovWin API ---")

    # Get credentials
    client_id = _get_credential(config.aws.govwin_secret_name, "client_id", "GOVWIN_CLIENT_ID")
    client_secret = _get_credential(
        config.aws.govwin_secret_name, "client_secret", "GOVWIN_CLIENT_SECRET"
    )
    username = _get_credential(config.aws.govwin_secret_name, "username", "GOVWIN_USERNAME")
    password = _get_credential(config.aws.govwin_secret_name, "password", "GOVWIN_PASSWORD")

    if not all([client_id, client_secret, username, password]):
        _print_result(
            "Credentials",
            False,
            "Missing credentials. Set GOVWIN_CLIENT_ID/SECRET/USERNAME/PASSWORD "
            "env vars or populate Secrets Manager.",
        )
        return False
    _print_result("Credentials", True, "loaded")

    # Test OAuth2
    base_url = config.govwin.base_url
    try:
        response = httpx.post(
            f"{base_url}/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "password",
                "username": username,
                "password": password,
                "scope": "read",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if response.status_code != 200:
            _print_result("OAuth2 Auth", False, f"HTTP {response.status_code}")
            return False
        token = response.json().get("access_token")
        expires = response.json().get("expires_in")
        _print_result("OAuth2 Auth", True, f"token obtained (expires in {expires}s)")
    except Exception as e:
        _print_result("OAuth2 Auth", False, str(e))
        return False

    # Test API call
    try:
        response = httpx.get(
            f"{base_url}/opportunities",
            params={"max": 1, "markedVersion": "2.2"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code == 200:
            data = response.json()
            count = data.get("meta", {}).get("paging", {}).get("totalCount", 0)
            _print_result("API Access", True, f"{count} marked opportunities available")
        else:
            _print_result("API Access", False, f"HTTP {response.status_code}")
            return False
    except Exception as e:
        _print_result("API Access", False, str(e))
        return False

    return True


def check_hubspot(config) -> bool:
    """Test HubSpot API connectivity: verify token + check for govwin properties."""
    print("\n--- HubSpot API ---")

    token = _get_credential(
        config.aws.hubspot_secret_name, "private_app_token", "HUBSPOT_PRIVATE_APP_TOKEN"
    )
    if not token:
        _print_result(
            "Credentials",
            False,
            "Missing token. Set HUBSPOT_PRIVATE_APP_TOKEN env var or populate Secrets Manager.",
        )
        return False
    _print_result("Credentials", True, "loaded")

    base_url = config.hubspot.base_url
    try:
        response = httpx.get(
            f"{base_url}/crm/v3/properties/deals",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code != 200:
            _print_result("API Access", False, f"HTTP {response.status_code}")
            return False

        props = response.json().get("results", [])
        prop_names = {p["name"] for p in props}
        has_govwin = "govwin_opp_id" in prop_names
        _print_result(
            "API Access",
            True,
            f"{len(props)} deal properties found",
        )
        _print_result(
            "GovWin Properties",
            has_govwin,
            "installed" if has_govwin else "not found — run setup_hubspot Lambda first",
        )
    except Exception as e:
        _print_result("API Access", False, str(e))
        return False

    return True


def check_dynamodb(config) -> bool:
    """Test DynamoDB read/write access on both tables."""
    print("\n--- DynamoDB ---")
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    all_passed = True

    for table_name in [config.aws.sync_state_table, config.aws.entity_mappings_table]:
        try:
            kwargs = {"region_name": config.aws.region}
            if endpoint_url:
                kwargs["endpoint_url"] = endpoint_url
            dynamodb = boto3.resource("dynamodb", **kwargs)
            table = dynamodb.Table(table_name)

            # Write test item
            table.put_item(Item={"pk": "VALIDATE_TEST", "sk": "TEST", "value": "ok"})
            # Read it back
            result = table.get_item(Key={"pk": "VALIDATE_TEST", "sk": "TEST"})
            assert result["Item"]["value"] == "ok"
            # Clean up
            table.delete_item(Key={"pk": "VALIDATE_TEST", "sk": "TEST"})

            _print_result(f"Table: {table_name}", True, "read/write OK")
        except Exception as e:
            _print_result(f"Table: {table_name}", False, str(e))
            all_passed = False

    return all_passed


def check_secrets(config) -> bool:
    """Test Secrets Manager access for all 3 secrets."""
    print("\n--- Secrets Manager ---")
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    all_passed = True

    secrets_to_check = {
        config.aws.govwin_secret_name: ["client_id", "client_secret", "username", "password"],
        config.aws.hubspot_secret_name: ["private_app_token"],
        config.aws.govwin_tokens_secret_name: ["access_token", "refresh_token", "expires_at"],
    }

    kwargs = {"region_name": config.aws.region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    client = boto3.client("secretsmanager", **kwargs)

    for secret_name, expected_keys in secrets_to_check.items():
        try:
            response = client.get_secret_value(SecretId=secret_name)
            data = json.loads(response["SecretString"])
            missing = [k for k in expected_keys if k not in data]
            if missing:
                _print_result(f"Secret: {secret_name}", False, f"missing keys: {missing}")
                all_passed = False
            else:
                _print_result(f"Secret: {secret_name}", True, f"keys: {', '.join(expected_keys)}")
        except ClientError as e:
            _print_result(f"Secret: {secret_name}", False, str(e))
            all_passed = False

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate GovWin-HubSpot integration prerequisites"
    )
    parser.add_argument("--skip-govwin", action="store_true", help="Skip GovWin API check")
    parser.add_argument("--skip-hubspot", action="store_true", help="Skip HubSpot API check")
    args = parser.parse_args()

    config = load_config()
    results: list[bool] = []

    print("GovWin-HubSpot Integration — Pre-deployment Validation")
    print("=" * 55)

    if os.environ.get("AWS_ENDPOINT_URL"):
        print(f"\nUsing endpoint: {os.environ['AWS_ENDPOINT_URL']}")

    # Always check AWS resources
    results.append(check_dynamodb(config))
    results.append(check_secrets(config))

    # Optionally check external APIs
    if not args.skip_govwin:
        results.append(check_govwin(config))
    else:
        print("\n--- GovWin API --- (skipped)")

    if not args.skip_hubspot:
        results.append(check_hubspot(config))
    else:
        print("\n--- HubSpot API --- (skipped)")

    # Summary
    print("\n" + "=" * 55)
    passed = all(results)
    if passed:
        print("\033[32mAll checks passed.\033[0m")
    else:
        print("\033[31mSome checks failed. See above for details.\033[0m")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
