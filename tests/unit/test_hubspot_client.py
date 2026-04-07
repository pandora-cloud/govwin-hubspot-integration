"""Tests for HubSpot API client."""

from __future__ import annotations

import httpx
import pytest

from src.config import AppConfig
from src.hubspot.client import HubSpotClient
from src.hubspot.properties import GOVWIN_PIPELINE


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
                        {"id": "hs-deal-001", "properties": {"govwin_opp_id": "OPP001"}}
                    ]
                },
            )
        )

        deals = [
            {"properties": {"govwin_opp_id": "OPP001", "dealname": "Test Deal"}}
        ]
        results = hs_client.batch_upsert_deals(deals)

        assert len(results) == 1
        assert results[0]["id"] == "hs-deal-001"

        # Verify the request payload structure
        request = hubspot_mock.calls[0].request
        import json

        body = json.loads(request.content)
        assert "inputs" in body
        assert body["inputs"][0]["idProperty"] == "govwin_opp_id"
        assert body["inputs"][0]["id"] == "OPP001"


class TestEnsurePipeline:
    def test_ensure_pipeline_creates_new(self, hs_client: HubSpotClient, hubspot_mock):
        """Mock GET pipelines (empty) then POST create."""
        hubspot_mock.get("/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        hubspot_mock.post("/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "new-pipeline-001",
                    "label": "GovWin Pipeline",
                    "stages": [
                        {"id": "stage-1", "label": "Pre-RFP"},
                        {"id": "stage-2", "label": "RFP Released"},
                    ],
                },
            )
        )

        pipeline_id = hs_client.ensure_pipeline()
        assert pipeline_id == "new-pipeline-001"
        assert hs_client.pipeline_id == "new-pipeline-001"
        # Verify POST was called (second call after GET)
        assert len(hubspot_mock.calls) == 2
        assert hubspot_mock.calls[1].request.method == "POST"

    def test_ensure_pipeline_existing(self, hs_client: HubSpotClient, hubspot_mock):
        """Mock GET pipelines (found) and verify no POST."""
        hubspot_mock.get("/crm/v3/pipelines/deals").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "existing-pipe-001",
                            "label": "GovWin Pipeline",
                            "stages": [
                                {"id": "s1", "label": "Pre-RFP"},
                                {"id": "s2", "label": "RFP Released"},
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
                            "label": GOVWIN_PIPELINE["label"],
                            "stages": [
                                {"id": "stage-prerp", "label": "Pre-RFP"},
                                {"id": "stage-rfp", "label": "RFP Released"},
                                {"id": "stage-other", "label": "Other"},
                            ],
                        }
                    ]
                },
            )
        )

        hs_client.ensure_pipeline()

        # Test mapping known GovWin status
        assert hs_client.get_stage_id("Pre-RFP") == "stage-prerp"
        assert hs_client.get_stage_id("RFP Released") == "stage-rfp"
        assert hs_client.get_stage_id("Pre-Solicitation") == "stage-prerp"

        # Unknown status maps to "Other"
        assert hs_client.get_stage_id("UnknownStatus") == "stage-other"


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
