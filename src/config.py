"""Configuration management for the GovWin-HubSpot integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GovWinConfig:
    base_url: str = "https://services.govwin.com/neo-ws"
    rate_limit_per_hour: int = 4000
    max_page_size: int = 100
    token_expiry_buffer_seconds: int = 300  # Refresh 5 min before expiry
    # GovWin's WSAPI accepts these oppType values:
    #   OPP, TNS, BID, FBO, OPN, TOP, FED_CONTRACT_AWARD, SL_CONTRACT_AWARD, ALL.
    # The ``lead`` type also exists in the data (mostly SLED Forecast Pre-RFP)
    # but is not a filterable oppType — leads share the BID global-ID prefix
    # and come through any time ``oppType=BID`` or ``oppType=ALL`` is used.
    opp_types: str = "ALL"
    market: str = ""  # Federal, SLED, or empty for both
    saved_search_id: str = ""  # GovWin saved search ID (filter #1)
    bookmarked_only: bool = False  # Only sync bookmarked opps (filter #2)
    marked_version: str = "2.2"  # "2.2" (Web Services), "2" (Deltek CRM), "" (disabled)


@dataclass(frozen=True)
class HubSpotConfig:
    base_url: str = "https://api.hubapi.com"
    max_batch_size: int = 100
    rate_limit_per_10s: int = 100
    rate_limit_buffer: int = 10  # Stay 10 requests below limit


@dataclass(frozen=True)
class AWSConfig:
    region: str = "us-east-1"
    sync_state_table: str = "govwin_sync_state"
    entity_mappings_table: str = "govwin_entity_mappings"
    govwin_secret_name: str = "govwin-hubspot/govwin"
    hubspot_secret_name: str = "govwin-hubspot/hubspot"
    govwin_tokens_secret_name: str = "govwin-hubspot/govwin-tokens"
    hubspot_webhook_secret_name: str = "govwin-hubspot/hubspot-webhook"
    sns_topic_arn: str = ""
    dlq_url: str = ""
    ace_submission_queue_url: str = ""
    ace_update_queue_url: str = ""


@dataclass(frozen=True)
class ACEConfig:
    """AWS Partner Central Selling API configuration.

    The catalog defaults to ``Sandbox`` so that any misconfigured deployment
    cannot accidentally write to production. Pair this with the IAM policy
    condition ``partnercentral:Catalog: Sandbox`` for dev environments.
    """

    catalog: str = "Sandbox"
    default_solution_id: str = ""  # e.g. "S-0051246" (Pandora Cloud Professional Services)
    default_involvement_type: str = "Co-Sell"
    default_visibility: str = "Full"
    default_origin: str = "Partner Referral"
    rate_limit_writes_per_sec: int = 1
    rate_limit_reads_per_sec: int = 10
    webhook_max_age_seconds: int = 300  # 5-minute replay window per HubSpot docs
    event_dedup_ttl_seconds: int = 86400  # AWS guarantees no redelivery beyond 24h


@dataclass(frozen=True)
class SyncConfig:
    schedule: str = "rate(1 hour)"
    max_concurrency: int = 2
    initial_lookback_days: int = 365
    batch_size: int = 10  # Opportunities per Step Function Map iteration (max 25 for payload limit)
    detail_endpoints: list[str] = field(
        default_factory=lambda: ["contacts", "companies", "placesOfPerformance", "contracts"]
    )


@dataclass(frozen=True)
class AppConfig:
    govwin: GovWinConfig
    hubspot: HubSpotConfig
    aws: AWSConfig
    sync: SyncConfig
    ace: ACEConfig
    environment: str = "prod"


_VALID_ACE_CATALOGS = {"AWS", "Sandbox"}


def _validated_catalog(value: str) -> str:
    if value not in _VALID_ACE_CATALOGS:
        raise ValueError(
            f"ACE_CATALOG must be one of {sorted(_VALID_ACE_CATALOGS)}, got {value!r}"
        )
    return value


def load_config() -> AppConfig:
    """Load configuration from environment variables with sensible defaults."""
    return AppConfig(
        govwin=GovWinConfig(
            base_url=os.environ.get("GOVWIN_BASE_URL", "https://services.govwin.com/neo-ws"),
            opp_types=os.environ.get("GOVWIN_OPP_TYPES", "ALL"),
            market=os.environ.get("GOVWIN_MARKET", ""),
            saved_search_id=os.environ.get("GOVWIN_SAVED_SEARCH_ID", ""),
            bookmarked_only=os.environ.get("GOVWIN_BOOKMARKED_ONLY", "false").lower() == "true",
            marked_version=os.environ.get("GOVWIN_MARKED_VERSION", "2.2"),
        ),
        hubspot=HubSpotConfig(
            base_url=os.environ.get("HUBSPOT_BASE_URL", "https://api.hubapi.com"),
        ),
        aws=AWSConfig(
            region=os.environ.get("AWS_REGION", "us-east-1"),
            sync_state_table=os.environ.get("SYNC_STATE_TABLE", "govwin_sync_state"),
            entity_mappings_table=os.environ.get("ENTITY_MAPPINGS_TABLE", "govwin_entity_mappings"),
            govwin_secret_name=os.environ.get("GOVWIN_SECRET_NAME", "govwin-hubspot/govwin"),
            hubspot_secret_name=os.environ.get("HUBSPOT_SECRET_NAME", "govwin-hubspot/hubspot"),
            govwin_tokens_secret_name=os.environ.get(
                "GOVWIN_TOKENS_SECRET_NAME", "govwin-hubspot/govwin-tokens"
            ),
            hubspot_webhook_secret_name=os.environ.get(
                "HUBSPOT_WEBHOOK_SECRET_NAME", "govwin-hubspot/hubspot-webhook"
            ),
            sns_topic_arn=os.environ.get("SNS_TOPIC_ARN", ""),
            dlq_url=os.environ.get("DLQ_URL", ""),
            ace_submission_queue_url=os.environ.get("ACE_SUBMISSION_QUEUE_URL", ""),
            ace_update_queue_url=os.environ.get("ACE_UPDATE_QUEUE_URL", ""),
        ),
        sync=SyncConfig(
            max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "2")),
            initial_lookback_days=int(os.environ.get("INITIAL_LOOKBACK_DAYS", "365")),
            batch_size=int(os.environ.get("BATCH_SIZE", "10")),
        ),
        ace=ACEConfig(
            catalog=_validated_catalog(os.environ.get("ACE_CATALOG", "Sandbox")),
            default_solution_id=os.environ.get("ACE_DEFAULT_SOLUTION_ID", ""),
            default_involvement_type=os.environ.get("ACE_DEFAULT_INVOLVEMENT_TYPE", "Co-Sell"),
            default_visibility=os.environ.get("ACE_DEFAULT_VISIBILITY", "Full"),
            default_origin=os.environ.get("ACE_DEFAULT_ORIGIN", "Partner Referral"),
        ),
        environment=os.environ.get("ENVIRONMENT", "prod"),
    )
