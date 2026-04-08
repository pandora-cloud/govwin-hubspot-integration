"""Tests for the sync_to_hubspot Lambda handler."""

from __future__ import annotations

import httpx
import respx

from tests.conftest import SAMPLE_CONTACT_JSON, SAMPLE_OPPORTUNITY_JSON

BASE = "https://api.hubapi.com"


def _env_vars(monkeypatch):
    """Set environment variables for load_config."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SYNC_STATE_TABLE", "test-sync-state")
    monkeypatch.setenv("ENTITY_MAPPINGS_TABLE", "test-entity-mappings")
    monkeypatch.setenv("GOVWIN_SECRET_NAME", "test/govwin")
    monkeypatch.setenv("HUBSPOT_SECRET_NAME", "test/hubspot")
    monkeypatch.setenv("GOVWIN_TOKENS_SECRET_NAME", "test/govwin-tokens")


class TestSyncToHubspot:
    @respx.mock
    def test_handler_with_bundles(self, app_config, mock_aws_env, monkeypatch):
        """Mock HubSpot client and verify orchestrator called."""
        _env_vars(monkeypatch)

        # Mock pipeline GET (existing)
        respx.get(f"{BASE}/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "pipe-001",
                            "label": "Government",
                            "stages": [
                                {"id": "s1", "label": "Opportunity Identified"},
                                {"id": "s2", "label": "Reviewing Requirements"},
                                {"id": "s3", "label": "Preparing Response"},
                                {"id": "s4", "label": "Submitted"},
                                {"id": "s5", "label": "Closed Won"},
                                {"id": "s6", "label": "Closed Lost"},
                            ],
                        }
                    ]
                },
            )
        )

        # Mock company upsert
        respx.post(f"{BASE}/crm/v3/objects/companies/batch/upsert").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "hs-co-001",
                            "properties": {"govwin_gov_entity_id": "100"},
                        }
                    ]
                },
            )
        )

        # Mock contact upsert
        respx.post(f"{BASE}/crm/v3/objects/contacts/batch/upsert").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        # Mock deal upsert
        respx.post(f"{BASE}/crm/v3/objects/deals/batch/upsert").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "hs-deal-001",
                            "properties": {"govwin_opp_id": "OPP12345"},
                        }
                    ]
                },
            )
        )

        # Mock batch associations
        respx.post(url__regex=r".*/crm/v4/associations/.*/batch/create").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        from src.lambdas.sync_to_hubspot import handler

        event = {
            "bundles": [
                {
                    "opportunity": SAMPLE_OPPORTUNITY_JSON,
                    "contacts": [SAMPLE_CONTACT_JSON],
                    "companies": [],
                    "contracts": [],
                    "places_of_performance": [],
                }
            ],
            "rate_limit_calls_used": 5,
            "errors": [],
        }

        result = handler(event, None)
        assert result["deals_synced"] == 1

    def test_handler_empty_bundles(self, app_config, mock_aws_env, monkeypatch):
        """Pass empty bundles and verify early return."""
        _env_vars(monkeypatch)

        from src.lambdas.sync_to_hubspot import handler

        result = handler({"bundles": []}, None)
        assert result["deals_synced"] == 0
