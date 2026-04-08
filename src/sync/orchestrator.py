"""High-level sync coordination logic used by Lambda handlers."""

from __future__ import annotations

import logging
from typing import Any

from src.config import AppConfig
from src.govwin.client import GovWinClient
from src.hubspot.client import HubSpotAPIError, HubSpotClient
from src.models import GovWinOpportunityBundle
from src.sync.mapper import (
    map_contact_to_hubspot,
    map_gov_entity_to_company,
    map_opportunity_to_deal,
)
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)


class SyncOrchestrator:
    """Coordinates the sync of GovWin data to HubSpot."""

    def __init__(
        self,
        config: AppConfig,
        *,
        govwin_client: GovWinClient | None = None,
        hubspot_client: HubSpotClient,
        state_manager: SyncStateManager,
    ) -> None:
        self._config = config
        self._govwin = govwin_client
        self._hubspot = hubspot_client
        self._state = state_manager

    def sync_opportunity_batch(
        self,
        bundles: list[GovWinOpportunityBundle],
    ) -> dict[str, Any]:
        """Sync a batch of opportunity bundles to HubSpot.

        Returns sync statistics.
        """
        stats = {
            "deals_synced": 0,
            "companies_synced": 0,
            "contacts_synced": 0,
            "associations_created": 0,
            "errors": [],
        }

        # 1. Collect and upsert all unique companies (gov entities)
        company_payloads: dict[str, dict[str, Any]] = {}
        for bundle in bundles:
            entity = bundle.opportunity.gov_entity
            if entity and entity.id:
                entity_id_str = str(entity.id)
                if entity_id_str not in company_payloads:
                    company_payloads[entity_id_str] = map_gov_entity_to_company(entity)

        company_results: list[dict[str, Any]] = []
        if company_payloads:
            try:
                company_results = self._hubspot.batch_upsert_companies(
                    list(company_payloads.values())
                )
                stats["companies_synced"] = len(company_results)

                # Store company mappings
                mappings = []
                for result in company_results:
                    hs_id = result.get("id")
                    gw_id = result.get("properties", {}).get("govwin_entity_id")
                    if hs_id and gw_id:
                        mappings.append(("GOVENTITY", gw_id, hs_id))
                if mappings:
                    self._state.batch_set_entity_mappings(mappings)
            except HubSpotAPIError as e:
                stats["errors"].append(f"Company upsert failed: {e}")
                logger.exception("Failed to upsert companies")

        # 2. Collect and upsert all unique contacts
        contact_payloads: list[dict[str, Any]] = []
        seen_contacts: set[str] = set()
        for bundle in bundles:
            for contact in bundle.contacts:
                key = contact.email or contact.contact_id or ""
                if key and key not in seen_contacts:
                    seen_contacts.add(key)
                    contact_payloads.append(map_contact_to_hubspot(contact))

        contact_results: list[dict[str, Any]] = []
        if contact_payloads:
            try:
                contact_results = self._hubspot.batch_upsert_contacts(contact_payloads)
                stats["contacts_synced"] = len(contact_results)

                # Store contact mappings
                mappings = []
                for result in contact_results:
                    hs_id = result.get("id")
                    gw_id = result.get("properties", {}).get("govwin_contact_id")
                    if hs_id and gw_id:
                        mappings.append(("CONTACT", gw_id, hs_id))
                if mappings:
                    self._state.batch_set_entity_mappings(mappings)
            except HubSpotAPIError as e:
                stats["errors"].append(f"Contact upsert failed: {e}")
                logger.exception("Failed to upsert contacts")

        # 3. Upsert deals
        deal_payloads: list[dict[str, Any]] = []
        for bundle in bundles:
            stage_id = None
            if bundle.opportunity.status:
                stage_id = self._hubspot.get_stage_id(bundle.opportunity.status)

            deal_payload = map_opportunity_to_deal(
                bundle,
                pipeline_id=self._hubspot.pipeline_id,
                stage_id=stage_id,
            )
            deal_payloads.append(deal_payload)

        deal_results: list[dict[str, Any]] = []
        if deal_payloads:
            try:
                deal_results = self._hubspot.batch_upsert_deals(deal_payloads)
                stats["deals_synced"] = len(deal_results)
            except HubSpotAPIError as e:
                stats["errors"].append(f"Deal upsert failed: {e}")
                logger.exception("Failed to upsert deals")

        # Detect skipped deals via set-difference (batch API doesn't guarantee order)
        if len(deal_results) < len(bundles):
            returned_ids = {
                r.get("properties", {}).get("govwin_id")
                for r in deal_results
            }
            submitted_ids = {
                b.opportunity.id for b in bundles if b.opportunity.id
            }
            skipped_ids = submitted_ids - returned_ids
            if skipped_ids:
                logger.warning(
                    "Deal upsert returned %d results for %d bundles, skipped: %s",
                    len(deal_results), len(bundles), skipped_ids,
                )
                for opp_id in skipped_ids:
                    stats["errors"].append(f"Deal upsert skipped: {opp_id}")

        # 4. Create associations (batched)
        deal_company_assocs: list[tuple[str, str]] = []
        deal_contact_assocs: list[tuple[str, str]] = []

        for bundle, deal_result in zip(bundles, deal_results, strict=False):
            deal_hs_id = deal_result.get("id")
            if not deal_hs_id:
                continue

            # Deal <-> Company
            entity = bundle.opportunity.gov_entity
            if entity and entity.id:
                company_hs_id = self._state.get_entity_hubspot_id(
                    "GOVENTITY", str(entity.id)
                )
                if company_hs_id:
                    deal_company_assocs.append((deal_hs_id, company_hs_id))

            # Deal <-> Contacts (look up by contact_id, matching how mappings are stored)
            for contact in bundle.contacts:
                key = str(contact.contact_id) if contact.contact_id else None
                if key:
                    contact_hs_id = self._state.get_entity_hubspot_id("CONTACT", key)
                    if contact_hs_id:
                        deal_contact_assocs.append((deal_hs_id, contact_hs_id))

        if deal_company_assocs:
            self._hubspot.batch_create_associations(
                "deals", "companies", deal_company_assocs
            )
        if deal_contact_assocs:
            self._hubspot.batch_create_associations(
                "deals", "contacts", deal_contact_assocs
            )

        stats["associations_created"] = len(deal_company_assocs) + len(deal_contact_assocs)

        # 5. Update per-opportunity sync state
        for bundle, deal_result in zip(bundles, deal_results, strict=False):
            opp = bundle.opportunity
            if opp.id and opp.update_date:
                self._state.set_opp_state(
                    govwin_opp_id=opp.id,
                    govwin_update_date=opp.update_date,
                    hubspot_deal_id=deal_result.get("id"),
                )

        return stats
