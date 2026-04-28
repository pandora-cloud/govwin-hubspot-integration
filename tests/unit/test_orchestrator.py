"""Tests for the SyncOrchestrator high-level coordination logic.

Exercises company/contact/deal upsert ordering, partial failure handling,
deduplication of shared entities across bundles, and the skipped-deal
detection that uses set-difference on govwin_id (not positional zip).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.hubspot.client import HubSpotAPIError, HubSpotClient
from src.models import (
    GovWinContact,
    GovWinOpportunity,
    GovWinOpportunityBundle,
)
from src.sync.orchestrator import SyncOrchestrator
from src.sync.state import SyncStateManager


def _bundle(opp_id: str, *, agency_id: int | None = 100, agency_name: str = "DoD",
            contacts: list[dict] | None = None) -> GovWinOpportunityBundle:
    opp = GovWinOpportunity.model_validate(
        {
            "id": opp_id,
            "title": f"Opp {opp_id}",
            "status": "Pre-RFP",
            "updateDate": "2026-04-01T00:00:00Z",
            "govEntity": {"id": agency_id, "title": agency_name} if agency_id else None,
        }
    )
    contact_models = [GovWinContact.model_validate(c) for c in (contacts or [])]
    return GovWinOpportunityBundle(opportunity=opp, contacts=contact_models)


@pytest.fixture
def state_manager(app_config, mock_aws_env) -> SyncStateManager:
    return SyncStateManager(app_config)


@pytest.fixture
def hubspot_mock_client() -> MagicMock:
    client = MagicMock(spec=HubSpotClient)
    client.pipeline_id = "pipe-001"
    client.get_stage_id.return_value = "stage-opid"
    client.batch_upsert_companies.return_value = []
    client.batch_upsert_contacts.return_value = []
    client.batch_upsert_deals.return_value = []
    client.batch_create_associations.return_value = None
    return client


def test_dedupes_shared_company_across_bundles(app_config, hubspot_mock_client, state_manager):
    """Three bundles for the same agency must produce a single company upsert call."""
    bundles = [_bundle("OPP1"), _bundle("OPP2"), _bundle("OPP3")]
    hubspot_mock_client.batch_upsert_companies.return_value = [
        {"id": "hs-co-1", "properties": {"govwin_entity_id": "100"}}
    ]
    hubspot_mock_client.batch_upsert_deals.return_value = [
        {"id": f"hs-deal-{i}", "properties": {"govwin_id": b.opportunity.id}}
        for i, b in enumerate(bundles)
    ]

    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )
    stats = orch.sync_opportunity_batch(bundles)

    assert stats["companies_synced"] == 1
    assert stats["deals_synced"] == 3
    payload = hubspot_mock_client.batch_upsert_companies.call_args[0][0]
    assert len(payload) == 1


def test_company_upsert_failure_does_not_block_deal_sync(
    app_config, hubspot_mock_client, state_manager
):
    """A HubSpotAPIError on company upsert must be captured in stats but allow deals to proceed."""
    bundles = [_bundle("OPP1")]
    hubspot_mock_client.batch_upsert_companies.side_effect = HubSpotAPIError("boom", 500)
    hubspot_mock_client.batch_upsert_deals.return_value = [
        {"id": "hs-deal-1", "properties": {"govwin_id": "OPP1"}}
    ]

    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )
    stats = orch.sync_opportunity_batch(bundles)

    assert stats["companies_synced"] == 0
    assert stats["deals_synced"] == 1
    assert any("Company upsert failed" in e for e in stats["errors"])


def test_skipped_deals_detected_via_set_difference(
    app_config, hubspot_mock_client, state_manager
):
    """When the batch API returns fewer results than submitted, missing govwin_ids are reported."""
    bundles = [_bundle("OPP1"), _bundle("OPP2"), _bundle("OPP3")]
    hubspot_mock_client.batch_upsert_companies.return_value = [
        {"id": "hs-co-1", "properties": {"govwin_entity_id": "100"}}
    ]
    # HubSpot returns OPP1 and OPP3 but not OPP2 (and not in input order)
    hubspot_mock_client.batch_upsert_deals.return_value = [
        {"id": "hs-deal-3", "properties": {"govwin_id": "OPP3"}},
        {"id": "hs-deal-1", "properties": {"govwin_id": "OPP1"}},
    ]

    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )
    stats = orch.sync_opportunity_batch(bundles)

    skipped_msgs = [e for e in stats["errors"] if "skipped" in e]
    assert len(skipped_msgs) == 1
    assert "OPP2" in skipped_msgs[0]


def test_contact_lookup_uses_contact_id_not_email(
    app_config, hubspot_mock_client, state_manager
):
    """Associations must look up contacts by contact_id (the key DynamoDB mappings use)."""
    bundles = [
        _bundle(
            "OPP1",
            contacts=[
                {"contactId": "C-42", "email": "jane@dod.gov", "firstName": "Jane"}
            ],
        )
    ]
    hubspot_mock_client.batch_upsert_companies.return_value = []
    hubspot_mock_client.batch_upsert_contacts.return_value = [
        {"id": "hs-contact-1", "properties": {"govwin_contact_id": "C-42"}}
    ]
    hubspot_mock_client.batch_upsert_deals.return_value = [
        {"id": "hs-deal-1", "properties": {"govwin_id": "OPP1"}}
    ]

    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )
    stats = orch.sync_opportunity_batch(bundles)

    assert stats["associations_created"] >= 1
    # Find the deals→contacts association call
    assoc_calls = [
        c for c in hubspot_mock_client.batch_create_associations.call_args_list
        if c.args[1] == "contacts"
    ]
    assert assoc_calls, "Expected at least one deals→contacts association call"
    pairs = assoc_calls[0].args[2]
    assert ("hs-deal-1", "hs-contact-1") in pairs


def test_handles_bundle_with_no_agency(app_config, hubspot_mock_client, state_manager):
    """A bundle whose opportunity has no govEntity must not crash company collection."""
    bundles = [_bundle("OPP1", agency_id=None)]
    hubspot_mock_client.batch_upsert_deals.return_value = [
        {"id": "hs-deal-1", "properties": {"govwin_id": "OPP1"}}
    ]

    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )
    stats = orch.sync_opportunity_batch(bundles)

    assert stats["companies_synced"] == 0
    assert stats["deals_synced"] == 1
    hubspot_mock_client.batch_upsert_companies.assert_not_called()


def test_resync_same_opp_uses_same_govwin_id(
    app_config, hubspot_mock_client, state_manager
):
    """An opp with a changed updateDate is upserted via the same govwin_id key both times.

    HubSpot's ``govwin_id`` property is ``hasUniqueValue=true``; the deal upsert always
    keys on it, which is what makes re-syncing the same opp idempotent (it updates the
    existing deal instead of creating a duplicate). This test pins that behavior.
    """
    bundle_v1 = _bundle("OPP-RESYNC")
    bundle_v1.opportunity.update_date = "2026-04-01T00:00:00Z"
    bundle_v2 = _bundle("OPP-RESYNC")
    bundle_v2.opportunity.update_date = "2026-04-15T00:00:00Z"
    bundle_v2.opportunity.status = "RFP Released"  # field changed in GovWin

    hubspot_mock_client.batch_upsert_companies.return_value = [
        {"id": "hs-co-1", "properties": {"govwin_entity_id": "100"}}
    ]
    hubspot_mock_client.batch_upsert_deals.return_value = [
        {"id": "hs-deal-RESYNC", "properties": {"govwin_id": "OPP-RESYNC"}}
    ]

    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )

    # First sync — creates the deal
    orch.sync_opportunity_batch([bundle_v1])
    first_payload = hubspot_mock_client.batch_upsert_deals.call_args[0][0]
    assert first_payload[0]["properties"]["govwin_id"] == "OPP-RESYNC"

    # Verify state captured the HubSpot deal id from the first run
    assert state_manager.get_opp_hubspot_id("OPP-RESYNC") == "hs-deal-RESYNC"
    assert state_manager.get_opp_update_date("OPP-RESYNC") == "2026-04-01T00:00:00Z"

    # Second sync — same govwin_id, new updateDate
    orch.sync_opportunity_batch([bundle_v2])
    second_payload = hubspot_mock_client.batch_upsert_deals.call_args[0][0]
    assert second_payload[0]["properties"]["govwin_id"] == "OPP-RESYNC"
    assert second_payload[0]["properties"]["govwin_status"] == "RFP Released"

    # State cursor moved forward and HubSpot deal id is unchanged
    assert state_manager.get_opp_hubspot_id("OPP-RESYNC") == "hs-deal-RESYNC"
    assert state_manager.get_opp_update_date("OPP-RESYNC") == "2026-04-15T00:00:00Z"


def test_empty_bundle_list_returns_zero_stats(app_config, hubspot_mock_client, state_manager):
    """An empty input should never call HubSpot and should return zero stats."""
    orch = SyncOrchestrator(
        app_config,
        hubspot_client=hubspot_mock_client,
        state_manager=state_manager,
    )
    stats = orch.sync_opportunity_batch([])

    assert stats == {
        "deals_synced": 0,
        "companies_synced": 0,
        "contacts_synced": 0,
        "associations_created": 0,
        "errors": [],
    }
    hubspot_mock_client.batch_upsert_companies.assert_not_called()
    hubspot_mock_client.batch_upsert_deals.assert_not_called()
    hubspot_mock_client.batch_upsert_contacts.assert_not_called()
