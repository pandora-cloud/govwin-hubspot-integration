"""Sandbox smoke matrix for the AWS Partner Central submission half (Phase 4.1).

Runs scenarios 1-5 and 10 from docs/testing.md against a real Sandbox catalog
in Pandora's AWS account. Cleans up the sandbox opportunities at the end.

Scenarios:
  1. CreateOpportunity (with OtherSolutionDescription so the opp is valid even
     without an associated Solution)
  2. AssociateOpportunity. Path is auto-selected:
       a) If --solution-id (or ACE_DEFAULT_SOLUTION_ID) names an Approved
          Sandbox Solution, associate that Solution.
       b) Otherwise, associate an AwsProduct (--aws-product, default
          "Amazon EC2"). Per the AWS partner-crm-integration-samples repo,
          AwsProducts are the recommended Sandbox associatable when the
          partner has no registered Solution. See:
          https://github.com/aws-samples/partner-crm-integration-samples
       c) --skip-associate forces no association at all (relies purely on
          the OtherSolutionDescription field).
  3. StartEngagementFromOpportunityTask
  4. UpdateOpportunity with optimistic locking (positive)
  5. UpdateOpportunity with stale lock (negative -> ConflictException recovery)
 10. HubSpot webhook signature validation (negative: forged signature -> 401)

The remaining scenarios (6-9, 11) are manual; see docs/phase4-runbook.md.

Note on Sandbox Solutions:
  AWS docs claim a default Sandbox solution `S-1234567` exists, but newly
  onboarded partner orgs see an empty list_solutions(Catalog="Sandbox")
  response. Open a Partner Central support case (CRM Integration) to have
  one provisioned. Until then, this script's AwsProducts path keeps the
  three-call flow exercised end-to-end.

Usage:
  python scripts/sandbox_smoke.py [--keep] \\
      [--solution-id S-XXXXXXX] \\
      [--aws-product "Amazon EC2"] \\
      [--skip-associate] \\
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
from pathlib import Path
from typing import Any

# Make `from src.ace.client import ACEClient` work when this script is
# launched directly (PYTHONPATH=. is otherwise required).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import boto3  # noqa: E402
import httpx  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

from src.ace.client import ACEClient  # noqa: E402

CATALOG = "Sandbox"
REGION = "us-east-1"
# Identifier from the canonical product list at
# https://github.com/aws-samples/partner-crm-integration-samples/blob/main/resources/aws_products.json
# AssociateOpportunity expects the short Identifier (e.g. "AmazonEC2Linux"),
# not the human-friendly Name ("Amazon EC2 Linux").
DEFAULT_AWS_PRODUCT = "AmazonEC2Linux"
OTHER_SOLUTION_DESCRIPTION = (
    "Sandbox smoke test: AWS migration accelerator for federal customers. "
    "Pandora Cloud delivers professional services around discovery, landing zone, "
    "workload migration, and post-migration optimization."
)


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
        # Partner Referral = we (Pandora) are originating this opportunity.
        # Do NOT use "AWS Referral" here even in Sandbox: that flow places
        # the opportunity in a separate incoming-invitation inbox not
        # visible to GetOpportunity until accepted.
        "Origin": "Partner Referral",
        "OpportunityType": "Net New Business",
        "PrimaryNeedsFromAws": ["Co-Sell - Technical Consultation"],
        "PartnerOpportunityIdentifier": f"SMOKE-{uuid.uuid4().hex[:8]}",
        "Customer": {
            "Account": {
                "CompanyName": "Sandbox Smoke Test Customer",
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
            "Title": "Sandbox smoke: AWS migration for federal customer",
            "CustomerBusinessProblem": "Smoke-test opportunity created by sandbox_smoke.py",
            "CustomerUseCase": "Migration / Database Migration",
            "DeliveryModels": ["Professional Services"],
            # OtherSolutionDescription is required when no Solution will be
            # associated. Populated unconditionally so the opportunity is
            # self-describing even when AssociateOpportunity is skipped or
            # falls back to an AwsProduct.
            "OtherSolutionDescription": OTHER_SOLUTION_DESCRIPTION,
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


def _resolve_associate_target(
    client: Any, solution_id: str, aws_product: str, skip: bool
) -> tuple[str, str] | None:
    """Pick what AssociateOpportunity should attach.

    Returns (RelatedEntityType, RelatedEntityIdentifier) or None to skip.

    Order of preference:
      1. Explicit --skip-associate -> skip.
      2. --solution-id provided AND it appears in list_solutions(Sandbox) ->
         use Solutions.
      3. Otherwise -> use AwsProducts with the configured product name. AWS
         Products are valid in Sandbox without any partner-side registration.
    """
    if skip:
        return None
    if solution_id:
        try:
            response = client.list_solutions(Catalog=CATALOG, MaxResults=50)
        except ClientError:
            response = {"SolutionSummaries": []}
        ids = {s.get("Id") for s in response.get("SolutionSummaries", [])}
        if solution_id in ids:
            return ("Solutions", solution_id)
        print(
            f"  [INFO] solution {solution_id} not found in Sandbox catalog "
            f"(list_solutions returned {len(ids)} entries); falling back to "
            f"AwsProducts ({aws_product})."
        )
    return ("AwsProducts", aws_product)


def scenario_1_create(client: Any) -> dict[str, Any]:
    print("Scenario 1: CreateOpportunity in Sandbox")
    token = str(uuid.uuid4())
    payload = _build_create_payload(token)
    response = client.create_opportunity(**payload)
    if not response.get("Id") or not response.get("LastModifiedDate"):
        raise RuntimeError(f"missing Id or LastModifiedDate in response: {response}")
    _ok("created", f"Id={response['Id']}")
    # AWS Partner Central is eventually consistent: GetOpportunity right after
    # CreateOpportunity can return ResourceNotFoundException for a few seconds.
    time.sleep(5)
    return response


def scenario_2_associate(
    client: Any, opp_id: str, target: tuple[str, str]
) -> None:
    related_type, related_id = target
    print(f"Scenario 2: AssociateOpportunity ({related_type})")
    client.associate_opportunity(
        Catalog=CATALOG,
        OpportunityIdentifier=opp_id,
        RelatedEntityIdentifier=related_id,
        RelatedEntityType=related_type,
    )
    _ok("associated", f"opp={opp_id} {related_type.lower()[:-1]}={related_id}")


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
        # No GetTask API; we check the opportunity to see if its review
        # status has advanced past Pending Submission.
        opp = client.get_opportunity(Catalog=CATALOG, Identifier=opp_id)
        review = opp.get("LifeCycle", {}).get("ReviewStatus")
        if review in {"Submitted", "Approved", "In review", "Action Required"}:
            _ok("engagement complete", f"review_status={review}")
            return response
    print("  [WARN] task did not complete within 60s; continuing")
    return response


def _get_with_retry(client: Any, opp_id: str, attempts: int = 6) -> dict[str, Any]:
    """GetOpportunity with backoff for the eventual-consistency window."""
    last_error: Exception | None = None
    for i in range(attempts):
        try:
            return client.get_opportunity(Catalog=CATALOG, Identifier=opp_id)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code != "ResourceNotFoundException":
                raise
            last_error = exc
            wait = 5 * (i + 1)  # 5, 10, 15, 20, 25, 30 seconds
            print(f"  [WAIT] {opp_id} not yet visible (attempt {i+1}/{attempts}); sleeping {wait}s")
            time.sleep(wait)
    assert last_error is not None
    raise last_error


def _scrub_for_update(current: dict[str, Any]) -> dict[str, Any]:
    """Delegate to the production ACEClient.scrub_for_update so the smoke
    test exercises the same whitelist as the deployed Lambda.
    """
    return ACEClient.scrub_for_update(current)


def scenario_4_update_with_optimistic_lock(client: Any, opp_id: str) -> str:
    """Returns the new LastModifiedDate after a successful update.

    UpdateOpportunity has PUT semantics: omitted fields are treated as being
    cleared. We fetch the current opportunity, mutate only the field we
    want to change, and send the full payload back.
    """
    print("Scenario 4: UpdateOpportunity with optimistic locking (positive)")
    current = _get_with_retry(client, opp_id)
    original_lmd = current["LastModifiedDate"]
    payload = _scrub_for_update(current)
    project = dict(payload.get("Project") or {})
    project["Title"] = "Sandbox smoke: title updated by scenario 4"
    payload["Project"] = project
    response = client.update_opportunity(
        Catalog=CATALOG,
        Identifier=opp_id,
        LastModifiedDate=original_lmd,
        **payload,
    )
    new_lmd = response.get("LastModifiedDate") or original_lmd
    _ok("updated", f"opp={opp_id}")
    return str(new_lmd)


def scenario_5_stale_lock(client: Any, opp_id: str, stale_lmd: str) -> None:
    print("Scenario 5: UpdateOpportunity with stale lock (negative)")
    fresh = _get_with_retry(client, opp_id)
    payload = _scrub_for_update(fresh)
    project = dict(payload.get("Project") or {})
    project["Title"] = "should fail"
    payload["Project"] = project
    try:
        client.update_opportunity(
            Catalog=CATALOG,
            Identifier=opp_id,
            LastModifiedDate=stale_lmd,
            **payload,
        )
        raise RuntimeError("expected ConflictException, got success")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "ConflictException":
            raise RuntimeError(f"expected ConflictException, got {code}") from exc
        _ok("conflict on stale lock", "ConflictException as expected")
    # Recovery: refetch and retry succeeds.
    fresh = _get_with_retry(client, opp_id)
    payload = _scrub_for_update(fresh)
    project = dict(payload.get("Project") or {})
    project["Title"] = "Sandbox smoke: recovered after stale lock"
    payload["Project"] = project
    client.update_opportunity(
        Catalog=CATALOG,
        Identifier=opp_id,
        LastModifiedDate=fresh["LastModifiedDate"],
        **payload,
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
    queries. Sandbox state is also wiped periodically by AWS, so a failure
    here is non-fatal.

    Sandbox enforces: Stage cannot move to "Closed Lost" while ReviewStatus is
    "Pending Submission". Opportunities that completed scenario 3
    (StartEngagement) end up with ReviewStatus = "Submitted" / "In review"
    and are closeable; opportunities that failed before that are stuck and
    will be cleared by AWS's periodic Sandbox reset.
    """
    print(f"Cleanup: marking {opp_id} as Closed Lost")
    try:
        current = _get_with_retry(client, opp_id, attempts=3)
        review = current.get("LifeCycle", {}).get("ReviewStatus", "")
        if review == "Pending Submission":
            print(
                f"  [SKIP] {opp_id} is still Pending Submission; cannot close. "
                "AWS will wipe Sandbox state on the next reset."
            )
            return
        payload = _scrub_for_update(current)
        # "Closed Lost" is a Stage enum value, not a ReviewStatus value.
        lc = dict(payload.get("LifeCycle") or {})
        lc["Stage"] = "Closed Lost"
        lc["ClosedLostReason"] = "Delay / Cancellation of Project"
        payload["LifeCycle"] = lc
        client.update_opportunity(
            Catalog=CATALOG,
            Identifier=opp_id,
            LastModifiedDate=current["LastModifiedDate"],
            **payload,
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
        help=(
            "Partner Central Solution ID to associate (e.g. S-0051246). "
            "Used only if it appears in the Sandbox solutions list."
        ),
    )
    parser.add_argument(
        "--aws-product",
        default=DEFAULT_AWS_PRODUCT,
        help=(
            "AwsProducts fallback for AssociateOpportunity when no Sandbox "
            "Solution is registered. Must be a real AWS product name; see "
            "github.com/aws-samples/partner-crm-integration-samples for the "
            "canonical list."
        ),
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("HUBSPOT_WEBHOOK_TARGET_URL", ""),
        help="HubSpot webhook receiver URL (for scenario 10)",
    )
    parser.add_argument(
        "--skip-associate",
        action="store_true",
        help=(
            "Skip scenarios 2 and 3 (AssociateOpportunity + StartEngagement). "
            "Useful for validating the rest of the flow without exercising "
            "AssociateOpportunity at all. Most users should NOT pass this -- "
            "the AwsProducts fallback runs the full three-call flow even "
            "without a Sandbox Solution."
        ),
    )
    args = parser.parse_args()

    client = _client()
    print(f"Running sandbox smoke matrix against catalog={CATALOG} region={REGION}")
    target = _resolve_associate_target(
        client,
        solution_id=args.solution_id,
        aws_product=args.aws_product,
        skip=args.skip_associate,
    )
    if target is None:
        print("(scenarios 2-3 will be skipped: --skip-associate)")
    else:
        print(f"(scenario 2 will associate {target[0]}={target[1]})")
    print()

    opp_id = ""
    update_opp_id = ""
    try:
        create_response = scenario_1_create(client)
        opp_id = create_response["Id"]
        if target is not None:
            scenario_2_associate(client, opp_id, target)
            scenario_3_start_engagement(client, opp_id)
            # After StartEngagement, the opportunity is locked from edits, so
            # scenarios 4 and 5 use a fresh opportunity. When skipping
            # associate the original opportunity remains editable, so the
            # update scenarios reuse it.
            update_create = scenario_1_create(client)
            update_opp_id = update_create["Id"]
            update_lmd = str(update_create["LastModifiedDate"])
        else:
            update_opp_id = opp_id
            update_lmd = str(create_response["LastModifiedDate"])
        scenario_4_update_with_optimistic_lock(client, update_opp_id)
        # scenario 5 uses the original (now stale) LMD to force a conflict.
        scenario_5_stale_lock(client, update_opp_id, update_lmd)
        scenario_10_forged_signature(args.api_url)
        if not args.keep:
            cleanup(client, opp_id)
            if update_opp_id and update_opp_id != opp_id:
                cleanup(client, update_opp_id)
        print()
        print("ALL RUN SCENARIOS PASSED")
        return 0
    except Exception as exc:  # noqa: BLE001 -- top-level reporting
        print()
        print(f"FAIL: {type(exc).__name__}: {exc}")
        if not args.keep:
            if opp_id:
                cleanup(client, opp_id)
            if update_opp_id and update_opp_id != opp_id:
                cleanup(client, update_opp_id)
        return 1


if __name__ == "__main__":
    sys.exit(main())
