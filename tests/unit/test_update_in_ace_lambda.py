"""Tests for the update_in_ace SQS-driven Lambda.

Covers the fetch-modify-send PUT-semantic flow against AWS UpdateOpportunity:

* per-property delta application
* description short-input padding
* description re-fetch from HubSpot (webhook propertyValue may be truncated)
* objectId validation
* missing-mapping skips
* ConflictException retry path
* permanent vs transient error classification
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ace.client import ACEAPIError, ACEClient
from src.lambdas import update_in_ace


@pytest.fixture(autouse=True)
def _ace_env(monkeypatch):
    monkeypatch.setenv("ACE_CATALOG", "Sandbox")
    monkeypatch.setenv("ACE_DEFAULT_SOLUTION_ID", "S-1234567")


def _record(prop: str, value: object, deal_id: str = "320194741966") -> dict:
    """Build an SQS Records[0] entry for a HubSpot property-change webhook."""
    body = {
        "objectId": int(deal_id),
        "subscriptionType": "object.propertyChange",
        "propertyName": prop,
        "propertyValue": value,
    }
    return {"messageId": "msg-1", "body": json.dumps(body)}


def _event(*records: dict) -> dict:
    return {"Records": list(records)}


def _full_get_opp_response() -> dict:
    """A realistic GetOpportunity response that includes every field
    scrub_for_update keeps."""
    return {
        "Id": "O-EXISTING",
        "Catalog": "Sandbox",
        "PartnerOpportunityIdentifier": "OPP1234",
        "LastModifiedDate": "2026-04-30T17:09:00Z",
        "PrimaryNeedsFromAws": ["Co-Sell - Technical Consultation"],
        "OpportunityType": "Net New Business",
        "Customer": {
            "Account": {
                "CompanyName": "Test Customer",
                "Industry": "Government",
                "WebsiteUrl": "https://www.usa.gov",
                "Address": {
                    "CountryCode": "US",
                    "PostalCode": "20001",
                    "StateOrRegion": "Dist. of Columbia",
                },
            }
        },
        "Project": {
            "Title": "Existing Title",
            "DeliveryModels": ["Professional Services"],
            "CustomerUseCase": "Migration / Database Migration",
            "CustomerBusinessProblem": (
                "An existing description that is well over twenty chars long."
            ),
            "ExpectedCustomerSpend": [
                {
                    "Amount": "100000.00",
                    "CurrencyCode": "USD",
                    "Frequency": "Monthly",
                    "TargetCompany": "Partner Company",
                }
            ],
        },
        "LifeCycle": {
            "ReviewStatus": "Pending Submission",
            "TargetCloseDate": "2026-12-31",
        },
    }


def _patches(deal_payload: dict | None = None):
    ace = MagicMock()
    ace.get_opportunity.return_value = _full_get_opp_response()
    ace.update_with_retry.return_value = {"LastModifiedDate": "2026-05-01T00:00:00Z"}

    state = MagicMock()
    state.find_govwin_by_hubspot_deal_id.return_value = "OPP1234"
    state.get_ace_mapping.return_value = {
        "ace_opportunity_id": "O-EXISTING",
        "hubspot_deal_id": "320194741966",
        "last_modified_date": "2026-04-30T17:09:00Z",
    }

    hubspot = MagicMock()
    hubspot.__enter__.return_value = hubspot
    hubspot.__exit__.return_value = False
    hubspot.get_deal.return_value = deal_payload or {"id": "320194741966", "properties": {}}
    return ace, state, hubspot


def _run(event: dict, ace, state, hubspot) -> dict:
    # Replace the ACEClient *class* but keep its static method
    # scrub_for_update pointing at the real implementation, since the
    # production handler relies on it returning a real dict.
    mock_ace_class = MagicMock(side_effect=lambda config: ace)
    mock_ace_class.scrub_for_update = staticmethod(ACEClient.scrub_for_update)
    with patch.object(update_in_ace, "ACEClient", mock_ace_class), \
         patch.object(update_in_ace, "SyncStateManager", return_value=state), \
         patch.object(update_in_ace, "HubSpotClient", return_value=hubspot):
        return update_in_ace.handler(event, context=None)


# ---------------------------------------------------------------------------
# Per-property happy-path coverage
# ---------------------------------------------------------------------------


class TestApplyDelta:
    def test_amount_writes_expected_customer_spend(self):
        ace, state, hubspot = _patches()
        result = _run(_event(_record("amount", "250000")), ace, state, hubspot)
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        spend = body["Project"]["ExpectedCustomerSpend"]
        # MRR convention: HubSpot annual amount / 12 -> AWS Frequency=Monthly
        # (matches the create-path mapper).
        assert spend[0]["Amount"] == "20833.33"
        assert spend[0]["CurrencyCode"] == "USD"
        assert spend[0]["Frequency"] == "Monthly"

    def test_amount_invalid_string_skips(self):
        ace, state, hubspot = _patches()
        result = _run(_event(_record("amount", "not-a-number")), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"
        ace.update_with_retry.assert_not_called()

    def test_closedate_truncated_to_yyyy_mm_dd(self):
        ace, state, hubspot = _patches()
        event = _event(_record("closedate", "2027-01-15T12:34:56Z"))
        result = _run(event, ace, state, hubspot)
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        assert body["LifeCycle"]["TargetCloseDate"] == "2027-01-15"

    def test_dealname_writes_project_title(self):
        ace, state, hubspot = _patches()
        hubspot.get_deal.return_value = {
            "id": "320194741966", "properties": {"dealname": "New Deal Title"}
        }
        result = _run(_event(_record("dealname", "Truncated...")), ace, state, hubspot)
        assert result["results"][0]["status"] == "updated"
        # The updated Title should come from the HubSpot fetch, not the
        # webhook propertyValue (since dealname is in _REFETCH_FROM_HUBSPOT_PROPERTIES).
        body = ace.update_with_retry.call_args.kwargs["updates"]
        assert body["Project"]["Title"] == "New Deal Title"

    def test_govwin_ace_use_case_writes_customer_use_case(self):
        ace, state, hubspot = _patches()
        event = _event(_record("govwin_ace_use_case", "Security & Compliance"))
        result = _run(event, ace, state, hubspot)
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        assert body["Project"]["CustomerUseCase"] == "Security & Compliance"

    def test_irrelevant_property_skips(self):
        ace, state, hubspot = _patches()
        result = _run(_event(_record("hs_lastmodifieddate", "2026-04-30")), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"
        ace.update_with_retry.assert_not_called()

    def test_empty_value_skips(self):
        ace, state, hubspot = _patches()
        result = _run(_event(_record("amount", "")), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"

    def test_marketing_source_marketing_activity_keeps_companions(self):
        """Source='Marketing Activity' is the only value that keeps
        companion fields. Audit-trail for AWS validation rules.
        """
        ace, state, hubspot = _patches()
        result = _run(
            _event(_record("govwin_ace_marketing_source", "Marketing Activity")),
            ace, state, hubspot,
        )
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        assert body["Marketing"]["Source"] == "Marketing Activity"

    def test_marketing_source_explicit_none_strips_companions(self):
        """When Source is 'None', AWS rejects companion fields. Strip them."""
        ace, state, hubspot = _patches()
        result = _run(
            _event(_record("govwin_ace_marketing_source", "None")),
            ace, state, hubspot,
        )
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        assert body["Marketing"] == {"Source": "None"}


# ---------------------------------------------------------------------------
# description: re-fetch + padding behaviors
# ---------------------------------------------------------------------------


class TestDescription:
    def test_description_refetched_from_hubspot(self):
        """Webhook propertyValue can be truncated for long fields; the
        Lambda should fetch the full value from HubSpot directly."""
        ace, state, hubspot = _patches()
        full_text = "A " * 100  # 200 chars, well above the 20-char minimum
        hubspot.get_deal.return_value = {
            "id": "320194741966", "properties": {"description": full_text}
        }
        result = _run(_event(_record("description", "TRUNCATED")), ace, state, hubspot)
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        cbp = body["Project"]["CustomerBusinessProblem"]
        assert cbp == full_text
        # Confirm we asked HubSpot for the description
        assert any(
            "description" in str(call) for call in hubspot.get_deal.call_args_list
        )

    def test_description_padded_with_title_when_short(self):
        """If both webhook and HubSpot return a short value, pad with the
        existing project title to satisfy the 20-char regex."""
        ace, state, hubspot = _patches()
        hubspot.get_deal.return_value = {
            "id": "320194741966", "properties": {"description": "tiny"}
        }
        result = _run(_event(_record("description", "tiny")), ace, state, hubspot)
        assert result["results"][0]["status"] == "updated"
        body = ace.update_with_retry.call_args.kwargs["updates"]
        cbp = body["Project"]["CustomerBusinessProblem"]
        # Padded with the existing title
        assert cbp.startswith("Existing Title")
        assert len(cbp) >= 20

    def test_description_skipped_when_unpaddable(self):
        """If neither webhook nor HubSpot returns enough text, and there's
        no Title to pad with, skip rather than write an invalid value."""
        ace, state, hubspot = _patches()
        ace.get_opportunity.return_value = {
            **_full_get_opp_response(),
            "Project": {**_full_get_opp_response()["Project"], "Title": ""},
        }
        hubspot.get_deal.return_value = {
            "id": "320194741966", "properties": {"description": "x"}
        }
        result = _run(_event(_record("description", "x")), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"
        ace.update_with_retry.assert_not_called()


# ---------------------------------------------------------------------------
# Validation + skip paths
# ---------------------------------------------------------------------------


class TestSkips:
    def test_invalid_object_id_skipped(self):
        ace, state, hubspot = _patches()
        bad = {
            "messageId": "msg-1",
            "body": json.dumps({
                "objectId": "../../../etc/passwd",
                "subscriptionType": "object.propertyChange",
                "propertyName": "amount",
                "propertyValue": "1000",
            }),
        }
        result = _run(_event(bad), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"
        # Make sure we never even looked anything up in DynamoDB
        state.find_govwin_by_hubspot_deal_id.assert_not_called()

    def test_no_govwin_mapping_skipped(self):
        ace, state, hubspot = _patches()
        state.find_govwin_by_hubspot_deal_id.return_value = None
        hubspot.get_deal.return_value = {"id": "320194741966", "properties": {}}
        result = _run(_event(_record("amount", "1000")), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"

    def test_no_ace_mapping_yet_skipped(self):
        ace, state, hubspot = _patches()
        state.get_ace_mapping.return_value = {}  # ace_opportunity_id missing
        result = _run(_event(_record("amount", "1000")), ace, state, hubspot)
        assert result["results"][0]["status"] == "skipped"
        ace.get_opportunity.assert_not_called()


# ---------------------------------------------------------------------------
# Error classification: permanent vs transient
# ---------------------------------------------------------------------------


class TestErrors:
    def test_permanent_validation_dropped(self):
        ace, state, hubspot = _patches()
        ace.update_with_retry.side_effect = ACEAPIError("bad", code="ValidationException")
        result = _run(_event(_record("amount", "1000")), ace, state, hubspot)
        assert result["batchItemFailures"] == []  # not retried

    def test_permanent_access_denied_dropped(self):
        ace, state, hubspot = _patches()
        ace.update_with_retry.side_effect = ACEAPIError("denied", code="AccessDeniedException")
        result = _run(_event(_record("amount", "1000")), ace, state, hubspot)
        assert result["batchItemFailures"] == []

    def test_transient_throttling_retried(self):
        ace, state, hubspot = _patches()
        ace.update_with_retry.side_effect = ACEAPIError("slow", code="ThrottlingException")
        result = _run(_event(_record("amount", "1000")), ace, state, hubspot)
        assert result["batchItemFailures"] == [{"itemIdentifier": "msg-1"}]

    def test_invalid_json_dropped(self):
        ace, state, hubspot = _patches()
        bad = {"messageId": "msg-bad", "body": "{not json"}
        result = _run(_event(bad), ace, state, hubspot)
        # Permanent error: do not retry via SQS
        assert result["batchItemFailures"] == []


# ---------------------------------------------------------------------------
# Scrub-for-update interaction (PUT semantics)
# ---------------------------------------------------------------------------


def test_scrub_preserves_partner_opportunity_identifier():
    """Without echoing PartnerOpportunityIdentifier, AWS PUT semantics
    would clear it on every update."""
    ace, state, hubspot = _patches()
    _run(_event(_record("amount", "1000")), ace, state, hubspot)
    body = ace.update_with_retry.call_args.kwargs["updates"]
    assert body.get("PartnerOpportunityIdentifier") == "OPP1234"


def test_scrub_preserves_lifecycle_target_close_date():
    """Updating amount should not clear an unrelated LifeCycle field."""
    ace, state, hubspot = _patches()
    _run(_event(_record("amount", "1000")), ace, state, hubspot)
    body = ace.update_with_retry.call_args.kwargs["updates"]
    assert body["LifeCycle"]["TargetCloseDate"] == "2026-12-31"
