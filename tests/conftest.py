"""Shared test fixtures and mock data."""

from __future__ import annotations

import json

import boto3
import pytest
import respx
from moto import mock_aws

from src.config import (
    ACEConfig,
    AppConfig,
    AWSConfig,
    GovWinConfig,
    HubSpotConfig,
    SyncConfig,
)


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        govwin=GovWinConfig(
            base_url="https://services.govwin.com/neo-ws",
        ),
        hubspot=HubSpotConfig(
            base_url="https://api.hubapi.com",
        ),
        aws=AWSConfig(
            region="us-east-1",
            sync_state_table="test-sync-state",
            entity_mappings_table="test-entity-mappings",
            govwin_secret_name="test/govwin",
            hubspot_secret_name="test/hubspot",
            govwin_tokens_secret_name="test/govwin-tokens",
            hubspot_webhook_secret_name="test/hubspot-webhook",
            ace_submission_queue_url="https://sqs.us-east-1.amazonaws.com/000000000000/test-ace-submit",
        ),
        sync=SyncConfig(),
        ace=ACEConfig(
            catalog="Sandbox",
            default_solution_id="S-0051246",
        ),
        environment="test",
    )


@pytest.fixture
def mock_aws_env(app_config: AppConfig):
    """Set up mocked AWS services with DynamoDB tables and Secrets Manager."""
    with mock_aws():
        # Create DynamoDB tables
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        dynamodb.create_table(
            TableName=app_config.aws.sync_state_table,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        dynamodb.create_table(
            TableName=app_config.aws.entity_mappings_table,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Create secrets
        secrets = boto3.client("secretsmanager", region_name="us-east-1")

        secrets.create_secret(
            Name=app_config.aws.govwin_secret_name,
            SecretString=json.dumps({
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
                "username": "test@example.com",
                "password": "test-password",
            }),
        )

        secrets.create_secret(
            Name=app_config.aws.hubspot_secret_name,
            SecretString=json.dumps({
                "private_app_token": "test-hubspot-token",
            }),
        )

        secrets.create_secret(
            Name=app_config.aws.govwin_tokens_secret_name,
            SecretString=json.dumps({
                "access_token": "",
                "refresh_token": "",
                "expires_at": 0,
            }),
        )

        yield


# ---------------------------------------------------------------------------
# Sample Data
# ---------------------------------------------------------------------------

SAMPLE_OPPORTUNITY_JSON = {
    "id": "OPP12345",
    "iqOppId": 12345,
    "title": "Cloud Migration Services for DoD",
    "type": "trackedopp",
    "status": "RFP Released",
    "description": "<p>Cloud migration <b>services</b> for Department of Defense.</p>",
    "country": "USA",
    "createdDate": "2025-01-15T10:00:00Z",
    "updateDate": "2025-03-20T14:30:00Z",
    "solicitationDate": {"value": "2025-04-01"},
    "solicitationNumber": "W91234-25-R-0001",
    "responseDate": {"value": "2025-05-15"},
    "pAwardDateFrom": {"value": "2025-07-01"},
    "pAwardDateTo": {"value": "2025-09-30"},
    "oppValue": 5000.0,
    "priority": 3,
    "primaryNAICS": {"id": "541512", "title": "Computer Systems Design Services"},
    "govEntity": {"id": 100, "title": "Department of Defense"},
    "primaryRequirement": "Cloud Infrastructure",
    "procurement": "The DoD is seeking cloud migration services...",
    "sourceURL": "https://sam.gov/opp/12345",
    "duration": "5 years",
    "competitionTypes": [{"title": "Full and Open"}],
    "contractTypes": [{"title": "FFP"}],
    "typeOfAward": "Contract",
    "links": {"webHref": {"href": "https://iq.govwin.com/neo/opportunity/view/12345"}},
}

SAMPLE_CONTACT_JSON = {
    "contactId": "C001",
    "firstName": "Jane",
    "lastName": "Smith",
    "email": "jane.smith@dod.gov",
    "phone": "202-555-0100",
    "title": "Contracting Officer",
    "address1": "1400 Defense Pentagon",
    "city": "Washington",
    "state": "DC",
    "country": "USA",
    "zip": "20301",
    "govEntityLevel1": "Department of Defense",
    "govEntityLevel2": "Office of the CIO",
}

SAMPLE_GOV_ENTITY_JSON = {
    "id": 100,
    "title": "Department of Defense",
    "parentHierarchy": [{"id": 1, "title": "Federal Government"}],
}


# ---------------------------------------------------------------------------
# HTTP Mock Fixtures (respx)
# ---------------------------------------------------------------------------

@pytest.fixture
def govwin_mock():
    with respx.mock(base_url="https://services.govwin.com/neo-ws") as mock:
        yield mock


@pytest.fixture
def hubspot_mock():
    with respx.mock(base_url="https://api.hubapi.com") as mock:
        yield mock
