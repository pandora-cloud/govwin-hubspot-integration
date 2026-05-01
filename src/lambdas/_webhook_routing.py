"""Single source of truth for HubSpot webhook property routing.

Both the deploy-time webhook subscription registrar
(``setup_hubspot_webhooks.py``) and the request-time receiver Lambda
(``hubspot_webhook_receiver.py``) import these constants. Adding a new
property in one place without the other was a recurring drift source in
v2.0; this module pins the contract.
"""

from __future__ import annotations

# Property whose change should trigger initial ACE submission. Currently
# the Lambda only triggers when the change matches one of the configured
# stage internal IDs (see ACE_TRIGGER_STAGES env var), but we still
# subscribe to every dealstage change.
SUBMIT_TRIGGER_PROPERTY: str = "dealstage"

# Properties whose change should trigger an UpdateOpportunity call to AWS.
# These are content fields the BD team can edit after submission while
# the ACE opportunity is still mutable. Adding a property here without
# also handling it in update_in_ace._apply_delta is a no-op; the receiver
# enqueues but the worker doesn't know what to do with it. Keep both in
# sync.
UPDATE_TRIGGER_PROPERTIES: frozenset[str] = frozenset(
    {
        "amount",
        "closedate",
        "dealname",
        "description",
        "govwin_ace_use_case",
        # Extended BD-editable properties; each is a property that
        # update_in_ace._apply_delta forwards to AWS UpdateOpportunity.
        "govwin_ace_competitor_name",
        "govwin_ace_additional_comments",
        "govwin_ace_aws_account_id",
        "govwin_ace_next_steps",
        "govwin_ace_related_opportunity_id",
        "govwin_ace_marketing_source",
        "govwin_ace_marketing_campaign_name",
        "govwin_ace_marketing_use_cases",
        "govwin_ace_marketing_channel",
        "govwin_ace_marketing_dev_funded",
    }
)

# All properties the HubSpot app subscribes to. Order doesn't matter,
# but the order here maps 1:1 to the order in webhooks-hsmeta.json.
ALL_SUBSCRIBED_PROPERTIES: tuple[str, ...] = (
    SUBMIT_TRIGGER_PROPERTY,
    *sorted(UPDATE_TRIGGER_PROPERTIES),
)


def classify_property_change(property_name: str | None) -> str:
    """Return "submit", "update", or "drop" for a property-change event."""
    if not property_name:
        return "drop"
    if property_name == SUBMIT_TRIGGER_PROPERTY:
        return "submit"
    if property_name in UPDATE_TRIGGER_PROPERTIES:
        return "update"
    return "drop"
