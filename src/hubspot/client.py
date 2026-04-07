"""HubSpot API client for deals, companies, contacts, properties, and associations."""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import AppConfig
from src.hubspot.properties import (
    COMPANY_PROPERTIES,
    CONTACT_PROPERTIES,
    DEAL_PROPERTIES,
    GOVWIN_PIPELINE,
    GOVWIN_STATUS_TO_STAGE,
    PROPERTY_GROUP,
)
from src.hubspot.rate_limiter import HubSpotRateLimiter
from src.models import HubSpotProperty

logger = logging.getLogger(__name__)


class HubSpotAPIError(Exception):
    """Raised for HubSpot API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class HubSpotRateLimitError(HubSpotAPIError):
    """Raised when HubSpot rate limit is hit."""


class HubSpotClient:
    """Client for the HubSpot CRM API v3."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._base_url = config.hubspot.base_url
        self._rate_limiter = HubSpotRateLimiter(
            max_requests=config.hubspot.rate_limit_per_10s,
            buffer=config.hubspot.rate_limit_buffer,
        )
        self._token: str | None = None
        self._http = httpx.Client(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=5))
        self._pipeline_id: str | None = None
        self._secrets_client = boto3.client(
            "secretsmanager", region_name=config.aws.region
        )
        self._stage_label_to_id: dict[str, str] = {}

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> HubSpotClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def pipeline_id(self) -> str | None:
        return self._pipeline_id

    def _get_token(self) -> str:
        if self._token:
            return self._token
        try:
            response = self._secrets_client.get_secret_value(
                SecretId=self._config.aws.hubspot_secret_name
            )
            data = json.loads(response["SecretString"])
            self._token = data["private_app_token"]
            return self._token  # type: ignore[return-value]
        except ClientError as e:
            raise HubSpotAPIError(f"Failed to load HubSpot token: {e}") from e

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    @retry(
        retry=retry_if_exception_type((HubSpotRateLimitError, httpx.RequestError)),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request(
        self, method: str, path: str, json_data: Any = None, params: dict | None = None
    ) -> dict[str, Any]:
        self._rate_limiter.wait_if_needed()

        url = f"{self._base_url}/{path.lstrip('/')}"
        # Let httpx.RequestError propagate directly so tenacity can retry it
        response = self._http.request(
            method, url, headers=self._headers(), json=json_data, params=params
        )

        if response.status_code == 401:
            self._token = None
            response = self._http.request(
                method, url, headers=self._headers(), json=json_data, params=params
            )

        if response.status_code == 429:
            logger.warning("HubSpot rate limit hit (429)")
            raise HubSpotRateLimitError("Rate limit exceeded")

        if response.status_code >= 400:
            logger.debug("HubSpot error response %d: %s", response.status_code, response.text)
            raise HubSpotAPIError(
                f"HubSpot API error {response.status_code}",
                status_code=response.status_code,
            )

        return response.json() if response.text else {}

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: Any) -> dict[str, Any]:
        return self._request("POST", path, json_data=data)

    def _patch(self, path: str, data: Any) -> dict[str, Any]:
        return self._request("PATCH", path, json_data=data)

    def _put(self, path: str, data: Any = None) -> dict[str, Any]:
        return self._request("PUT", path, json_data=data)

    def _delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path)

    # -----------------------------------------------------------------------
    # Property Group Setup
    # -----------------------------------------------------------------------

    def ensure_property_group(self, object_type: str) -> None:
        """Create the govwin property group if it doesn't exist."""
        try:
            self._post(
                f"crm/v3/properties/{object_type}/groups",
                PROPERTY_GROUP,
            )
            logger.info("Created property group 'govwin' on %s", object_type)
        except HubSpotAPIError as e:
            if e.status_code == 409:
                logger.debug("Property group 'govwin' already exists on %s", object_type)
            else:
                raise

    def ensure_property(self, object_type: str, prop: HubSpotProperty) -> None:
        """Create a custom property if it doesn't exist."""
        payload: dict[str, Any] = {
            "name": prop.name,
            "label": prop.label,
            "type": prop.type,
            "fieldType": prop.field_type,
            "groupName": prop.group_name,
            "description": prop.description,
        }
        if prop.options:
            payload["options"] = prop.options

        try:
            self._post(f"crm/v3/properties/{object_type}", payload)
            logger.info("Created property %s on %s", prop.name, object_type)
        except HubSpotAPIError as e:
            if e.status_code == 409:
                logger.debug("Property %s already exists on %s", prop.name, object_type)
            else:
                raise

    def ensure_all_properties(self) -> None:
        """Create all custom properties and groups for all object types."""
        for obj_type in ("deals", "companies", "contacts"):
            self.ensure_property_group(obj_type)

        for prop in DEAL_PROPERTIES:
            self.ensure_property("deals", prop)

        for prop in COMPANY_PROPERTIES:
            self.ensure_property("companies", prop)

        for prop in CONTACT_PROPERTIES:
            self.ensure_property("contacts", prop)

        logger.info(
            "Ensured %d deal, %d company, %d contact properties",
            len(DEAL_PROPERTIES),
            len(COMPANY_PROPERTIES),
            len(CONTACT_PROPERTIES),
        )

    # -----------------------------------------------------------------------
    # Pipeline Setup
    # -----------------------------------------------------------------------

    def ensure_pipeline(self) -> str:
        """Create the GovWin pipeline if it doesn't exist. Returns pipeline ID."""
        # Check existing pipelines
        existing = self._get("crm/v3/pipelines/deals")
        for pipeline in existing.get("results", []):
            if pipeline.get("label") == GOVWIN_PIPELINE["label"]:
                self._pipeline_id = pipeline["id"]
                self._cache_stage_ids(pipeline)
                logger.info("GovWin pipeline already exists (ID: %s)", self._pipeline_id)
                return self._pipeline_id

        # Create new pipeline
        result = self._post("crm/v3/pipelines/deals", GOVWIN_PIPELINE)
        self._pipeline_id = result["id"]
        self._cache_stage_ids(result)
        logger.info("Created GovWin pipeline (ID: %s)", self._pipeline_id)
        return self._pipeline_id

    def _cache_stage_ids(self, pipeline_data: dict) -> None:
        """Cache the mapping from stage labels to internal IDs."""
        self._stage_label_to_id.clear()
        for stage in pipeline_data.get("stages", []):
            self._stage_label_to_id[stage["label"]] = stage["id"]

    def get_stage_id(self, govwin_status: str) -> str | None:
        """Map a GovWin status to a HubSpot pipeline stage ID."""
        stage_label = GOVWIN_STATUS_TO_STAGE.get(govwin_status, "Other")
        return self._stage_label_to_id.get(stage_label)

    # -----------------------------------------------------------------------
    # Deals
    # -----------------------------------------------------------------------

    def batch_upsert_deals(self, deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch upsert deals using govwin_opp_id as the dedup key."""
        results: list[dict[str, Any]] = []

        for i in range(0, len(deals), self._config.hubspot.max_batch_size):
            batch = deals[i : i + self._config.hubspot.max_batch_size]
            inputs = [
                {
                    "idProperty": "govwin_opp_id",
                    "id": deal["properties"]["govwin_opp_id"],
                    "properties": deal["properties"],
                }
                for deal in batch
                if deal.get("properties", {}).get("govwin_opp_id")
            ]

            if not inputs:
                continue

            try:
                result = self._post(
                    "crm/v3/objects/deals/batch/upsert",
                    {"inputs": inputs},
                )
                results.extend(result.get("results", []))
                logger.info("Upserted %d deals", len(inputs))
            except HubSpotAPIError:
                logger.exception("Failed to upsert deal batch starting at index %d", i)
                raise

        return results

    def search_deal_by_govwin_id(self, govwin_opp_id: str) -> dict[str, Any] | None:
        """Search for a deal by its GovWin opportunity ID."""
        result = self._post(
            "crm/v3/objects/deals/search",
            {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "govwin_opp_id",
                                "operator": "EQ",
                                "value": govwin_opp_id,
                            }
                        ]
                    }
                ],
                "properties": ["govwin_opp_id", "dealname", "dealstage"],
            },
        )
        results = result.get("results", [])
        return results[0] if results else None

    # -----------------------------------------------------------------------
    # Companies
    # -----------------------------------------------------------------------

    def batch_upsert_companies(self, companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch upsert companies using govwin_gov_entity_id as the dedup key."""
        results: list[dict[str, Any]] = []

        for i in range(0, len(companies), self._config.hubspot.max_batch_size):
            batch = companies[i : i + self._config.hubspot.max_batch_size]
            inputs = [
                {
                    "idProperty": "govwin_gov_entity_id",
                    "id": co["properties"]["govwin_gov_entity_id"],
                    "properties": co["properties"],
                }
                for co in batch
                if co.get("properties", {}).get("govwin_gov_entity_id")
            ]

            if not inputs:
                continue

            try:
                result = self._post(
                    "crm/v3/objects/companies/batch/upsert",
                    {"inputs": inputs},
                )
                results.extend(result.get("results", []))
                logger.info("Upserted %d companies", len(inputs))
            except HubSpotAPIError:
                logger.exception("Failed to upsert company batch starting at index %d", i)
                raise

        return results

    # -----------------------------------------------------------------------
    # Contacts
    # -----------------------------------------------------------------------

    def batch_upsert_contacts(self, contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch upsert contacts using email as the dedup key."""
        results: list[dict[str, Any]] = []

        # Split: contacts with email use email as idProperty, others use govwin_contact_id
        email_contacts = [c for c in contacts if c.get("properties", {}).get("email")]
        id_contacts = [
            c for c in contacts
            if not c.get("properties", {}).get("email")
            and c.get("properties", {}).get("govwin_contact_id")
        ]

        for batch_list, id_prop in [(email_contacts, "email"), (id_contacts, "govwin_contact_id")]:
            for i in range(0, len(batch_list), self._config.hubspot.max_batch_size):
                batch = batch_list[i : i + self._config.hubspot.max_batch_size]
                inputs = [
                    {
                        "idProperty": id_prop,
                        "id": c["properties"][id_prop],
                        "properties": c["properties"],
                    }
                    for c in batch
                ]

                if not inputs:
                    continue

                try:
                    result = self._post(
                        "crm/v3/objects/contacts/batch/upsert",
                        {"inputs": inputs},
                    )
                    results.extend(result.get("results", []))
                    logger.info("Upserted %d contacts (key: %s)", len(inputs), id_prop)
                except HubSpotAPIError:
                    logger.exception("Failed to upsert contact batch")
                    raise

        return results

    # -----------------------------------------------------------------------
    # Associations
    # -----------------------------------------------------------------------

    def create_association(
        self,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        association_category: str = "HUBSPOT_DEFINED",
        association_type_id: int | None = None,
    ) -> None:
        """Create an association between two CRM objects."""
        # Default association type IDs for common associations
        if association_type_id is None:
            type_map = {
                ("deals", "companies"): 341,
                ("deals", "contacts"): 3,
                ("companies", "contacts"): 279,
            }
            key = (from_type, to_type)
            association_type_id = type_map.get(key, 1)

        try:
            self._put(
                f"crm/v4/objects/{from_type}/{from_id}/associations/{to_type}/{to_id}",
                [
                    {
                        "associationCategory": association_category,
                        "associationTypeId": association_type_id,
                    }
                ],
            )
        except HubSpotAPIError:
            logger.warning(
                "Failed to create association %s/%s -> %s/%s",
                from_type, from_id, to_type, to_id,
            )

    def batch_create_associations(
        self,
        from_type: str,
        to_type: str,
        associations: list[tuple[str, str]],
    ) -> None:
        """Create multiple associations using the HubSpot batch API."""
        if not associations:
            return

        type_map = {
            ("deals", "companies"): 341,
            ("deals", "contacts"): 3,
            ("companies", "contacts"): 279,
        }
        key = (from_type, to_type)
        association_type_id = type_map.get(key, 1)

        batch_size = self._config.hubspot.max_batch_size
        for i in range(0, len(associations), batch_size):
            batch = associations[i : i + batch_size]
            inputs = [
                {
                    "from": {"id": from_id},
                    "to": {"id": to_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": association_type_id,
                        }
                    ],
                }
                for from_id, to_id in batch
            ]
            try:
                self._post(
                    f"crm/v4/associations/{from_type}/{to_type}/batch/create",
                    {"inputs": inputs},
                )
            except HubSpotAPIError:
                logger.warning(
                    "Failed to batch create associations %s -> %s (batch index %d)",
                    from_type, to_type, i,
                )

    # -----------------------------------------------------------------------
    # Setup (one-time)
    # -----------------------------------------------------------------------

    def setup(self) -> dict[str, Any]:
        """Run one-time setup: create properties, groups, and pipeline."""
        self.ensure_all_properties()
        pipeline_id = self.ensure_pipeline()
        return {
            "pipeline_id": pipeline_id,
            "deal_properties": len(DEAL_PROPERTIES),
            "company_properties": len(COMPANY_PROPERTIES),
            "contact_properties": len(CONTACT_PROPERTIES),
        }
