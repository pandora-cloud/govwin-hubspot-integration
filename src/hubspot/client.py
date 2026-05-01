"""HubSpot API client for deals, companies, contacts, properties, and associations."""

from __future__ import annotations

import json
import logging
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import AppConfig
from src.hubspot.properties import (
    COMPANY_PROPERTIES,
    CONTACT_PROPERTIES,
    DEAL_PROPERTIES,
    DEFAULT_STAGE_LABEL,
    GOVWIN_STATUS_TO_STAGE,
    PIPELINE_NAME,
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
            return self._token
        except ClientError as e:
            raise HubSpotAPIError(f"Failed to load HubSpot token: {e}") from e

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    @retry(
        retry=(
            retry_if_exception_type((HubSpotRateLimitError, httpx.RequestError))
            | retry_if_exception(
                lambda e: isinstance(e, HubSpotAPIError) and e.status_code in (401, 502, 503, 504)
            )
        ),
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
            # Clear token and raise so tenacity retries with fresh credentials
            self._token = None
            raise HubSpotAPIError("Token expired", status_code=401)

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
        """Create a custom property; if it already exists, PATCH it so option
        sets, descriptions, and labels stay in sync with code.

        Without the PATCH path, adding a new dropdown option in code never
        propagated -- HubSpot returned 409 on every redeploy and we silently
        kept the old option set. The mapper would then accept values the
        BD dropdown didn't expose, causing confusing "value not in enum"
        errors only after a CreateOpportunity round-trip.
        """
        payload: dict[str, Any] = {
            "name": prop.name,
            "label": prop.label,
            "type": prop.type,
            "fieldType": prop.field_type,
            "groupName": prop.group_name,
            "description": prop.description,
        }
        if prop.has_unique_value:
            payload["hasUniqueValue"] = True
        if prop.options:
            payload["options"] = prop.options

        try:
            self._post(f"crm/v3/properties/{object_type}", payload)
            logger.info("Created property %s on %s", prop.name, object_type)
            return
        except HubSpotAPIError as e:
            if e.status_code != 409:
                raise

        # Property already exists. PATCH to sync options / label / description.
        # HubSpot's PATCH endpoint accepts the same body shape minus 'name'
        # (name is in the URL) and 'type' (immutable). hasUniqueValue is
        # also not patchable -- HubSpot rejects attempts to flip it.
        update_payload = {
            k: v for k, v in payload.items() if k not in {"name", "type", "hasUniqueValue"}
        }
        # Option-list merge: HubSpot's PATCH replaces options wholesale,
        # which deletes any value BD added in the HubSpot UI that we
        # don't ship in code. Preserve BD-added values by unioning the
        # existing options with ours; on conflict (same value), our
        # label / description / displayOrder wins. WARN if BD has options
        # we don't ship so the operator can decide whether to retire them.
        if prop.options is not None:
            try:
                existing = self._get(
                    f"crm/v3/properties/{object_type}/{prop.name}"
                )
                existing_options = existing.get("options") or []
                ours_by_value = {o["value"]: o for o in prop.options}
                merged: list[dict[str, Any]] = list(prop.options)
                bd_added: list[str] = []
                for opt in existing_options:
                    val = opt.get("value")
                    if val and val not in ours_by_value:
                        merged.append(opt)
                        bd_added.append(str(val))
                if bd_added:
                    logger.warning(
                        "%s.%s: preserving %d BD-added option(s) not in code: %s",
                        object_type, prop.name, len(bd_added), bd_added[:10],
                    )
                update_payload["options"] = merged
            except HubSpotAPIError as e:
                # If we can't read existing options, fall back to
                # replacing -- accepts the BD-option-loss risk for the
                # rare case where the GET fails but the PATCH might
                # succeed. Emit at WARN so the operator sees it.
                logger.warning(
                    "Could not read existing options for %s on %s "
                    "(falling back to wholesale replace): %s",
                    prop.name, object_type, e,
                )
        try:
            self._patch(
                f"crm/v3/properties/{object_type}/{prop.name}",
                update_payload,
            )
            logger.info("Updated property %s on %s", prop.name, object_type)
        except HubSpotAPIError as e:
            # Some property fields are immutable post-creation (e.g.
            # fieldType for enumeration properties created without options
            # cannot later be changed). Log and continue rather than fail
            # the whole bootstrap.
            logger.warning(
                "Could not patch existing property %s on %s: %s",
                prop.name, object_type, e,
            )

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
        """Find the target pipeline by name and cache its stage IDs. Returns pipeline ID."""
        existing = self._get("crm/v3/pipelines/deals")
        for pipeline in existing.get("results", []):
            if pipeline.get("label") == PIPELINE_NAME:
                self._pipeline_id = pipeline["id"]
                self._cache_stage_ids(pipeline)
                logger.info(
                    "Using pipeline '%s' (ID: %s, %d stages)",
                    PIPELINE_NAME, self._pipeline_id, len(self._stage_label_to_id),
                )
                return self._pipeline_id

        raise HubSpotAPIError(
            f"Pipeline '{PIPELINE_NAME}' not found in HubSpot. "
            f"Create it manually or update PIPELINE_NAME in hubspot/properties.py."
        )

    def _cache_stage_ids(self, pipeline_data: dict) -> None:
        """Cache the mapping from stage labels to internal IDs."""
        self._stage_label_to_id.clear()
        for stage in pipeline_data.get("stages", []):
            self._stage_label_to_id[stage["label"]] = stage["id"]

    def get_stage_id_by_label(self, label: str) -> str | None:
        """Return the HubSpot pipeline stage ID for an exact stage label.

        Falls back to None when the label does not exist in the configured
        pipeline. Used by the v2 ACE flow to translate AWS review-status
        labels (e.g. "Approved by AWS") to the HubSpot internal stage id
        we write to ``dealstage``.
        """
        if not self._stage_label_to_id:
            self.ensure_pipeline()
        return self._stage_label_to_id.get(label)

    def get_stage_id(self, govwin_status: str) -> str | None:
        """Map a GovWin status to a HubSpot pipeline stage ID.

        Unmapped statuses fall back to ``DEFAULT_STAGE_LABEL`` so the deal still
        lands in a stage. A warning is logged so the unmapped value can be
        added to ``GOVWIN_STATUS_TO_STAGE``.
        """
        if govwin_status in GOVWIN_STATUS_TO_STAGE:
            stage_label = GOVWIN_STATUS_TO_STAGE[govwin_status]
        else:
            logger.warning(
                "Unmapped GovWin status %r — falling back to %r. "
                "Add it to GOVWIN_STATUS_TO_STAGE in src/hubspot/properties.py.",
                govwin_status, DEFAULT_STAGE_LABEL,
            )
            stage_label = DEFAULT_STAGE_LABEL
        return self._stage_label_to_id.get(stage_label)

    # -----------------------------------------------------------------------
    # Deals
    # -----------------------------------------------------------------------

    def batch_upsert_deals(self, deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch upsert deals using govwin_id as the dedup key."""
        results: list[dict[str, Any]] = []

        for i in range(0, len(deals), self._config.hubspot.max_batch_size):
            batch = deals[i : i + self._config.hubspot.max_batch_size]
            inputs = [
                {
                    "idProperty": "govwin_id",
                    "id": deal["properties"]["govwin_id"],
                    "properties": deal["properties"],
                }
                for deal in batch
                if deal.get("properties", {}).get("govwin_id")
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

    def get_deal(
        self, deal_id: str, properties: list[str] | None = None
    ) -> dict[str, Any]:
        """Fetch a single deal by HubSpot object id with the requested properties."""
        params: dict[str, Any] = {}
        if properties:
            params["properties"] = ",".join(properties)
        return self._get(f"crm/v3/objects/deals/{deal_id}", params=params)

    def is_deal_archived(self, deal_id: str) -> bool:
        """Return True if the deal exists in HubSpot's archive but not in the
        active set. HubSpot's CRM v3 API surfaces archived records under a
        separate ``archived=true`` query; the active fetch returns 404 for an
        archived id. This is the cheapest way to disambiguate "archived" from
        "never existed" without falling back to the search API.
        """
        try:
            self._get(
                f"crm/v3/objects/deals/{deal_id}",
                params={"archived": "false"},
            )
            return False  # found in active set; not archived
        except HubSpotAPIError as exc:
            if exc.status_code != 404:
                raise
        # Active fetch returned 404. Check the archive.
        try:
            self._get(
                f"crm/v3/objects/deals/{deal_id}",
                params={"archived": "true"},
            )
            return True
        except HubSpotAPIError as exc:
            if exc.status_code == 404:
                return False  # never existed
            raise

    def update_deal(self, deal_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        """Patch a single deal's properties."""
        return self._patch(
            f"crm/v3/objects/deals/{deal_id}",
            {"properties": properties},
        )

    def get_associated_company(
        self, deal_id: str, properties: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Return the deal's primary associated HubSpot Company, or None.

        Used by the ACE mapper to populate Customer.Account.* from real
        company data instead of the constants previously hardcoded.
        HubSpot deals can have multiple company associations; we
        return the first one found.
        """
        try:
            assoc = self._get(
                f"crm/v3/objects/deals/{deal_id}/associations/companies"
            )
        except HubSpotAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        results = assoc.get("results") or []
        if not results:
            return None
        company_id = str(results[0].get("id") or "")
        if not company_id:
            return None
        params: dict[str, Any] = {}
        if properties:
            params["properties"] = ",".join(properties)
        return self._get(f"crm/v3/objects/companies/{company_id}", params=params)

    def get_associated_contacts(
        self, deal_id: str, properties: list[str] | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` HubSpot Contacts associated with the deal.

        AWS Partner Central's ``Customer.Contacts`` accepts up to 10 entries
        per opportunity; we cap at the same number even though HubSpot may
        return more associations.
        """
        try:
            assoc = self._get(
                f"crm/v3/objects/deals/{deal_id}/associations/contacts"
            )
        except HubSpotAPIError as exc:
            if exc.status_code == 404:
                return []
            raise
        ids = [
            str(a.get("id"))
            for a in (assoc.get("results") or [])
            if a.get("id")
        ][:limit]
        contacts: list[dict[str, Any]] = []
        params: dict[str, Any] = {}
        if properties:
            params["properties"] = ",".join(properties)
        for cid in ids:
            try:
                contacts.append(
                    self._get(f"crm/v3/objects/contacts/{cid}", params=params)
                )
            except HubSpotAPIError as exc:
                if exc.status_code == 404:
                    continue  # contact archived between association read and fetch
                raise
        return contacts

    def get_owner(self, owner_id: str) -> dict[str, Any] | None:
        """Return the HubSpot user record for a deal owner, or None.

        Used by the ACE mapper to populate OpportunityTeam[] / partner
        contact fields from the deal's HubSpot owner. ``owner_id`` is the
        numeric id stored on the deal's ``hubspot_owner_id`` property.
        """
        if not owner_id:
            return None
        try:
            return self._get(f"crm/v3/owners/{owner_id}")
        except HubSpotAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def find_contact_by_email(self, email: str) -> dict[str, Any] | None:
        """Return the existing HubSpot Contact for an email address, or None.

        Used by the Hyperscaler-Contact creation path to refuse to overwrite
        a real customer contact when AWS publishes an EngagementInvitation
        with a colliding email. Idempotent and read-only.
        """
        if not email or "@" not in email:
            return None
        try:
            return self._get(
                f"crm/v3/objects/contacts/{email}",
                params={"idProperty": "email", "properties": "email,hs_lead_status"},
            )
        except HubSpotAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

    def upsert_contact(
        self, properties: dict[str, Any], id_property: str = "email"
    ) -> dict[str, Any]:
        """Idempotent upsert of a single contact by ``id_property`` (default
        email). Used to create the AWS-side "Hyperscaler Contact" records
        when AWS publishes EngagementInvitation events.
        """
        return self._post(
            f"crm/v3/objects/contacts/upsert?idProperty={id_property}",
            {"properties": properties},
        )

    def associate_objects(
        self,
        from_object_type: str,
        from_id: str,
        to_object_type: str,
        to_id: str,
        association_type_id: int = 1,
    ) -> None:
        """Create a single typed association between two HubSpot objects.

        Default ``association_type_id`` 1 is the standard "associated to"
        type. Used by the AWS-side write-back path to associate Hyperscaler
        Contact records to the deal and the company.
        """
        path = (
            f"crm/v4/objects/{from_object_type}/{from_id}/associations/default/"
            f"{to_object_type}/{to_id}"
        )
        try:
            self._put(path, data={})
        except HubSpotAPIError as exc:
            if exc.status_code == 409:
                # association already exists; idempotent
                return
            raise

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
        """Batch upsert companies using govwin_entity_id as the dedup key."""
        results: list[dict[str, Any]] = []

        for i in range(0, len(companies), self._config.hubspot.max_batch_size):
            batch = companies[i : i + self._config.hubspot.max_batch_size]
            inputs = [
                {
                    "idProperty": "govwin_entity_id",
                    "id": co["properties"]["govwin_entity_id"],
                    "properties": co["properties"],
                }
                for co in batch
                if co.get("properties", {}).get("govwin_entity_id")
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
        """Run one-time setup: create properties/groups and verify pipeline exists."""
        self.ensure_all_properties()
        pipeline_id = self.ensure_pipeline()  # finds existing, does not create
        return {
            "pipeline_id": pipeline_id,
            "deal_properties": len(DEAL_PROPERTIES),
            "company_properties": len(COMPANY_PROPERTIES),
            "contact_properties": len(CONTACT_PROPERTIES),
        }

    # -----------------------------------------------------------------------
    # Webhook subscription management (developer-platform 2025.2+)
    # -----------------------------------------------------------------------

    def configure_webhook_settings(
        self,
        app_id: str,
        target_url: str,
        max_concurrent_requests: int = 10,
    ) -> dict[str, Any]:
        """Set the webhook delivery URL and throttling for a private app."""
        return self._post(
            f"webhooks/v3/{app_id}/settings",
            {
                "targetUrl": target_url,
                "throttling": {
                    "period": "SECONDLY",
                    "maxConcurrentRequests": max_concurrent_requests,
                },
            },
        )

    def create_webhook_subscription(
        self,
        app_id: str,
        subscription_details: dict[str, Any],
        active: bool = True,
    ) -> dict[str, Any]:
        """Register a webhook subscription on a private app."""
        return self._post(
            f"webhooks/v3/{app_id}/subscriptions",
            {"subscriptionDetails": subscription_details, "active": active},
        )
