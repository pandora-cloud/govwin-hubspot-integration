"""AWS Partner Central Selling API client.

Wraps boto3 ``partnercentral-selling`` calls with:

* per-call rate limiting (1 write/sec, 10 reads/sec)
* tenacity-driven retries on ThrottlingException and InternalServerException
* an optimistic-locking helper that fetches LastModifiedDate before update
  and retries on ConflictException

The catalog defaults to ``Sandbox`` from config. The IAM policy condition
``partnercentral:Catalog: Sandbox`` should enforce this for dev environments.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, NoReturn, cast

from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.ace.rate_limiter import ACERateLimiter
from src.aws_clients import make_client
from src.config import AppConfig

logger = logging.getLogger(__name__)


class ACEAPIError(Exception):
    """Raised for AWS Partner Central API errors that we cannot recover from."""

    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code
        super().__init__(message)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if a ClientError represents a transient failure."""
    if not isinstance(exc, ClientError):
        return False
    code = exc.response.get("Error", {}).get("Code", "")
    return code in {"ThrottlingException", "InternalServerException", "ServiceUnavailableException"}


class ACEClient:
    """Client for the AWS Partner Central Selling API."""

    def __init__(self, config: AppConfig, boto3_client: Any | None = None) -> None:
        self._config = config
        self._catalog = config.ace.catalog
        # partnercentral-selling is exposed only in us-east-1; FIPS endpoint
        # is selected automatically. make_client enforces both.
        self._client = boto3_client or make_client(
            "partnercentral-selling", config.aws.region
        )
        self._rate_limiter = ACERateLimiter(
            reads_per_sec=config.ace.rate_limit_reads_per_sec,
            writes_per_sec=config.ace.rate_limit_writes_per_sec,
        )

    @property
    def catalog(self) -> str:
        return self._catalog

    def __enter__(self) -> ACEClient:
        return self

    def __exit__(self, *args: Any) -> None:
        # boto3 clients do not require explicit close, but match the
        # HubSpotClient context-manager pattern so callers can use both
        # consistently.
        return None

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _call_write(self, op: str, **kwargs: Any) -> dict[str, Any]:
        self._rate_limiter.acquire_write()
        method = getattr(self._client, op)
        return cast(dict[str, Any], method(**kwargs))

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _call_read(self, op: str, **kwargs: Any) -> dict[str, Any]:
        self._rate_limiter.acquire_read()
        method = getattr(self._client, op)
        return cast(dict[str, Any], method(**kwargs))

    # ------------------------------------------------------------------
    # Opportunity lifecycle
    # ------------------------------------------------------------------

    def create_opportunity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a new ACE opportunity.

        ``payload`` is expected to already include ``Catalog`` and ``ClientToken``;
        callers should generate the ClientToken via :meth:`new_client_token` and
        persist it before this call so retries can reuse it.
        """
        if "Catalog" not in payload:
            payload = {**payload, "Catalog": self._catalog}
        if "ClientToken" not in payload:
            payload = {**payload, "ClientToken": self.new_client_token()}
        logger.info("ace.create_opportunity catalog=%s", payload["Catalog"])
        try:
            return self._call_write("create_opportunity", **payload)
        except ClientError as exc:
            self._raise_api_error("CreateOpportunity", exc)

    def get_opportunity(self, identifier: str) -> dict[str, Any]:
        try:
            return self._call_read(
                "get_opportunity", Catalog=self._catalog, Identifier=identifier
            )
        except ClientError as exc:
            self._raise_api_error("GetOpportunity", exc)

    def list_opportunities(self, **filters: Any) -> dict[str, Any]:
        try:
            return self._call_read("list_opportunities", Catalog=self._catalog, **filters)
        except ClientError as exc:
            self._raise_api_error("ListOpportunities", exc)

    def update_opportunity(
        self,
        identifier: str,
        last_modified_date: Any,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an opportunity using optimistic locking via LastModifiedDate."""
        params = {
            "Catalog": self._catalog,
            "Identifier": identifier,
            "LastModifiedDate": last_modified_date,
            **updates,
        }
        try:
            return self._call_write("update_opportunity", **params)
        except ClientError as exc:
            self._raise_api_error("UpdateOpportunity", exc)

    def update_with_retry(
        self,
        identifier: str,
        updates: dict[str, Any],
        max_attempts: int = 3,
        known_last_modified_date: Any | None = None,
    ) -> dict[str, Any]:
        """Update an opportunity, refreshing LastModifiedDate on ConflictException.

        :param known_last_modified_date: caller-provided LastModifiedDate (e.g.
            persisted in DynamoDB after the last successful write). When
            supplied the first attempt skips the GetOpportunity round-trip;
            subsequent attempts always refetch.
        """
        last_error: Exception | None = None
        last_modified = known_last_modified_date
        for attempt in range(max_attempts):
            if last_modified is None:
                current = self.get_opportunity(identifier)
                last_modified = current.get("LastModifiedDate")
                if last_modified is None:
                    raise ACEAPIError(
                        f"GetOpportunity returned no LastModifiedDate for {identifier}",
                        code="MissingLastModifiedDate",
                    )
            try:
                return self.update_opportunity(
                    identifier=identifier,
                    last_modified_date=last_modified,
                    updates=updates,
                )
            except ACEAPIError as exc:
                if exc.code != "ConflictException":
                    raise
                last_error = exc
                last_modified = None  # force refetch on next attempt
                logger.warning(
                    "ConflictException on update %s attempt %d/%d; refetching",
                    identifier,
                    attempt + 1,
                    max_attempts,
                )
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Solutions and associations
    # ------------------------------------------------------------------

    def list_solutions(self, **filters: Any) -> dict[str, Any]:
        try:
            return self._call_read("list_solutions", Catalog=self._catalog, **filters)
        except ClientError as exc:
            self._raise_api_error("ListSolutions", exc)

    def associate_opportunity(
        self,
        opportunity_identifier: str,
        related_entity_identifier: str,
        related_entity_type: str = "Solutions",
    ) -> dict[str, Any]:
        try:
            return self._call_write(
                "associate_opportunity",
                Catalog=self._catalog,
                OpportunityIdentifier=opportunity_identifier,
                RelatedEntityIdentifier=related_entity_identifier,
                RelatedEntityType=related_entity_type,
            )
        except ClientError as exc:
            self._raise_api_error("AssociateOpportunity", exc)

    def disassociate_opportunity(
        self,
        opportunity_identifier: str,
        related_entity_identifier: str,
        related_entity_type: str = "Solutions",
    ) -> dict[str, Any]:
        try:
            return self._call_write(
                "disassociate_opportunity",
                Catalog=self._catalog,
                OpportunityIdentifier=opportunity_identifier,
                RelatedEntityIdentifier=related_entity_identifier,
                RelatedEntityType=related_entity_type,
            )
        except ClientError as exc:
            self._raise_api_error("DisassociateOpportunity", exc)

    # ------------------------------------------------------------------
    # Engagement (the "submit" call)
    # ------------------------------------------------------------------

    def start_engagement_from_opportunity_task(
        self,
        opportunity_identifier: str,
        client_token: str,
        aws_submission: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit an opportunity to AWS for review.

        ``aws_submission`` shape: ``{"InvolvementType": "Co-Sell", "Visibility": "Full"}``.
        Defaults pulled from config when not provided.
        """
        if aws_submission is None:
            aws_submission = {
                "InvolvementType": self._config.ace.default_involvement_type,
                "Visibility": self._config.ace.default_visibility,
            }
        try:
            return self._call_write(
                "start_engagement_from_opportunity_task",
                Catalog=self._catalog,
                ClientToken=client_token,
                Identifier=opportunity_identifier,
                AwsSubmission=aws_submission,
            )
        except ClientError as exc:
            self._raise_api_error("StartEngagementFromOpportunityTask", exc)

    def start_engagement_by_accepting_invitation_task(
        self,
        invitation_identifier: str,
        client_token: str,
    ) -> dict[str, Any]:
        try:
            return self._call_write(
                "start_engagement_by_accepting_invitation_task",
                Catalog=self._catalog,
                ClientToken=client_token,
                Identifier=invitation_identifier,
            )
        except ClientError as exc:
            self._raise_api_error("StartEngagementByAcceptingInvitationTask", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def new_client_token() -> str:
        """Return a fresh idempotency token. Persist before the call so retries reuse it."""
        return str(uuid.uuid4())

    @staticmethod
    def scrub_for_update(current: dict[str, Any]) -> dict[str, Any]:
        """Reduce a GetOpportunity response to fields UpdateOpportunity accepts.

        UpdateOpportunity has PUT semantics: omitted fields are treated as
        being cleared. The valid Update params per the boto3 service model
        are narrower than what GetOpportunity returns, so we whitelist.
        Catalog, Identifier, and LastModifiedDate are passed by the caller
        and are not part of the body fields we scrub.
        """
        # AWS UpdateOpportunity has PUT semantics: any field omitted from
        # the request is treated as null. We must echo every field that
        # AWS could have on the opportunity, including fields a BD
        # operator may have set directly in Partner Central UI
        # (Marketing.CampaignName, SoftwareRevenue, NationalSecurity).
        # Dropping them would silently clear them on every webhook.
        #
        # The whitelist matches the boto3 input shape for UpdateOpportunity
        # exactly. PartnerOpportunityIdentifier MUST be echoed too: it
        # carries the GovWin cross-reference and AWS clears it without it.
        allowed = {
            "PrimaryNeedsFromAws",
            "NationalSecurity",
            "Customer",
            "Project",
            "OpportunityType",
            "Marketing",
            "SoftwareRevenue",
            "LifeCycle",
            "PartnerOpportunityIdentifier",
        }
        scrubbed = {k: v for k, v in current.items() if k in allowed}

        # AWS sometimes returns stub fields the boto3 client-side validator
        # rejects on UpdateOpportunity. Specifically:
        #
        #   * ExpectedCustomerSpend may include an entry with only
        #     CurrencyCode populated -- Amount / Frequency / TargetCompany
        #     are all required when the entry is present.
        #   * Customer.Contacts[] may contain entries missing FirstName /
        #     LastName / Email when AWS auto-populated from invitations.
        #   * Project.SalesActivities may come back as [] which AWS rejects
        #     when present (must be non-empty if the key exists).
        #   * Marketing may come back as {Source: "None"} which AWS rejects
        #     when paired with companion fields. Drop the whole block in
        #     that case to mirror the create-path logic.
        project = scrubbed.get("Project")
        if isinstance(project, dict):
            spend = project.get("ExpectedCustomerSpend")
            if isinstance(spend, list):
                cleaned = [
                    e for e in spend
                    if isinstance(e, dict)
                    and e.get("Amount")
                    and e.get("Frequency")
                    and e.get("TargetCompany")
                ]
                if cleaned:
                    project["ExpectedCustomerSpend"] = cleaned
                else:
                    project.pop("ExpectedCustomerSpend", None)
            activities = project.get("SalesActivities")
            if isinstance(activities, list) and not activities:
                project.pop("SalesActivities", None)

        customer = scrubbed.get("Customer")
        if isinstance(customer, dict):
            contacts = customer.get("Contacts")
            if isinstance(contacts, list):
                cleaned_contacts = [
                    c for c in contacts
                    if isinstance(c, dict)
                    and c.get("FirstName")
                    and c.get("LastName")
                    and c.get("Email")
                ]
                if cleaned_contacts:
                    customer["Contacts"] = cleaned_contacts
                else:
                    customer.pop("Contacts", None)

        # Marketing handling. Two AWS-side rules collide here:
        #
        # 1. UpdateOpportunity REQUIRES Marketing.Source on every call
        #    (introduced 2026-05; surfaced in sandbox smoke as
        #    REQUIRED_FIELD_MISSING marketing.source). The Marketing
        #    block can no longer be dropped from the payload.
        #
        # 2. AWS still REJECTS companion Marketing fields (UseCases,
        #    AwsFundingUsed, CampaignName, Channel) when Source is
        #    anything other than "Marketing Activity".
        #
        # The reconciliation: always emit Marketing.Source. When Source
        # is empty or "None" (no marketing context), strip companion
        # fields and emit just {Source: "None"} so AWS sees a valid
        # block without rejected companions.
        marketing = scrubbed.get("Marketing")
        if not isinstance(marketing, dict):
            marketing = {}
        source = marketing.get("Source")
        if source in (None, ""):
            source = "None"
        if source != "Marketing Activity":
            # Strip companion fields that AWS rejects when Source is not
            # "Marketing Activity". Keeping Source itself is required.
            marketing = {"Source": source}
        else:
            marketing = {**marketing, "Source": source}
        scrubbed["Marketing"] = marketing

        return scrubbed

    @staticmethod
    def _raise_api_error(op: str, exc: ClientError) -> NoReturn:
        code = exc.response.get("Error", {}).get("Code", "")
        message = exc.response.get("Error", {}).get("Message", str(exc))
        raise ACEAPIError(f"{op} failed [{code}]: {message}", code=code) from exc
