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
    opp_types: str = "ALL"  # OPP, TNS, BID, FBO, OPN, TOP, ALL
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
    sns_topic_arn: str = ""
    dlq_url: str = ""


@dataclass(frozen=True)
class SyncConfig:
    schedule: str = "rate(4 hours)"
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
    environment: str = "prod"


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
            sns_topic_arn=os.environ.get("SNS_TOPIC_ARN", ""),
            dlq_url=os.environ.get("DLQ_URL", ""),
        ),
        sync=SyncConfig(
            max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "2")),
            initial_lookback_days=int(os.environ.get("INITIAL_LOOKBACK_DAYS", "365")),
            batch_size=int(os.environ.get("BATCH_SIZE", "10")),
        ),
        environment=os.environ.get("ENVIRONMENT", "prod"),
    )
