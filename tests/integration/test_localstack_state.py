"""End-to-end integration tests against a real AWS endpoint.

These tests exercise the DynamoDB and Secrets Manager paths against a real AWS
boto3 client, talking to whatever endpoint is configured via ``AWS_ENDPOINT_URL``
(LocalStack in CI/local Docker, real AWS for staging smoke tests).

The tests skip when no endpoint is configured so the default ``make test`` and
unit suite remain hermetic. They run inside the docker-compose ``test-runner``
service (``make local-test``) where the LocalStack endpoint is wired up.
"""

from __future__ import annotations

import json
import os
import uuid

import boto3
import pytest

from src.config import AppConfig, AWSConfig, GovWinConfig, HubSpotConfig, SyncConfig
from src.govwin.auth import GovWinAuth
from src.sync.state import SyncStateManager

# Skip the entire module unless an AWS endpoint is configured. boto3 reads
# AWS_ENDPOINT_URL natively from the environment for endpoint overrides.
_endpoint = os.environ.get("AWS_ENDPOINT_URL")
pytestmark = pytest.mark.skipif(
    not _endpoint,
    reason="AWS_ENDPOINT_URL not set; skipping LocalStack integration tests",
)


@pytest.fixture(scope="module")
def aws_clients():
    """Return boto3 clients pointed at the configured endpoint."""
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return {
        "dynamodb": boto3.resource("dynamodb", region_name=region),
        "secrets": boto3.client("secretsmanager", region_name=region),
    }


@pytest.fixture(scope="module")
def app_config() -> AppConfig:
    """Build an AppConfig from the env vars set by docker-compose."""
    return AppConfig(
        govwin=GovWinConfig(),
        hubspot=HubSpotConfig(),
        aws=AWSConfig(
            region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            sync_state_table=os.environ["SYNC_STATE_TABLE"],
            entity_mappings_table=os.environ["ENTITY_MAPPINGS_TABLE"],
            govwin_secret_name=os.environ["GOVWIN_SECRET_NAME"],
            hubspot_secret_name=os.environ["HUBSPOT_SECRET_NAME"],
            govwin_tokens_secret_name=os.environ["GOVWIN_TOKENS_SECRET_NAME"],
        ),
        sync=SyncConfig(),
        environment="dev",
    )


def test_resources_exist(aws_clients, app_config):
    """LocalStack init script must have created the tables and secrets."""
    tables = list(aws_clients["dynamodb"].tables.all())
    names = {t.name for t in tables}
    assert app_config.aws.sync_state_table in names
    assert app_config.aws.entity_mappings_table in names

    for secret_name in (
        app_config.aws.govwin_secret_name,
        app_config.aws.hubspot_secret_name,
        app_config.aws.govwin_tokens_secret_name,
    ):
        aws_clients["secrets"].describe_secret(SecretId=secret_name)


def test_sync_cursor_round_trip(app_config):
    state = SyncStateManager(app_config)
    timestamp = "2026-04-28T12:00:00+00:00"

    state.set_last_sync_timestamp(timestamp)
    assert state.get_last_sync_timestamp() == timestamp


def test_opp_state_round_trip(app_config):
    state = SyncStateManager(app_config)
    opp_id = f"OPP-IT-{uuid.uuid4().hex[:8]}"

    assert state.get_opp_update_date(opp_id) is None
    state.set_opp_state(opp_id, "2026-04-01T00:00:00Z", hubspot_deal_id="9999")

    assert state.get_opp_update_date(opp_id) == "2026-04-01T00:00:00Z"
    assert state.get_opp_hubspot_id(opp_id) == "9999"


def test_entity_mapping_round_trip(app_config):
    state = SyncStateManager(app_config)
    govwin_id = f"IT-{uuid.uuid4().hex[:8]}"

    assert state.get_entity_hubspot_id("GOVENTITY", govwin_id) is None
    state.set_entity_mapping("GOVENTITY", govwin_id, "hs-1234")
    assert state.get_entity_hubspot_id("GOVENTITY", govwin_id) == "hs-1234"


def test_batch_get_opp_update_dates(app_config):
    state = SyncStateManager(app_config)
    opps = [f"OPP-BATCH-{uuid.uuid4().hex[:8]}" for _ in range(3)]

    for i, opp_id in enumerate(opps):
        state.set_opp_state(opp_id, f"2026-04-0{i + 1}T00:00:00Z")

    dates = state.batch_get_opp_update_dates(opps + ["OPP-MISSING-XYZ"])
    assert set(dates.keys()) == set(opps)
    assert all(d.startswith("2026-04-") for d in dates.values())


def test_govwin_auth_reads_secrets_manager(aws_clients, app_config):
    """The auth module must be able to load credentials from Secrets Manager."""
    aws_clients["secrets"].put_secret_value(
        SecretId=app_config.aws.govwin_secret_name,
        SecretString=json.dumps(
            {
                "client_id": "it-client",
                "client_secret": "it-secret",
                "username": "it@example.com",
                "password": "it-password",
            }
        ),
    )

    auth = GovWinAuth(app_config)
    creds = auth._load_credentials()
    assert creds["client_id"] == "it-client"
    assert creds["username"] == "it@example.com"
