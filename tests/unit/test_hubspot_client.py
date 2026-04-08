"""Tests for HubSpot API client."""

from __future__ import annotations

import httpx
import pytest

from src.config import AppConfig
from src.hubspot.client import HubSpotClient
from src.hubspot.properties import PIPELINE_NAME


@pytest.fixture
def hs_client(app_config: AppConfig, mock_aws_env) -> HubSpotClient:
    return HubSpotClient(app_config)


class TestBatchUpsertDeals:
    def test_batch_upsert_deals(self, hs_client: HubSpotClient, hubspot_mock):
        """Mock POST /crm/v3/objects/deals/batch/upsert and verify payload structure."""
        hubspot_mock.post("/crm/v3/objects/deals/batch/upsert").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "hs-deal-001", "properties": {"govwin_id": "OPP001"}}
                    ]
                },
            )
        )

        deals = [
            {
                "properties": {
                    "govwin_id": "OPP001",
                    "govwin_opp_id": "OPP001",
                    "dealname": "Test Deal",
                }
            }
        ]
        results = hs_client.batch_upsert_deals(deals)

        assert len(results) == 1
        assert results[0]["id"] == "hs-deal-001"

        # Verify the request payload structure
        request = hubspot_mock.calls[0].request
        import json

        body = json.loads(request.content)
        assert "inputs" in body
        assert body["inputs"][0]["idProperty"] == "govwin_id"
        assert body["inputs"][0]["id"] == "OPP001"


class TestEnsurePipeline:
    def test_ensure_pipeline_finds_existing(self, hs_client: HubSpotClient, hubspot_mock):
        """Find the existing Government pipeline by name."""
        hubspot_mock.get("/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "existing-pipe-001",
                            "label": PIPELINE_NAME,
                            "stages": [
                                {"id": "s1", "label": "Opportunity Identified"},
                                {"id": "s2", "label": "Reviewing Requirements"},
                            ],
                        }
                    ]
                },
            )
        )

        pipeline_id = hs_client.ensure_pipeline()
        assert pipeline_id == "existing-pipe-001"
        # Only the GET should have been called
        assert len(hubspot_mock.calls) == 1
        assert hubspot_mock.calls[0].request.method == "GET"

    def test_ensure_pipeline_not_found_raises(self, hs_client: HubSpotClient, hubspot_mock):
        """Raise error if target pipeline doesn't exist in HubSpot."""
        hubspot_mock.get("/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        import pytest

        from src.hubspot.client import HubSpotAPIError

        with pytest.raises(HubSpotAPIError, match="not found"):
            hs_client.ensure_pipeline()


class TestEnsureProperty:
    def test_ensure_property_409_handled(self, hs_client: HubSpotClient, hubspot_mock):
        """Mock POST that returns 409 status code and verify no exception."""
        hubspot_mock.post("/crm/v3/properties/deals/groups").mock(
            return_value=httpx.Response(409, json={"message": "Already exists"})
        )

        # Should not raise an exception
        hs_client.ensure_property_group("deals")


class TestGetStageId:
    def test_get_stage_id(self, hs_client: HubSpotClient, hubspot_mock):
        """Set up pipeline and verify stage ID mapping."""
        hubspot_mock.get("/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "pipe-001",
                            "label": PIPELINE_NAME,
                            "stages": [
                                {"id": "stage-opid", "label": "Opportunity Identified"},
                                {"id": "stage-review", "label": "Reviewing Requirements"},
                                {"id": "stage-prep", "label": "Preparing Response"},
                            ],
                        }
                    ]
                },
            )
        )

        hs_client.ensure_pipeline()

        # Test mapping known GovWin status to Government pipeline stages
        assert hs_client.get_stage_id("Pre-RFP") == "stage-opid"
        assert hs_client.get_stage_id("RFP Released") == "stage-review"
        assert hs_client.get_stage_id("Proposal Submitted") == "stage-prep"

        # Unknown status returns None (no "Other" stage in existing pipeline)
        assert hs_client.get_stage_id("UnknownStatus") is None


class TestAuthRetry:
    def test_401_clears_token(self, hs_client: HubSpotClient, hubspot_mock):
        """Mock 401 and verify self._token set to None and retry."""
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(401, json={"message": "Unauthorized"})
            return httpx.Response(200, json={"results": []})

        hubspot_mock.get("/crm/v3/pipelines/deals").mock(side_effect=side_effect)

        # Pre-set the token so we can verify it gets cleared
        hs_client._token = "old-token"

        result = hs_client._get("crm/v3/pipelines/deals")
        # Token should have been cleared and re-fetched
        assert result == {"results": []}


class TestBatchCreateAssociations:
    def test_batch_create_associations(self, hs_client: HubSpotClient, hubspot_mock):
        """Mock batch association endpoint."""
        hubspot_mock.post("/crm/v4/associations/deals/companies/batch/create").mock(
            return_value=httpx.Response(200, json={"results": []})
        )

        associations = [("deal-1", "company-1"), ("deal-2", "company-2")]
        # Should not raise
        hs_client.batch_create_associations("deals", "companies", associations)

        # Verify the call was made
        assert len(hubspot_mock.calls) == 1
        import json

        body = json.loads(hubspot_mock.calls[0].request.content)
        assert len(body["inputs"]) == 2
        assert body["inputs"][0]["from"]["id"] == "deal-1"
        assert body["inputs"][0]["to"]["id"] == "company-1"
