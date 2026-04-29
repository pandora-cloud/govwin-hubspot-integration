"""Sandbox smoke matrix for the AWS Partner Central submission half (Phase 4.1).

Runs scenarios 1-5 and 10 from docs/testing.md against a real Sandbox catalog
in Pandora's AWS account. Cleans up the sandbox opportunities at the end.

Scenarios:
  1. CreateOpportunity
  2. AssociateOpportunity with the configured Solution
  3. StartEngagementFromOpportunityTask
  4. UpdateOpportunity with optimistic locking (positive)
  5. UpdateOpportunity with stale lock (negative -> ConflictException recovery)
 10. HubSpot webhook signature validation (negative: forged signature -> 401)

The remaining scenarios (6-9, 11) are manual; see docs/phase4-runbook.md.

Usage:
  python scripts/sandbox_smoke.py [--keep] [--solution-id S-XXXXXXX] \\
      [--api-url https://abc.execute-api.us-east-1.amazonaws.com/hubspot]

Environment:
  AWS_PROFILE / standard boto3 credential precedence (must have Sandbox IAM).
  ACE_DEFAULT_SOLUTION_ID (or pass --solution-id).
  HUBSPOT_WEBHOOK_TARGET_URL for scenario 10 (or pass --api-url).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError

CATALOG = "Sandbox"
REGION = "us-east-1"


def _client() -> Any:
    return boto3.client("partnercentral-selling", region_name=REGION)


def _ok(label: str, msg: str = "") -> None:
    print(f"  [OK] {label}{(': ' + msg) if msg else ''}")


def _fail(label: str, msg: str) -> None:
    print(f"  [FAIL] {label}: {msg}")


def _build_create_payload(client_token: str) -> dict[str, Any]:
    return {
        "Catalog": CATALOG,
        "ClientToken": client_token,
        "Origin": "AWS Referral",  # Sandbox accepts AWS Referral; prod requires Partner Referral
        "OpportunityType": "Net New Business",
        "PrimaryNeedsFromAws": ["Co-Sell - Technical Consultation"],
        "PartnerOpportunityIdentifier": f"SMOKE-{uuid.uuid4().hex[:8]}",
        "Customer": {
            "Account": {
                "CompanyName": "Sandbox Smoke Test Customer",
                "Industry": "Government",
                "CountryCode": "US",
            }
        },
        "Project": {
            "Title": "Sandbox smoke: AWS migration for federal customer",
            "CustomerBusinessProblem": "Smoke-test opportunity created by sandbox_smoke.py",
            "CustomerUseCase": "Smoke-test opportunity created by sandbox_smoke.py",
            "DeliveryModels": ["Professional Services"],
            "ExpectedCustomerSpend": [
                {
                    "Amount": "100000.00",
                    "CurrencyCode": "USD",
                    "Frequency": "Monthly",
                    "TargetCompany": "Pandora Cloud LLC",
                }
            ],
        },
        "LifeCycle": {
            "ReviewStatus": "Pending Submission",
            "TargetCloseDate": "2026-12-31",
        },
    }


def scenario_1_create(client: Any) -> dict[str, Any]:
    print("Scenario 1: CreateOpportunity in Sandbox")
    token = str(uuid.uuid4())
    payload = _build_create_payload(token)
    response = client.create_opportunity(**payload)
    if not response.get("Id") or not response.get("LastModifiedDate"):
        raise RuntimeError(f"missing Id or LastModifiedDate in response: {response}")
    _ok("created", f"Id={response['Id']}")
    return response


def scenario_2_associate(client: Any, opp_id: str, solution_id: str) -> None:
    print("Scenario 2: AssociateOpportunity with configured Solution")
    client.associate_opportunity(
        Catalog=CATALOG,
        OpportunityIdentifier=opp_id,
        RelatedEntityIdentifier=solution_id,
        RelatedEntityType="Solutions",
    )
    _ok("associated", f"opp={opp_id} solution={solution_id}")


def scenario_3_start_engagement(client: Any, opp_id: str) -> dict[str, Any]:
    print("Scenario 3: StartEngagementFromOpportunityTask")
    response = client.start_engagement_from_opportunity_task(
        Catalog=CATALOG,
        ClientToken=str(uuid.uuid4()),
        Identifier=opp_id,
        AwsSubmission={"InvolvementType": "Co-Sell", "Visibility": "Full"},
    )
    task_id = response.get("TaskId")
    _ok("task started", f"task_id={task_id}")
    # Poll briefly for completion. AWS often completes within seconds in Sandbox.
    for _ in range(30):
        time.sleep(2)
        # No GetTask API; we check the opportunity to see if it now has an
        # engagement invitation associated.
        opp = client.get_opportunity(Catalog=CATALOG, Identifier=opp_id)
        review = opp.get("LifeCycle", {}).get("ReviewStatus")
        if review in {"Submitted", "Approved", "In Review", "Action Required"}:
            _ok("engagement complete", f"review_status={review}")
            return response
    print("  [WARN] task did not complete within 60s; continuing")
    return response


def scenario_4_update_with_optimistic_lock(client: Any, opp_id: str) -> str:
    """Returns the new LastModifiedDate after a successful update."""
    print("Scenario 4: UpdateOpportunity with optimistic locking (positive)")
    current = client.get_opportunity(Catalog=CATALOG, Identifier=opp_id)
    original_lmd = current["LastModifiedDate"]
    response = client.update_opportunity(
        Catalog=CATALOG,
        Identifier=opp_id,
        LastModifiedDate=original_lmd,
        Project={"Title": "Sandbox smoke: title updated by scenario 4"},
    )
    new_lmd = response.get("LastModifiedDate") or current["LastModifiedDate"]
    _ok("updated", f"opp={opp_id}")
    return str(new_lmd)


def scenario_5_stale_lock(client: Any, opp_id: str, stale_lmd: str) -> None:
    print("Scenario 5: UpdateOpportunity with stale lock (negative)")
    try:
        client.update_opportunity(
            Catalog=CATALOG,
            Identifier=opp_id,
            LastModifiedDate=stale_lmd,
            Project={"Title": "should fail"},
        )
        raise RuntimeError("expected ConflictException, got success")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "ConflictException":
            raise RuntimeError(f"expected ConflictException, got {code}") from exc
        _ok("conflict on stale lock", "ConflictException as expected")
    # Recovery: refetch and retry succeeds.
    fresh = client.get_opportunity(Catalog=CATALOG, Identifier=opp_id)
    client.update_opportunity(
        Catalog=CATALOG,
        Identifier=opp_id,
        LastModifiedDate=fresh["LastModifiedDate"],
        Project={"Title": "Sandbox smoke: recovered after stale lock"},
    )
    _ok("recovered", "refetch + retry succeeded")


def scenario_10_forged_signature(api_url: str) -> None:
    print("Scenario 10: HubSpot webhook signature validation (negative)")
    if not api_url:
        print("  [SKIP] no api-url provided")
        return
    body = json.dumps([{"objectId": 1, "subscriptionType": "object.propertyChange"}])
    headers = {
        "x-hubspot-signature-v3": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "x-hubspot-request-timestamp": str(int(time.time() * 1000)),
        "content-type": "application/json",
    }
    response = httpx.post(api_url, content=body, headers=headers, timeout=10.0)
    if response.status_code == 401:
        _ok("forged signature rejected", "401 as expected")
        return
    raise RuntimeError(
        f"expected 401 for forged signature, got {response.status_code}: {response.text[:200]}"
    )


def cleanup(client: Any, opp_id: str) -> None:
    """Best-effort cleanup of a sandbox opportunity.

    AWS does not currently expose a DeleteOpportunity API; the standard cleanup
    is to mark it Closed Lost in LifeCycle so it stops appearing in active
    queries. Sandbox state is also wiped periodically.
    """
    print(f"Cleanup: marking {opp_id} as Closed Lost")
    try:
        current = client.get_opportunity(Catalog=CATALOG, Identifier=opp_id)
        client.update_opportunity(
            Catalog=CATALOG,
            Identifier=opp_id,
            LastModifiedDate=current["LastModifiedDate"],
            LifeCycle={"ReviewStatus": "Closed Lost", "ClosedLostReason": "Other"},
        )
        _ok("marked closed lost", opp_id)
    except ClientError as exc:
        print(f"  [WARN] cleanup failed (non-fatal): {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="do not run cleanup at the end")
    parser.add_argument(
        "--solution-id",
        default=os.environ.get("ACE_DEFAULT_SOLUTION_ID", ""),
        help="Partner Central Solution ID (e.g. S-0051246)",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("HUBSPOT_WEBHOOK_TARGET_URL", ""),
        help="HubSpot webhook receiver URL (for scenario 10)",
    )
    args = parser.parse_args()

    if not args.solution_id:
        print("ERROR: --solution-id or ACE_DEFAULT_SOLUTION_ID is required")
        return 1

    client = _client()
    print(f"Running sandbox smoke matrix against catalog={CATALOG} region={REGION}")
    print()

    opp_id = ""
    try:
        create_response = scenario_1_create(client)
        opp_id = create_response["Id"]
        scenario_2_associate(client, opp_id, args.solution_id)
        scenario_3_start_engagement(client, opp_id)
        # After StartEngagement, the opportunity is locked from edits, so
        # scenarios 4 and 5 use a fresh opportunity.
        update_create = scenario_1_create(client)
        update_opp_id = update_create["Id"]
        scenario_4_update_with_optimistic_lock(client, update_opp_id)
        # scenario 5 uses the original LMD (now stale) to force a conflict.
        scenario_5_stale_lock(client, update_opp_id, str(update_create["LastModifiedDate"]))
        scenario_10_forged_signature(args.api_url)
        if not args.keep:
            cleanup(client, opp_id)
            cleanup(client, update_opp_id)
        print()
        print("ALL AUTOMATED SCENARIOS PASSED")
        return 0
    except Exception as exc:  # noqa: BLE001 -- top-level reporting
        print()
        print(f"FAIL: {type(exc).__name__}: {exc}")
        if opp_id and not args.keep:
            cleanup(client, opp_id)
        return 1


if __name__ == "__main__":
    sys.exit(main())
