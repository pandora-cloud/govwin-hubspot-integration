# `StartEngagementFromOpportunityTask` API reference

> Snapshot from https://docs.aws.amazon.com/partner-central/latest/selling-api/API_StartEngagementFromOpportunityTask.html captured 2026-04-28.

## Purpose

The "submit my deal to AWS" call. Asynchronous. Bundles six operations in one task:

1. `GetOpportunity` (sanity-check)
2. `CreateEngagement` (if no engagement exists)
3. `CreateResourceSnapshot` (point-in-time of the opportunity)
4. `CreateResourceSnapshotJob` (attach snapshot to engagement)
5. `CreateEngagementInvitation` (invite AWS)
6. `SubmitOpportunity` (lock from edits, push into AWS review)

After this returns successfully and the task reaches `COMPLETE`, the opportunity is in AWS's review queue and can no longer be edited via `UpdateOpportunity` until review finishes.

## HTTP

- **Method:** `POST`
- **Service:** `partnercentral-selling`
- **Quota:** counts as a **write** action (1/sec, 10K/24h)

## Request

```json
{
  "Identifier": "O123456789012345",
  "Catalog": "AWS",
  "ClientToken": "550e8400-e29b-41d4-a716-446655440000",
  "AwsSubmission": {
    "InvolvementType": "Co-Sell",
    "Visibility": "Full"
  },
  "Tags": [
    {"Key": "Source", "Value": "GovWin"}
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `Identifier` | yes | The opportunity ID returned by `CreateOpportunity` |
| `Catalog` | yes | `AWS` or `Sandbox` |
| `ClientToken` | yes | Unique UUID for idempotency |
| `AwsSubmission.InvolvementType` | yes | Level of AWS participation requested |
| `AwsSubmission.Visibility` | yes | What AWS can see |
| `Tags[]` | no | Up to 200 key/value pairs |

## Response (immediate, with `IN_PROGRESS`)

```json
{
  "TaskId": "oit-1234567890abc",
  "TaskArn": "arn:aws:partnercentral:us-east-1:...:task/oit-1234567890abc",
  "TaskStatus": "IN_PROGRESS",
  "StartTime": "2026-04-28T22:30:00Z",
  "OpportunityId": "O123456789012345"
}
```

## Response (when polled and `COMPLETE`)

```json
{
  "TaskId": "oit-1234567890abc",
  "TaskStatus": "COMPLETE",
  "StartTime": "2026-04-28T22:30:00Z",
  "EngagementId": "eng-abcdef1234567g",
  "EngagementInvitationId": "engi-xyza12345bcde",
  "ResourceSnapshotJobId": "job-snapshot123456",
  "OpportunityId": "O123456789012345",
  "OpportunitySubmissionStatus": "SUBMITTED"
}
```

## Failure modes

| Reason code | Meaning |
|---|---|
| `InvitationAccessDenied` | IAM is missing `CreateEngagementInvitation` |
| `EngagementConflict` | An engagement already exists for this opportunity |
| `OpportunityAccessDenied` | IAM can't read the opportunity |
| `OpportunityValidationFailed` | The opportunity payload is incomplete (missing `PrimaryNeedsFromAws`, `Project.ExpectedCustomerSpend`, etc) |
| `ResourceSnapshotJobConflict` | A snapshot job is already in progress |
| `ServiceQuotaExceeded` | Write quota hit |
| `RequestThrottled` | Burst rate exceeded |

## How to poll

The API spec shows the result fields populating once `TaskStatus = COMPLETE`. There's no listed `GetEngagementTask` operation in the API index we captured, so the recommended pattern is:

1. Call `StartEngagementFromOpportunityTask`, store `TaskId` and `OpportunityId`
2. Listen for the `Engagement Created` and `Engagement Invitation Created` EventBridge events with `engagementId` matching what shows up after the task completes (correlation by `OpportunityId` in the event payload)
3. Or use `ListEngagementInvitations` filtered by `OpportunityId` to discover the new invitation ID

In Step Functions, the simplest pattern is:
- `StartEngagement` Lambda task → starts the async task and returns immediately
- A `Wait 30s` state followed by an `EventBridge Wait` (or polling Lambda) until `Engagement Created` event for that opportunity arrives
- Update DynamoDB with the resulting `EngagementId` and `EngagementInvitationId`

## Pre-flight requirements

Before calling this:

- Opportunity must exist (`CreateOpportunity` already called, ID stored)
- At least one solution must be associated (`AssociateOpportunity` with a Solution `S-...` from `ListSolutions`)
- All required fields must be filled (the three manual ACE fields — `DeliveryModels`, `PrimaryNeedsFromAws`, and the Solution association — are the most common reasons this call fails with `OpportunityValidationFailed`)

## Why this matters for this project

This is the call that closes out the submission flow. The partner-side value-add is exactly this step: collect the HubSpot deal, validate the payload, and call `StartEngagementFromOpportunityTask`. By calling it directly we avoid any third-party connector dependency.
