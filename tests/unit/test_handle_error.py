"""Tests for the handle_error Lambda handler."""

from __future__ import annotations

import json

import boto3

from src.lambdas.handle_error import _sanitize_event


class TestSanitizeEvent:
    def test_sanitize_event_strips_sensitive(self):
        """Verify _sanitize_event removes keys with 'token', 'secret', 'password'."""
        event = {
            "error": "SomeError",
            "access_token": "secret-value-123",
            "client_secret": "should-be-removed",
            "password_hash": "also-removed",
            "credential_data": "gone",
        }
        result = _sanitize_event(event)

        assert "error" in result
        assert "access_token" not in result
        assert "client_secret" not in result
        assert "password_hash" not in result
        assert "credential_data" not in result

    def test_sanitize_event_keeps_safe_keys(self):
        """Verify 'error', 'cause', 'status' are preserved."""
        event = {
            "error": "AuthError",
            "cause": "Invalid credentials",
            "status": "failed",
            "deals_synced": 5,
            "opportunities_count": 10,
        }
        result = _sanitize_event(event)

        assert result["error"] == "AuthError"
        assert result["cause"] == "Invalid credentials"
        assert result["status"] == "failed"
        assert result["deals_synced"] == 5
        assert result["opportunities_count"] == 10

    def test_sanitize_event_truncates_long_values(self):
        """Verify strings > 500 chars truncated."""
        long_string = "x" * 1000
        event = {"error": long_string}
        result = _sanitize_event(event)

        assert len(result["error"]) == 500


class TestHandlerSNS:
    def test_handler_sends_to_sns(self, app_config, mock_aws_env, monkeypatch):
        """Mock SNS and verify publish called with sanitized data."""
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("SYNC_STATE_TABLE", "test-sync-state")
        monkeypatch.setenv("ENTITY_MAPPINGS_TABLE", "test-entity-mappings")
        monkeypatch.setenv("GOVWIN_SECRET_NAME", "test/govwin")
        monkeypatch.setenv("HUBSPOT_SECRET_NAME", "test/hubspot")
        monkeypatch.setenv("GOVWIN_TOKENS_SECRET_NAME", "test/govwin-tokens")

        # Create SNS topic
        sns = boto3.client("sns", region_name="us-east-1")
        topic = sns.create_topic(Name="test-error-topic")
        topic_arn = topic["TopicArn"]
        monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)

        from src.lambdas.handle_error import handler

        event = {
            "error": "GovWinAuthError",
            "cause": "Authentication failed",
            "access_token": "should-be-stripped",
        }

        result = handler(event, None)
        assert result["status"] == "error_handled"
        assert result["error"] == "GovWinAuthError"


class TestHandlerSQS:
    def test_handler_sends_to_sqs(self, app_config, mock_aws_env, monkeypatch):
        """Mock SQS and verify send_message called."""
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("SYNC_STATE_TABLE", "test-sync-state")
        monkeypatch.setenv("ENTITY_MAPPINGS_TABLE", "test-entity-mappings")
        monkeypatch.setenv("GOVWIN_SECRET_NAME", "test/govwin")
        monkeypatch.setenv("HUBSPOT_SECRET_NAME", "test/hubspot")
        monkeypatch.setenv("GOVWIN_TOKENS_SECRET_NAME", "test/govwin-tokens")
        monkeypatch.setenv("SNS_TOPIC_ARN", "")  # Disable SNS

        # Create SQS queue
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName="test-dlq")
        queue_url = queue["QueueUrl"]
        monkeypatch.setenv("DLQ_URL", queue_url)

        from src.lambdas.handle_error import handler

        event = {
            "error": "SyncFailure",
            "cause": "HubSpot API error",
        }

        result = handler(event, None)
        assert result["status"] == "error_handled"

        # Verify message was sent to DLQ
        messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1)
        assert "Messages" in messages
        body = json.loads(messages["Messages"][0]["Body"])
        assert body["error"] == "SyncFailure"
