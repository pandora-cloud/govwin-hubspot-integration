"""DynamoDB state management for sync cursors and entity mappings."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.config import AppConfig

logger = logging.getLogger(__name__)


def _as_str(value: Any) -> str | None:
    """Narrow a DynamoDB attribute (Any) to ``str | None`` for the type checker."""
    return value if isinstance(value, str) else None


class SyncStateManager:
    """Manages sync state in DynamoDB."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._dynamodb = boto3.resource("dynamodb", region_name=config.aws.region)
        self._state_table = self._dynamodb.Table(config.aws.sync_state_table)
        self._mappings_table = self._dynamodb.Table(config.aws.entity_mappings_table)

    # -----------------------------------------------------------------------
    # Sync Cursor
    # -----------------------------------------------------------------------

    def get_last_sync_timestamp(self) -> str | None:
        """Get the timestamp of the last successful sync."""
        try:
            response = self._state_table.get_item(
                Key={"pk": "SYNC_CURSOR", "sk": "METADATA"}
            )
            item = response.get("Item")
            return _as_str(item.get("last_sync_timestamp")) if item else None
        except ClientError:
            logger.warning("Failed to read sync cursor from DynamoDB")
            return None

    def set_last_sync_timestamp(self, timestamp: str | None = None) -> None:
        """Set the last successful sync timestamp."""
        if timestamp is None:
            timestamp = datetime.now(UTC).isoformat()

        self._state_table.put_item(
            Item={
                "pk": "SYNC_CURSOR",
                "sk": "METADATA",
                "last_sync_timestamp": timestamp,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

    # -----------------------------------------------------------------------
    # Per-Opportunity State
    # -----------------------------------------------------------------------

    def get_opp_update_date(self, govwin_opp_id: str) -> str | None:
        """Get the stored updateDate for an opportunity."""
        try:
            response = self._state_table.get_item(
                Key={"pk": f"OPP#{govwin_opp_id}", "sk": "METADATA"}
            )
            item = response.get("Item")
            return _as_str(item.get("govwin_update_date")) if item else None
        except ClientError:
            return None

    def set_opp_state(
        self,
        govwin_opp_id: str,
        govwin_update_date: str,
        hubspot_deal_id: str | None = None,
    ) -> None:
        """Store the sync state for an opportunity."""
        item: dict[str, Any] = {
            "pk": f"OPP#{govwin_opp_id}",
            "sk": "METADATA",
            "govwin_update_date": govwin_update_date,
            "last_synced": datetime.now(UTC).isoformat(),
            "ttl": int(time.time()) + 180 * 86400,
        }
        if hubspot_deal_id:
            item["hubspot_deal_id"] = hubspot_deal_id

        self._state_table.put_item(Item=item)

    def get_opp_hubspot_id(self, govwin_opp_id: str) -> str | None:
        """Get the HubSpot deal ID for a GovWin opportunity."""
        try:
            response = self._state_table.get_item(
                Key={"pk": f"OPP#{govwin_opp_id}", "sk": "METADATA"}
            )
            item = response.get("Item")
            return _as_str(item.get("hubspot_deal_id")) if item else None
        except ClientError:
            return None

    def batch_get_opp_update_dates(
        self, govwin_opp_ids: list[str]
    ) -> dict[str, str]:
        """Get stored updateDates for multiple opportunities at once."""
        result: dict[str, str] = {}

        # DynamoDB batch_get_item supports max 100 keys per request
        for i in range(0, len(govwin_opp_ids), 100):
            batch = govwin_opp_ids[i : i + 100]
            request_items: dict[str, Any] = {
                self._config.aws.sync_state_table: {
                    "Keys": [{"pk": f"OPP#{opp_id}", "sk": "METADATA"} for opp_id in batch]
                }
            }

            try:
                while request_items:
                    response = self._dynamodb.batch_get_item(
                        RequestItems=request_items
                    )
                    items = response.get("Responses", {}).get(
                        self._config.aws.sync_state_table, []
                    )
                    for item in items:
                        pk_value = item["pk"]
                        opp_id = pk_value.replace("OPP#", "") if isinstance(pk_value, str) else None
                        update_date = _as_str(item.get("govwin_update_date"))
                        if opp_id and update_date:
                            result[opp_id] = update_date

                    # Retry any unprocessed keys
                    request_items = response.get("UnprocessedKeys", {})
                    if request_items:
                        table = self._config.aws.sync_state_table
                        table_entry: Any = request_items.get(table, {})
                        unprocessed = table_entry.get("Keys", []) if table_entry else []
                        logger.warning("Retrying %d unprocessed keys", len(unprocessed))
            except ClientError:
                logger.warning("Failed to batch read opp update dates")

        return result

    # -----------------------------------------------------------------------
    # Entity Mappings
    # -----------------------------------------------------------------------

    def get_entity_hubspot_id(
        self, govwin_type: str, govwin_id: str
    ) -> str | None:
        """Get the HubSpot ID for a GovWin entity."""
        try:
            response = self._mappings_table.get_item(
                Key={
                    "pk": f"{govwin_type}#{govwin_id}",
                    "sk": "HUBSPOT_MAPPING",
                }
            )
            item = response.get("Item")
            return _as_str(item.get("hubspot_id")) if item else None
        except ClientError:
            return None

    def set_entity_mapping(
        self,
        govwin_type: str,
        govwin_id: str,
        hubspot_id: str,
    ) -> None:
        """Store a mapping between a GovWin entity and HubSpot object."""
        self._mappings_table.put_item(
            Item={
                "pk": f"{govwin_type}#{govwin_id}",
                "sk": "HUBSPOT_MAPPING",
                "hubspot_id": hubspot_id,
                "last_synced": datetime.now(UTC).isoformat(),
                "ttl": int(time.time()) + 180 * 86400,
            }
        )

    def batch_set_entity_mappings(
        self,
        mappings: list[tuple[str, str, str]],
    ) -> None:
        """Batch write entity mappings. Each tuple is (govwin_type, govwin_id, hubspot_id)."""
        with self._mappings_table.batch_writer() as writer:
            for govwin_type, govwin_id, hubspot_id in mappings:
                writer.put_item(
                    Item={
                        "pk": f"{govwin_type}#{govwin_id}",
                        "sk": "HUBSPOT_MAPPING",
                        "hubspot_id": hubspot_id,
                        "last_synced": datetime.now(UTC).isoformat(),
                        "ttl": int(time.time()) + 180 * 86400,
                    }
                )

    # -----------------------------------------------------------------------
    # ACE (AWS Partner Central) Mappings
    # -----------------------------------------------------------------------

    def get_ace_mapping(self, govwin_id: str) -> dict[str, Any] | None:
        """Return the ACE record for a GovWin opportunity, or None if not submitted."""
        try:
            response = self._mappings_table.get_item(
                Key={"pk": f"ACE#{govwin_id}", "sk": "MAPPING"}
            )
            item = response.get("Item")
            return dict(item) if item else None
        except ClientError:
            logger.warning("Failed to read ACE mapping for %s", govwin_id)
            return None

    def update_ace_mapping(
        self,
        govwin_id: str,
        *,
        ace_opportunity_id: str | None = None,
        last_modified_date: str | None = None,
        ace_engagement_invitation_id: str | None = None,
        ace_task_id: str | None = None,
        ace_task_client_token: str | None = None,
        client_token: str | None = None,
        hubspot_deal_id: str | None = None,
    ) -> None:
        """Merge the supplied ACE fields into the mapping for ``govwin_id``.

        Uses ``UpdateItem`` with SET expressions so that fields written by an
        earlier step (CreateOpportunity, AssociateOpportunity) are preserved
        when a later step (StartEngagement) writes its result. Pass only the
        fields you intend to change; ``None`` values are skipped.
        """
        updates: dict[str, Any] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "ttl": int(time.time()) + 365 * 86400,
        }
        if ace_opportunity_id is not None:
            updates["ace_opportunity_id"] = ace_opportunity_id
        if last_modified_date is not None:
            updates["last_modified_date"] = last_modified_date
        if ace_engagement_invitation_id is not None:
            updates["ace_engagement_invitation_id"] = ace_engagement_invitation_id
        if ace_task_id is not None:
            updates["ace_task_id"] = ace_task_id
        if ace_task_client_token is not None:
            updates["ace_task_client_token"] = ace_task_client_token
        if client_token is not None:
            updates["client_token"] = client_token
        if hubspot_deal_id is not None:
            updates["hubspot_deal_id"] = hubspot_deal_id

        names = {f"#k{i}": k for i, k in enumerate(updates)}
        values = {f":v{i}": v for i, (_, v) in enumerate(updates.items())}
        set_expr = ", ".join(
            f"{name} = :v{i}" for i, name in enumerate(names)
        )
        self._mappings_table.update_item(
            Key={"pk": f"ACE#{govwin_id}", "sk": "MAPPING"},
            UpdateExpression=f"SET {set_expr}",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

        # Maintain reverse-lookup records so find_govwin_by_invitation_id
        # and find_govwin_by_hubspot_deal_id can use O(1) GetItem instead
        # of an expensive table Scan.
        if ace_engagement_invitation_id:
            self._put_reverse_index(
                f"INV#{ace_engagement_invitation_id}", govwin_id
            )
        if hubspot_deal_id:
            self._put_reverse_index(f"DEAL#{hubspot_deal_id}", govwin_id)

    # Back-compat alias: callers that meant to overwrite still get merge
    # semantics. New code should use ``update_ace_mapping`` directly.
    set_ace_mapping = update_ace_mapping

    def reserve_client_token(self, govwin_id: str, client_token: str) -> str:
        """Atomically reserve a ClientToken for a pending CreateOpportunity.

        Uses a conditional ``put_item`` so two concurrent SQS deliveries for
        the same deal cannot both reserve different tokens (which would
        otherwise mint two ACE opportunities for one GovWin opp). On
        contention, falls back to reading the winning token.
        """
        try:
            self._mappings_table.put_item(
                Item={
                    "pk": f"ACE#{govwin_id}",
                    "sk": "MAPPING",
                    "client_token": client_token,
                    "ace_opportunity_id": "",
                    "reserved_at": datetime.now(UTC).isoformat(),
                    "ttl": int(time.time()) + 365 * 86400,
                },
                ConditionExpression=(
                    "attribute_not_exists(pk) OR attribute_not_exists(client_token)"
                ),
            )
            return client_token
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code != "ConditionalCheckFailedException":
                raise
            existing = self.get_ace_mapping(govwin_id) or {}
            return str(existing.get("client_token") or client_token)

    def reserve_task_client_token(self, govwin_id: str, client_token: str) -> str:
        """Reserve a ClientToken for the StartEngagementFromOpportunityTask call.

        Same idempotency guarantee as ``reserve_client_token`` but scoped to
        the engagement-task token so retries reuse it instead of regenerating.
        """
        existing = self.get_ace_mapping(govwin_id) or {}
        token = existing.get("ace_task_client_token")
        if token:
            return str(token)
        try:
            self._mappings_table.update_item(
                Key={"pk": f"ACE#{govwin_id}", "sk": "MAPPING"},
                UpdateExpression="SET ace_task_client_token = :t",
                ConditionExpression="attribute_not_exists(ace_task_client_token)",
                ExpressionAttributeValues={":t": client_token},
            )
            return client_token
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code != "ConditionalCheckFailedException":
                raise
            refreshed = self.get_ace_mapping(govwin_id) or {}
            return str(refreshed.get("ace_task_client_token") or client_token)

    def find_govwin_by_invitation_id(self, invitation_id: str) -> str | None:
        """Locate the GovWin id whose ACE mapping holds this engagement invitation.

        Uses an O(1) GetItem against a reverse-index record written by
        ``update_ace_mapping`` whenever ``ace_engagement_invitation_id`` is
        set. The reverse record's pk is ``INV#<invitation_id>`` and its
        body carries ``govwin_id``.
        """
        try:
            response = self._mappings_table.get_item(
                Key={"pk": f"INV#{invitation_id}", "sk": "REVERSE"}
            )
        except ClientError:
            logger.exception("get reverse-index for invitation %s failed", invitation_id)
            return None
        item = response.get("Item")
        return _as_str(item.get("govwin_id")) if item else None

    def find_govwin_by_hubspot_deal_id(self, hubspot_deal_id: str) -> str | None:
        """Locate the GovWin id whose ACE mapping points at this HubSpot deal.

        O(1) GetItem against a reverse-index record (pk
        ``DEAL#<hubspot_deal_id>``) written by ``update_ace_mapping``.
        """
        try:
            response = self._mappings_table.get_item(
                Key={"pk": f"DEAL#{hubspot_deal_id}", "sk": "REVERSE"}
            )
        except ClientError:
            logger.exception("get reverse-index for hubspot deal %s failed", hubspot_deal_id)
            return None
        item = response.get("Item")
        return _as_str(item.get("govwin_id")) if item else None

    def _put_reverse_index(self, pk: str, govwin_id: str) -> None:
        """Write a reverse-lookup record. Uses the same TTL as the forward record."""
        self._mappings_table.put_item(
            Item={
                "pk": pk,
                "sk": "REVERSE",
                "govwin_id": govwin_id,
                "updated_at": datetime.now(UTC).isoformat(),
                "ttl": int(time.time()) + 365 * 86400,
            }
        )

    def is_event_seen(self, event_id: str) -> bool:
        """Return True if we have already processed this EventBridge event id."""
        try:
            response = self._mappings_table.get_item(
                Key={"pk": f"EVT#{event_id}", "sk": "SEEN"}
            )
            return response.get("Item") is not None
        except ClientError:
            return False

    def mark_event_seen_atomic(self, event_id: str, ttl_seconds: int = 86400) -> bool:
        """Atomically mark an EventBridge event id as seen.

        Returns True on first sighting (caller should process the event) and
        False if the event was already marked (caller should skip). Combines
        the prior is_event_seen + mark_event_seen pair into a single
        conditional write to eliminate the TOCTOU window.
        """
        try:
            self._mappings_table.put_item(
                Item={
                    "pk": f"EVT#{event_id}",
                    "sk": "SEEN",
                    "seen_at": datetime.now(UTC).isoformat(),
                    "ttl": int(time.time()) + ttl_seconds,
                },
                ConditionExpression="attribute_not_exists(pk)",
            )
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException":
                return False
            raise

    def mark_event_seen(self, event_id: str, ttl_seconds: int = 86400) -> None:
        """Mark an EventBridge event id as processed (non-atomic; legacy)."""
        self._mappings_table.put_item(
            Item={
                "pk": f"EVT#{event_id}",
                "sk": "SEEN",
                "seen_at": datetime.now(UTC).isoformat(),
                "ttl": int(time.time()) + ttl_seconds,
            }
        )
