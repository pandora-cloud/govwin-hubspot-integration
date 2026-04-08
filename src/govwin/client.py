"""GovWin WSAPI V3 client for retrieving opportunities, entities, and companies."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import AppConfig
from src.govwin.auth import GovWinAuth, GovWinAuthError
from src.govwin.rate_limiter import TokenBucketRateLimiter
from src.models import (
    GovWinCompany,
    GovWinContact,
    GovWinContract,
    GovWinGovEntity,
    GovWinMeta,
    GovWinOpportunity,
    GovWinOpportunityBundle,
)

logger = logging.getLogger(__name__)


class GovWinAPIError(Exception):
    """Raised for GovWin API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class GovWinRateLimitError(GovWinAPIError):
    """Raised when the GovWin rate limit is hit."""

    def __init__(self, wait_seconds: float = 300) -> None:
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit exceeded. Wait {wait_seconds}s.")


class GovWinClient:
    """Client for the GovWin WSAPI V3."""

    def __init__(self, config: AppConfig, auth: GovWinAuth | None = None) -> None:
        self._config = config
        self._base_url = config.govwin.base_url
        self._auth = auth or GovWinAuth(config)
        self._rate_limiter = TokenBucketRateLimiter(
            max_calls_per_hour=config.govwin.rate_limit_per_hour
        )
        self._http = httpx.Client(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=5))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GovWinClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def rate_limiter(self) -> TokenBucketRateLimiter:
        return self._rate_limiter

    # -----------------------------------------------------------------------
    # Core HTTP
    # -----------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.RequestError, GovWinAPIError))
        & retry_if_not_exception_type((GovWinRateLimitError, GovWinAuthError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Make an authenticated, rate-limited API request."""
        wait = self._rate_limiter.acquire()
        if wait > 0:
            raise GovWinRateLimitError(wait_seconds=wait)

        url = f"{self._base_url}/{path.lstrip('/')}"
        headers = self._auth.get_auth_headers()

        # Let httpx.RequestError propagate directly so tenacity can retry it
        response = self._http.request(method, url, headers=headers, **kwargs)

        # Record the call after it completes (acquire is side-effect-free)
        self._rate_limiter.record_call()

        if response.status_code == 401:
            # Token expired — invalidate and raise so tenacity retries with fresh token
            self._auth.invalidate()
            raise GovWinAPIError("Token expired", status_code=401)

        if response.status_code == 403:
            body = response.text.lower()
            if "too many requests" in body:
                raise GovWinRateLimitError()
            logger.debug("GovWin 403 response: %s", response.text)
            raise GovWinAPIError("Forbidden", status_code=403)

        if response.status_code == 404:
            return {}

        if response.status_code >= 400:
            raise GovWinAPIError(
                f"API error {response.status_code}", status_code=response.status_code
            )

        return response.json() if response.text else {}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    # -----------------------------------------------------------------------
    # Opportunities
    # -----------------------------------------------------------------------

    def search_opportunities(
        self,
        *,
        opp_type: str = "ALL",
        market: str = "",
        opp_selection_date_from: str = "",
        opp_selection_date_to: str = "",
        opp_category: str = "2",
        saved_search_id: str = "",
        bookmarked_only: bool = False,
        q: str = "",
        max_results: int = 100,
        offset: int = 0,
        sort: str = "updatedDate",
        order: str = "desc",
    ) -> tuple[list[GovWinOpportunity], GovWinMeta]:
        """Search for opportunities with filtering and pagination."""
        params: dict[str, Any] = {
            "max": min(max_results, self._config.govwin.max_page_size),
            "offset": offset,
            "sort": sort,
            "order": order,
            "oppCategory": opp_category,
        }

        if opp_type and opp_type != "ALL":
            params["oppType"] = opp_type
        if market:
            params["market"] = market
        if opp_selection_date_from:
            params["oppSelectionDateFrom"] = opp_selection_date_from
        if opp_selection_date_to:
            params["oppSelectionDateTo"] = opp_selection_date_to
        if saved_search_id:
            params["savedSearchId"] = saved_search_id
        if bookmarked_only:
            params["markedOpps"] = "true"
        if q:
            params["q"] = q

        data = self._get("opportunities", params=params)
        meta = GovWinMeta.model_validate(data.get("meta", {}))
        opps = [
            GovWinOpportunity.model_validate(o) for o in data.get("opportunities", [])
        ]
        return opps, meta

    def get_marked_opportunities(
        self,
        *,
        marked_version: str = "2.2",
        opp_type: str = "ALL",
        max_results: int = 100,
        offset: int = 0,
    ) -> tuple[list[GovWinOpportunity], GovWinMeta]:
        """Get opportunities marked for download/sync in GovWin.

        marked_version: "2" = Deltek CRM, "2.2" = Web Services Download
        """
        params: dict[str, Any] = {
            "markedVersion": marked_version,
            "max": min(max_results, self._config.govwin.max_page_size),
            "offset": offset,
        }
        if opp_type and opp_type != "ALL":
            params["oppType"] = opp_type

        data = self._get("opportunities", params=params)
        meta = GovWinMeta.model_validate(data.get("meta", {}))
        opps = [
            GovWinOpportunity.model_validate(o) for o in data.get("opportunities", [])
        ]
        return opps, meta

    def get_all_marked_opportunities(
        self,
        *,
        marked_version: str = "2.2",
        opp_type: str = "ALL",
    ) -> list[GovWinOpportunity]:
        """Get all marked opportunities with automatic pagination."""
        all_opps: list[GovWinOpportunity] = []
        offset = 0
        page_size = self._config.govwin.max_page_size
        total_available = 0

        while True:
            opps, meta = self.get_marked_opportunities(
                marked_version=marked_version,
                opp_type=opp_type,
                max_results=page_size,
                offset=offset,
            )
            all_opps.extend(opps)
            total_available = meta.paging.total_count

            if not opps or offset + page_size >= total_available:
                break
            offset += page_size

        logger.info(
            "Retrieved %d marked opportunities (version=%s, total: %d)",
            len(all_opps), marked_version, total_available,
        )
        return all_opps

    def search_all_opportunities(
        self, **kwargs: Any
    ) -> list[GovWinOpportunity]:
        """Search with automatic pagination, returning all matching opportunities."""
        all_opps: list[GovWinOpportunity] = []
        offset = 0
        page_size = self._config.govwin.max_page_size
        total_available = 0

        while True:
            opps, meta = self.search_opportunities(
                max_results=page_size, offset=offset, **kwargs
            )
            all_opps.extend(opps)
            total_available = meta.paging.total_count

            if not opps or offset + page_size >= total_available:
                break
            offset += page_size

        logger.info("Retrieved %d opportunities (total: %d)", len(all_opps), total_available)
        return all_opps

    def get_opportunity(self, global_opp_id: str) -> GovWinOpportunity | None:
        """Get a single opportunity by its global ID."""
        data = self._get(f"opportunities/{global_opp_id}")
        opps = data.get("opportunities", [])
        if not opps:
            return None
        return GovWinOpportunity.model_validate(opps[0])

    def get_opportunities_by_ids(
        self, global_opp_ids: list[str]
    ) -> list[GovWinOpportunity]:
        """Get multiple opportunities by IDs (max 10 per request)."""
        results: list[GovWinOpportunity] = []
        for i in range(0, len(global_opp_ids), 10):
            batch = global_opp_ids[i : i + 10]
            ids_str = ",".join(batch)
            data = self._get(f"opportunities/{ids_str}")
            results.extend(
                GovWinOpportunity.model_validate(o)
                for o in data.get("opportunities", [])
            )
        return results

    # -----------------------------------------------------------------------
    # Extended Opportunity Attributes
    # -----------------------------------------------------------------------

    def _get_opp_attribute(
        self, global_opp_id: str, attribute: str, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """Get an extended attribute for an opportunity."""
        data = self._get(
            f"opportunities/{global_opp_id}/{attribute}",
            params={"max": max_results},
        )
        return data.get(attribute, [])

    def get_opportunity_contacts(self, global_opp_id: str) -> list[GovWinContact]:
        raw = self._get_opp_attribute(global_opp_id, "contacts")
        return [GovWinContact.model_validate(c) for c in raw]

    def get_opportunity_companies(self, global_opp_id: str) -> list[GovWinCompany]:
        raw = self._get_opp_attribute(global_opp_id, "companies")
        return [GovWinCompany.model_validate(c) for c in raw]

    def get_opportunity_contracts(self, global_opp_id: str) -> list[GovWinContract]:
        raw = self._get_opp_attribute(global_opp_id, "contracts")
        return [GovWinContract.model_validate(c) for c in raw]

    def get_opportunity_places_of_performance(
        self, global_opp_id: str
    ) -> list[dict[str, Any]]:
        return self._get_opp_attribute(global_opp_id, "placesOfPerformance")

    def get_opportunity_bundle(self, global_opp_id: str) -> GovWinOpportunityBundle | None:
        """Fetch an opportunity with all its extended attributes."""
        opp = self.get_opportunity(global_opp_id)
        if not opp:
            return None

        contacts = self.get_opportunity_contacts(global_opp_id)
        companies = self.get_opportunity_companies(global_opp_id)
        contracts = self.get_opportunity_contracts(global_opp_id)
        places = self.get_opportunity_places_of_performance(global_opp_id)

        return GovWinOpportunityBundle(
            opportunity=opp,
            contacts=contacts,
            companies=companies,
            contracts=contracts,
            places_of_performance=places,
        )

    # -----------------------------------------------------------------------
    # Gov Entities
    # -----------------------------------------------------------------------

    def get_gov_entity(self, entity_id: int) -> GovWinGovEntity | None:
        data = self._get(f"govEntities/{entity_id}")
        entities = data.get("govEntities", [])
        if not entities:
            return None
        return GovWinGovEntity.model_validate(entities[0])

    def search_gov_entities(
        self,
        q: str = "",
        entity_type: str = "",
        max_results: int = 100,
        offset: int = 0,
    ) -> list[GovWinGovEntity]:
        params: dict[str, Any] = {"max": max_results, "offset": offset}
        if q:
            params["q"] = q
        if entity_type:
            params["type"] = entity_type

        data = self._get("govEntities", params=params)
        return [
            GovWinGovEntity.model_validate(e) for e in data.get("govEntities", [])
        ]

    # -----------------------------------------------------------------------
    # Companies
    # -----------------------------------------------------------------------

    def get_company(self, company_id: int) -> GovWinCompany | None:
        data = self._get(f"companies/{company_id}")
        companies = data.get("companies", [])
        if not companies:
            return None
        return GovWinCompany.model_validate(companies[0])

    def search_companies(
        self,
        company_profile_name: str = "",
        naics: str = "",
        max_results: int = 100,
        offset: int = 0,
    ) -> list[GovWinCompany]:
        params: dict[str, Any] = {"max": max_results, "offset": offset}
        if company_profile_name:
            params["companyProfileName"] = company_profile_name
        if naics:
            params["naics"] = naics

        data = self._get("companies", params=params)
        return [
            GovWinCompany.model_validate(c) for c in data.get("companies", [])
        ]
