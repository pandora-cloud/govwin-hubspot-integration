# Sandbox testing for the AWS Partner Central Selling API

> Snapshot from https://docs.aws.amazon.com/partner-central/latest/selling-api/testing-sandbox.html captured 2026-04-28.

## What sandbox is

A separate catalog (`Catalog: "Sandbox"`) that mirrors the production API but doesn't affect real ACE data. Same endpoint (`partnercentral-selling.us-east-1.api.aws`), different catalog string. Lets us:

- Run integration tests against real API responses, not mocks
- Practice the partner-Sender and partner-Receiver flows without spamming the AWS sales team
- Validate field mappings before going live

EventBridge events from sandbox are tagged `"catalog": "Sandbox"` so the same Lambdas can listen to both with rule patterns that filter appropriately.

## IAM policy for sandbox-only

To make sure development/test invocations can't accidentally hit production, create a separate IAM role with this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "partnercentral:CreateOpportunity",
        "partnercentral:UpdateOpportunity",
        "partnercentral:ListOpportunities",
        "partnercentral:GetOpportunity",
        "partnercentral:GetAwsOpportunitySummary",
        "partnercentral:ListSolutions",
        "partnercentral:AssociateOpportunity",
        "partnercentral:DisassociateOpportunity",
        "partnercentral:AssignOpportunity",
        "partnercentral:SubmitOpportunity",
        "partnercentral:CreateEngagement",
        "partnercentral:CreateResourceSnapshotJob",
        "partnercentral:StartResourceSnapshotJob"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {"partnercentral:Catalog": "Sandbox"}
      }
    }
  ]
}
```

The condition `partnercentral:Catalog: Sandbox` is the safety net: even if someone passes `Catalog: "AWS"` in code, the API rejects with `AccessDeniedException` because the IAM policy is sandbox-only.

## Simulating an AWS-originated referral

Sandbox supports `Origin: "AWS Referral"` (production requires `Partner Referral`). Use this to test the partner-Receiver flow:

```json
{
  "Catalog": "Sandbox",
  "Origin": "AWS Referral",
  "ClientToken": "test-uuid",
  "Customer": {...},
  "Project": {...}
}
```

Then `StartEngagementByAcceptingInvitationTask` walks through the accept flow.

## Switching environments cleanly

In our config, drive this from a single env var so it's hard to misconfigure:

```python
ACE_CATALOG = os.environ.get("ACE_CATALOG", "Sandbox")  # never default to AWS
```

Two Lambda environments (or two Step Function stages — `dev` vs `prod`) each with their own IAM role and `ACE_CATALOG` value.

## Recommended testing workflow

1. **Unit:** mock `boto3.client('partnercentral-selling')` calls. Already pattern-matched to existing `src/govwin/client.py` and `src/hubspot/client.py` test approach.
2. **Sandbox integration:** new tests in `tests/integration/test_ace_sandbox.py` that call the real API with `Catalog: Sandbox`, verify CreateOpportunity → AssociateOpportunity → StartEngagement flow, then clean up by archiving the sandbox opportunities.
3. **Production smoke:** one manual end-to-end test against `Catalog: AWS` with a real GovWin-marked opportunity (analogous to the smoke matrix we just ran for the HubSpot side).
