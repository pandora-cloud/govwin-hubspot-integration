"""React to inbound EventBridge events from ``aws.partnercentral-selling``.

Per the AWS reference, event payloads carry only IDs in ``detail.opportunity``
and ``detail.engagementInvitation``. The handler resolves those to the local
HubSpot deal via ``PartnerOpportunityIdentifier`` (which our CreateOpportunity
populated with the GovWin opp ID) and updates the deal stage accordingly.

Idempotency: each event id is recorded atomically via
``mark_event_seen_atomic`` on first sighting; concurrent retries see the
existing record and return early.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.ace.client import ACEAPIError, ACEClient
from src.config import load_config
from src.hubspot.client import HubSpotClient
from src.sync.state import SyncStateManager

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# AWS review status -> HubSpot stage label. Keys MUST match the exact
# casing of the boto3 enum values for LifeCycle.ReviewStatus:
# ['Pending Submission', 'Submitted', 'In review', 'Approved', 'Rejected',
# 'Action Required']. Note 'In review' uses a lowercase 'r'.
#
# Label values are resolved at runtime via get_stage_id_by_label so
# deployments can rename pipeline stages without touching code; only the
# labels listed here need to exist in the configured pipeline. Statuses
# not in the map are intentionally ignored (e.g. 'Pending Submission'
# fires on every CreateOpportunity but doesn't move the deal stage).
_DEALSTAGE_BY_AWS_REVIEW: dict[str, str] = {
    "Submitted": "Submitted to AWS",
    "In review": "Under AWS Review",
    "Approved": "Approved by AWS",
    "Action Required": "Action Required",
    "Rejected": "Closed Lost",
    "Expired": "Closed Lost",
}


def _update_hubspot_stage(
    hubspot: HubSpotClient, deal_id: str, target_label: str
) -> tuple[bool, str | None]:
    """Resolve a stage label to its pipeline ID and patch the deal.

    Returns ``(success, reason)``. ``success`` is True when the deal was
    patched, False when the call was a deliberate no-op (stage label not in
    the configured pipeline, or deal is archived in HubSpot). Archived deals
    are an expected end-state -- BD has dispositioned the opp in HubSpot --
    and must not fire SNS alerts.
    """
    stage_id = hubspot.get_stage_id_by_label(target_label)
    if not stage_id:
        logger.warning(
            "handle_ace_event: stage label %r not in pipeline; skipping update of %s",
            target_label,
            deal_id,
        )
        return False, "stage label not in pipeline"
    # Cheap pre-flight: avoid update_deal on an archived deal so a stale
    # AWS-side EventBridge event doesn't surface as a 404 / SNS alert.
    if hubspot.is_deal_archived(deal_id):
        logger.info(
            "handle_ace_event: deal %s is archived in HubSpot; skipping stage update",
            deal_id,
        )
        return False, "deal archived in HubSpot"
    hubspot.update_deal(deal_id, {"dealstage": stage_id})
    return True, None


def _handle_opportunity_event(
    detail: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    """Opportunity Created / Updated.

    Detail carries only ``opportunity.identifier`` (the AWS Id). We must
    GetOpportunity to recover ``PartnerOpportunityIdentifier`` (our GovWin
    id) and the current ``LifeCycle.ReviewStatus``.
    """
    opp = detail.get("opportunity") or {}
    aws_id = opp.get("identifier")
    if not aws_id:
        return {"status": "skipped", "reason": "no opportunity.identifier"}
    try:
        full = ace.get_opportunity(str(aws_id))
    except ACEAPIError as exc:
        logger.warning("get_opportunity %s failed: %s", aws_id, exc)
        return {"status": "skipped", "reason": f"get_opportunity {exc.code}"}

    partner_id = full.get("PartnerOpportunityIdentifier")
    if not partner_id:
        return {"status": "skipped", "reason": "no PartnerOpportunityIdentifier on opportunity"}
    mapping = state.get_ace_mapping(str(partner_id)) or {}
    deal_id = mapping.get("hubspot_deal_id")
    if not deal_id:
        return {"status": "skipped", "reason": "no hubspot deal mapping"}

    review_status = str((full.get("LifeCycle") or {}).get("ReviewStatus") or "")

    # Write-back to HubSpot deal properties so BD sees AWS-side state
    # without leaving HubSpot. SaaSify parity: aws_cosell_id, aws_cosell_status,
    # aws_marketplace_engagement_score. Always attempted (even when the
    # ReviewStatus doesn't drive a dealstage change), but defensive against
    # archived deals so it doesn't 404 alarm the on-call.
    try:
        if not hubspot.is_deal_archived(str(deal_id)):
            engagement_score = (
                full.get("AwsOpportunitySummary") or {}
            ).get("MarketplaceEngagementScore")
            writeback: dict[str, Any] = {
                "govwin_aws_cosell_id": str(full.get("Id") or ""),
                "govwin_aws_cosell_status": review_status,
            }
            if engagement_score is not None:
                writeback["govwin_aws_marketplace_engagement_score"] = str(
                    engagement_score
                )
            hubspot.update_deal(str(deal_id), writeback)
    except Exception:  # noqa: BLE001 -- write-back is best-effort
        logger.exception(
            "handle_ace_event: AWS write-back failed for deal %s", deal_id
        )

    target_stage = _DEALSTAGE_BY_AWS_REVIEW.get(review_status)
    if not target_stage:
        # "Pending Submission" fires on every CreateOpportunity (and on the
        # implicit Opportunity Created event AWS emits). It is intentionally
        # not mapped because we don't want every create to thrash the
        # HubSpot dealstage. Distinguish that expected case in the log so
        # an operator scanning CloudWatch doesn't read it as a failure.
        if review_status == "Pending Submission":
            return {
                "status": "no-op",
                "reason": "Pending Submission is informational; no HubSpot stage change",
            }
        return {
            "status": "skipped",
            "reason": f"no HubSpot stage label maps to ReviewStatus={review_status!r}",
        }
    success, reason = _update_hubspot_stage(hubspot, str(deal_id), target_stage)
    if not success:
        return {"status": "skipped", "reason": reason or "stage update no-op"}

    last_modified = full.get("LastModifiedDate")
    state.update_ace_mapping(
        govwin_id=str(partner_id),
        last_modified_date=str(last_modified) if last_modified else None,
    )
    return {"status": "updated", "deal_id": deal_id, "stage": target_stage}


def _create_hyperscaler_contacts(
    *,
    invitation: dict[str, Any],
    deal_id: str,
    company_id: str | None,
    hubspot: HubSpotClient,
) -> int:
    """Create / upsert HubSpot Contact records for AWS-side participants.

    SaaSify parity: when AWS publishes EngagementInvitation events, the
    invitation detail can include AWS reviewer / PDM contacts. We mirror
    them as HubSpot Contacts labeled "Hyperscaler Contact" and associate
    each one to the deal and (when known) the company. Best-effort:
    contact creation failures are logged but never block stage updates.
    """
    aws_contacts = invitation.get("invitationContacts") or invitation.get("contacts") or []
    created = 0
    for c in aws_contacts:
        email = (c.get("email") or "").strip()
        first = (c.get("firstName") or c.get("first_name") or "").strip()
        last = (c.get("lastName") or c.get("last_name") or "").strip()
        if not email:
            continue
        try:
            response = hubspot.upsert_contact({
                "email": email,
                "firstname": first,
                "lastname": last,
                "company": "AWS",
                "jobtitle": c.get("businessTitle") or "AWS Partner Development Manager",
                "lifecyclestage": "other",
                "hs_lead_status": "HYPERSCALER_CONTACT",
            })
            contact_id = str(response.get("id") or "")
            if contact_id:
                hubspot.associate_objects("contacts", contact_id, "deals", deal_id)
                if company_id:
                    hubspot.associate_objects(
                        "contacts", contact_id, "companies", company_id
                    )
                created += 1
        except Exception:  # noqa: BLE001 -- best-effort
            logger.exception("hyperscaler contact upsert failed for %r", email)
    return created


def _handle_invitation_event(
    detail_type: str,
    detail: dict[str, Any],
    *,
    state: SyncStateManager,
    ace: ACEClient,
    hubspot: HubSpotClient,
) -> dict[str, Any]:
    invitation = detail.get("engagementInvitation") or {}
    invitation_id = invitation.get("id")
    if not invitation_id:
        return {"status": "skipped", "reason": "no engagementInvitation.id"}

    if detail_type == "Engagement Invitation Created":
        # Receiver-side referrals from AWS: we don't auto-create the deal in
        # v1 (BD approval in HubSpot is required first). Notify via log; the
        # Phase 4 referral handler will pick this up.
        if invitation.get("participantType") == "Receiver":
            logger.info(
                "ace.invitation.created.receiver invitation_id=%s engagementId=%s",
                invitation_id,
                invitation.get("engagementId"),
            )
        # Sender-side: AWS may include the reviewer's contact info. Create
        # Hyperscaler Contact records for visibility.
        try:
            partner_id = state.find_govwin_by_invitation_id(str(invitation_id))
            mapping = state.get_ace_mapping(partner_id) if partner_id else None
            deal_id = (mapping or {}).get("hubspot_deal_id")
            if deal_id:
                company = hubspot.get_associated_company(str(deal_id))
                company_id = str(company.get("id")) if company else None
                _create_hyperscaler_contacts(
                    invitation=invitation,
                    deal_id=str(deal_id),
                    company_id=company_id,
                    hubspot=hubspot,
                )
        except Exception:  # noqa: BLE001 -- best-effort
            logger.exception("hyperscaler contact creation failed")
        return {"status": "logged", "invitation_id": invitation_id}

    if detail_type == "Engagement Invitation Accepted":
        target_stage = "Approved by AWS"
    elif detail_type in {"Engagement Invitation Rejected", "Engagement Invitation Expired"}:
        target_stage = "Closed Lost"
    else:
        return {"status": "skipped", "reason": f"unhandled detail-type {detail_type}"}

    # Resolve invitation_id -> partner_id by scanning recent ACE mappings via
    # the engagement_invitation_id we persisted at submit time. v1 does this
    # via a get_opportunity round-trip from any associated opportunity.
    try:
        # AWS does not return the opportunity from the invitation event, so
        # we query our own DynamoDB by the invitation id we stored.
        partner_id = state.find_govwin_by_invitation_id(str(invitation_id))
    except Exception:  # noqa: BLE001 -- defensive, lookup is best-effort
        logger.exception("invitation lookup failed for %s", invitation_id)
        partner_id = None
    if not partner_id:
        return {"status": "skipped", "reason": "no mapping for invitation"}
    mapping = state.get_ace_mapping(partner_id) or {}
    deal_id = mapping.get("hubspot_deal_id")
    if not deal_id:
        return {"status": "skipped", "reason": "no hubspot deal mapping"}
    success, reason = _update_hubspot_stage(hubspot, str(deal_id), target_stage)
    if not success:
        return {"status": "skipped", "reason": reason or "stage update no-op"}
    return {"status": "updated", "deal_id": deal_id, "stage": target_stage}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    config = load_config()
    state = SyncStateManager(config)
    event_id = str(event.get("id") or "")
    detail_type = str(event.get("detail-type") or "")
    logger.info(
        "handle_ace_event.received id=%s detail-type=%s source=%s",
        event_id,
        detail_type,
        event.get("source"),
    )
    if event_id and not state.mark_event_seen_atomic(
        event_id, ttl_seconds=config.ace.event_dedup_ttl_seconds
    ):
        logger.info("handle_ace_event: dedup hit for %s", event_id)
        return {"status": "duplicate", "event_id": event_id}

    detail = event.get("detail") or {}
    ace = ACEClient(config)

    with HubSpotClient(config) as hubspot:
        if detail_type in {"Opportunity Created", "Opportunity Updated"}:
            result = _handle_opportunity_event(
                detail, state=state, ace=ace, hubspot=hubspot
            )
        elif detail_type.startswith("Engagement Invitation"):
            result = _handle_invitation_event(
                detail_type, detail, state=state, ace=ace, hubspot=hubspot
            )
        else:
            result = {"status": "skipped", "reason": f"unhandled detail-type {detail_type}"}
    logger.info("handle_ace_event.result %s", result)
    return result
