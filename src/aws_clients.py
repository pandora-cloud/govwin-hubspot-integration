"""Centralized boto3 client construction.

Every AWS client in the codebase goes through :func:`make_client` so that two
cross-cutting requirements are enforced in one place:

* **FIPS endpoints.** Federal deployments require FIPS 140-validated TLS
  endpoints (NIST 800-53 SC-13, CMMC L2 SC.L2-3.13.11). Setting
  ``use_fips_endpoint=True`` on the boto3 ``Config`` makes the SDK resolve to
  ``<service>-fips.<region>.amazonaws.com`` instead of the standard endpoint.
  Every AWS service this project uses (sqs, sns, dynamodb, secretsmanager,
  lambda, events, scheduler, apigatewayv2, logs, kms, partnercentral-selling)
  exposes a FIPS endpoint in us-east-1.

* **Region pinning for partnercentral-selling.** AWS only exposes the
  Partner Central Selling API in us-east-1 at this time. Even if the rest of
  the deployment lives in another region, this one client must target
  us-east-1 explicitly. All other clients honor the configured region.
"""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.config import Config

# Services AWS only exposes in us-east-1, regardless of the operator's
# configured region. Calls to other regions return a 403/endpoint error.
_US_EAST_1_ONLY = frozenset({"partnercentral-selling"})


def _fips_enabled() -> bool:
    """Whether FIPS endpoint resolution should be active.

    Production: always on. Disabled only when ``AWS_USE_FIPS_ENDPOINT=false``
    is set explicitly (the same env var boto3 honors natively). Test runners
    and the LocalStack docker-compose set this to ``false`` so requests hit
    moto / LocalStack endpoints instead of the real FIPS-suffixed hostnames
    those mocks do not implement.
    """
    return os.environ.get("AWS_USE_FIPS_ENDPOINT", "true").lower() != "false"


def _build_config(extra_config: Config | None = None) -> Config:
    config = Config(
        use_fips_endpoint=_fips_enabled(),
        retries={"mode": "standard", "max_attempts": 3},
    )
    if extra_config is not None:
        config = config.merge(extra_config)
    return config


def make_client(
    service: str,
    region: str,
    *,
    extra_config: Config | None = None,
) -> Any:
    """Return a boto3 client with FIPS enforced and region pinned.

    :param service: boto3 service name (e.g. ``"sqs"``, ``"partnercentral-selling"``).
    :param region: Operator-configured region. Overridden to ``us-east-1`` for
        services in :data:`_US_EAST_1_ONLY`.
    :param extra_config: Optional botocore Config that will be merged on top of
        the FIPS-enforcing default. Use this if a caller needs a longer timeout,
        a different signature version, etc.
    :returns: boto3 client with FIPS endpoint + correct region.
    """
    effective_region = "us-east-1" if service in _US_EAST_1_ONLY else region
    # boto3-stubs models ``client`` as a Literal-only overload set. We accept
    # arbitrary service strings here so callers don't have to thread literals
    # through every layer; cast keeps mypy quiet without changing runtime.
    return boto3.client(  # type: ignore[call-overload]
        service, region_name=effective_region, config=_build_config(extra_config)
    )


def make_resource(service: str, region: str) -> Any:
    """Return a boto3 resource with FIPS enforced (e.g. for DynamoDB)."""
    return boto3.resource(  # type: ignore[call-overload]
        service, region_name=region, config=_build_config()
    )
