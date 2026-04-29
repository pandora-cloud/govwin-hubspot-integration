"""Tests for the ACE Selling API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.ace.client import ACEAPIError, ACEClient
from src.config import AppConfig


def _client_error(code: str, message: str = "boom") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="op",
    )


@pytest.fixture
def mock_boto() -> MagicMock:
    return MagicMock()


@pytest.fixture
def ace(app_config: AppConfig, mock_boto: MagicMock) -> ACEClient:
    return ACEClient(app_config, boto3_client=mock_boto)


class TestCreateOpportunity:
    def test_passes_payload_through(self, ace: ACEClient, mock_boto: MagicMock) -> None:
        mock_boto.create_opportunity.return_value = {"Id": "O123", "LastModifiedDate": "2026-01-01"}
        result = ace.create_opportunity(
            {"Catalog": "Sandbox", "ClientToken": "tok", "Project": {"Title": "x"}}
        )
        mock_boto.create_opportunity.assert_called_once()
        kwargs = mock_boto.create_opportunity.call_args.kwargs
        assert kwargs["Catalog"] == "Sandbox"
        assert kwargs["ClientToken"] == "tok"
        assert result["Id"] == "O123"

    def test_injects_catalog_and_client_token_when_missing(
        self, ace: ACEClient, mock_boto: MagicMock
    ) -> None:
        mock_boto.create_opportunity.return_value = {"Id": "O999"}
        ace.create_opportunity({"Project": {"Title": "x"}})
        kwargs = mock_boto.create_opportunity.call_args.kwargs
        assert kwargs["Catalog"] == "Sandbox"
        assert kwargs["ClientToken"]  # uuid generated

    def test_validation_exception_is_not_retried(
        self, ace: ACEClient, mock_boto: MagicMock
    ) -> None:
        mock_boto.create_opportunity.side_effect = _client_error("ValidationException", "bad field")
        with pytest.raises(ACEAPIError) as exc:
            ace.create_opportunity({"Catalog": "Sandbox", "ClientToken": "tok"})
        assert exc.value.code == "ValidationException"
        assert mock_boto.create_opportunity.call_count == 1


class TestRetryBehavior:
    def test_throttling_is_retried(self, ace: ACEClient, mock_boto: MagicMock) -> None:
        mock_boto.create_opportunity.side_effect = [
            _client_error("ThrottlingException"),
            {"Id": "O1"},
        ]
        with patch("time.sleep"):  # tenacity sleeps between attempts
            result = ace.create_opportunity({"Catalog": "Sandbox", "ClientToken": "tok"})
        assert result["Id"] == "O1"
        assert mock_boto.create_opportunity.call_count == 2

    def test_internal_server_exception_is_retried(
        self, ace: ACEClient, mock_boto: MagicMock
    ) -> None:
        mock_boto.create_opportunity.side_effect = [
            _client_error("InternalServerException"),
            {"Id": "O2"},
        ]
        with patch("time.sleep"):
            result = ace.create_opportunity({"Catalog": "Sandbox", "ClientToken": "tok"})
        assert result["Id"] == "O2"


class TestUpdateWithRetry:
    def test_refetches_on_conflict_then_succeeds(
        self, ace: ACEClient, mock_boto: MagicMock
    ) -> None:
        mock_boto.get_opportunity.side_effect = [
            {"LastModifiedDate": "T1"},
            {"LastModifiedDate": "T2"},
        ]
        mock_boto.update_opportunity.side_effect = [
            _client_error("ConflictException"),
            {"Id": "O1", "LastModifiedDate": "T3"},
        ]
        with patch("time.sleep"):
            result = ace.update_with_retry("O1", {"Project": {"Title": "y"}})
        assert result["LastModifiedDate"] == "T3"
        assert mock_boto.update_opportunity.call_count == 2

    def test_raises_after_max_attempts(
        self, ace: ACEClient, mock_boto: MagicMock
    ) -> None:
        mock_boto.get_opportunity.return_value = {"LastModifiedDate": "T1"}
        mock_boto.update_opportunity.side_effect = _client_error("ConflictException")
        with patch("time.sleep"), pytest.raises(ACEAPIError) as exc:
            ace.update_with_retry("O1", {"a": "b"}, max_attempts=2)
        assert exc.value.code == "ConflictException"


class TestAssociateAndStartEngagement:
    def test_associate_passes_args(self, ace: ACEClient, mock_boto: MagicMock) -> None:
        mock_boto.associate_opportunity.return_value = {}
        ace.associate_opportunity("O1", "S-0051246")
        kwargs = mock_boto.associate_opportunity.call_args.kwargs
        assert kwargs["RelatedEntityType"] == "Solutions"
        assert kwargs["RelatedEntityIdentifier"] == "S-0051246"

    def test_start_engagement_uses_config_defaults(
        self, ace: ACEClient, mock_boto: MagicMock
    ) -> None:
        mock_boto.start_engagement_from_opportunity_task.return_value = {"TaskId": "T1"}
        ace.start_engagement_from_opportunity_task("O1", client_token="ct")
        kwargs = mock_boto.start_engagement_from_opportunity_task.call_args.kwargs
        assert kwargs["AwsSubmission"]["InvolvementType"] == "Co-Sell"
        assert kwargs["AwsSubmission"]["Visibility"] == "Full"


def test_new_client_token_returns_uuid() -> None:
    token = ACEClient.new_client_token()
    assert isinstance(token, str)
    assert len(token) == 36
