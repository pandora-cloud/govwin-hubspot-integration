"""Tests for GovWin API client."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import httpx
import pytest

from src.config import AppConfig
from src.govwin.auth import GovWinAuth
from src.govwin.client import GovWinClient, GovWinRateLimitError


@pytest.fixture
def mock_auth():
    """Create a mock GovWinAuth that returns a fixed token."""
    auth = MagicMock(spec=GovWinAuth)
    auth.get_auth_headers.return_value = {"Authorization": "Bearer test-token"}
    type(auth).access_token = PropertyMock(return_value="test-token")
    return auth


@pytest.fixture
def client(app_config: AppConfig, mock_auth) -> GovWinClient:
    return GovWinClient(app_config, auth=mock_auth)


class TestSearchOpportunities:
    def test_search_opportunities(self, client: GovWinClient, govwin_mock):
        """Mock GET /opportunities response and verify pagination params."""
        govwin_mock.get("/opportunities").mock(
            return_value=httpx.Response(
                200,
                json={
                    "meta": {
                        "paging": {
                            "max": 100,
                            "offset": 0,
                            "totalCount": 1,
                            "sort": "updatedDate",
                            "order": "desc",
                        }
                    },
                    "opportunities": [
                        {
                            "id": "OPP001",
                            "title": "Test Opportunity",
                            "updateDate": "2025-03-20T14:00:00Z",
                        }
                    ],
                },
            )
        )

        opps, meta = client.search_opportunities(
            opp_type="ALL", max_results=100, offset=0
        )

        assert len(opps) == 1
        assert opps[0].id == "OPP001"
        assert meta.paging.total_count == 1

        # Verify the request was made with pagination params
        request = govwin_mock.calls[0].request
        assert b"max=100" in request.url.query
        assert b"offset=0" in request.url.query


class TestGetOpportunity:
    def test_get_opportunity(self, client: GovWinClient, govwin_mock):
        """Mock single opportunity response."""
        govwin_mock.get("/opportunities/OPP001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "opportunities": [
                        {
                            "id": "OPP001",
                            "title": "Test Opportunity",
                            "status": "Pre-RFP",
                        }
                    ]
                },
            )
        )

        opp = client.get_opportunity("OPP001")
        assert opp is not None
        assert opp.id == "OPP001"
        assert opp.status == "Pre-RFP"


class TestGetOpportunityBundle:
    def test_get_opportunity_bundle(self, client: GovWinClient, govwin_mock):
        """Mock opportunity + contacts + companies + contracts + placesOfPerformance."""
        govwin_mock.get("/opportunities/OPP001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "opportunities": [
                        {"id": "OPP001", "title": "Test Opp", "status": "RFP"}
                    ]
                },
            )
        )
        govwin_mock.get("/opportunities/OPP001/contacts").mock(
            return_value=httpx.Response(
                200,
                json={"contacts": [{"contactId": "C001", "firstName": "Jane"}]},
            )
        )
        govwin_mock.get("/opportunities/OPP001/companies").mock(
            return_value=httpx.Response(200, json={"companies": []})
        )
        govwin_mock.get("/opportunities/OPP001/contracts").mock(
            return_value=httpx.Response(200, json={"contracts": []})
        )
        govwin_mock.get("/opportunities/OPP001/placesOfPerformance").mock(
            return_value=httpx.Response(200, json={"placesOfPerformance": []})
        )

        bundle = client.get_opportunity_bundle("OPP001")
        assert bundle is not None
        assert bundle.opportunity.id == "OPP001"
        assert len(bundle.contacts) == 1
        assert bundle.contacts[0].contact_id == "C001"


class TestErrorHandling:
    def test_401_triggers_reauth(self, client: GovWinClient, govwin_mock):
        """Mock first call 401, second succeeds after token refresh."""
        route = govwin_mock.get("/opportunities/OPP001")
        route.side_effect = [
            httpx.Response(401, json={"error": "Unauthorized"}),
            httpx.Response(
                200,
                json={"opportunities": [{"id": "OPP001", "title": "Test"}]},
            ),
        ]

        opp = client.get_opportunity("OPP001")
        assert opp is not None
        assert opp.id == "OPP001"
        # Auth should have been invalidated
        client._auth.invalidate.assert_called()

    def test_rate_limit_raises(self, client: GovWinClient, govwin_mock):
        """Fill rate limiter and verify GovWinRateLimitError raised."""
        # Fill the rate limiter to capacity
        limiter = client.rate_limiter
        limiter._call_timestamps = [
            __import__("time").time()
        ] * limiter._effective_limit

        with pytest.raises(GovWinRateLimitError):
            client.get_opportunity("OPP001")

    def test_retry_on_transient_error(self, client: GovWinClient, govwin_mock):
        """Mock first call raises a transient error, second succeeds (tenacity retry)."""
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(
                200,
                json={"opportunities": [{"id": "OPP001", "title": "Retry Success"}]},
            )

        govwin_mock.get("/opportunities/OPP001").mock(side_effect=side_effect)

        # The _request method wraps httpx.RequestError into GovWinAPIError
        # and tenacity retries GovWinAPIError, so this should succeed
        opp = client.get_opportunity("OPP001")
        assert opp is not None
        assert opp.title == "Retry Success"

    def test_404_returns_empty(self, client: GovWinClient, govwin_mock):
        """Mock 404 and verify empty dict returned (no opportunity)."""
        govwin_mock.get("/opportunities/OPPNOTFOUND").mock(
            return_value=httpx.Response(404, json={})
        )

        opp = client.get_opportunity("OPPNOTFOUND")
        assert opp is None
