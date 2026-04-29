# AWS Partner Central Selling API best practices

> Snapshot from https://docs.aws.amazon.com/partner-central/latest/selling-api/best-practices.html captured 2026-04-28.

## 1. Idempotency is mandatory

Every event handler MUST tolerate duplicate deliveries. EventBridge is at-least-once. Two strategies:

- **Dedup by event id** in DynamoDB (TTL 24h is fine; AWS won't redeliver after that)
- **Idempotent business logic** (e.g. `UpsertHubSpotDealByGovwinId` is naturally idempotent because HubSpot's batch upsert keys on `govwin_id`)

This project uses the second pattern wherever possible and the first for the few places where it isn't (e.g. SNS notification triggers).

## 2. Optimistic locking on every update

Every `UpdateOpportunity` call must include `LastModifiedDate` matching the current AWS-side value. If two paths try to update the same opportunity concurrently, one wins and the other gets `ConflictException`.

The recovery pattern:

```python
def update_with_retry(client, opportunity_id, updates, max_attempts=3):
    for attempt in range(max_attempts):
        opp = client.get_opportunity(Identifier=opportunity_id, Catalog=CATALOG)
        try:
            return client.update_opportunity(
                Identifier=opportunity_id,
                Catalog=CATALOG,
                LastModifiedDate=opp["LastModifiedDate"],
                **updates,
            )
        except client.exceptions.ConflictException:
            if attempt == max_attempts - 1:
                raise
            continue  # someone else just updated; refetch and retry
```

## 3. Don't `GetOpportunity` per event — batch

When 50 EventBridge events arrive in a burst (e.g. an AWS bulk update hits us), don't fire 50 sequential `GetOpportunity` calls. Instead:

1. Buffer 10-30 seconds of events in SQS or Lambda batching
2. Build a unique set of opportunity IDs
3. Run one `ListOpportunities` with `AfterLastModifiedDate` to fetch the changed set in one call

This is what we already do in `src/sync/dedup.py` for the GovWin side; the same pattern applies for AWS.

## 4. Two valid sync strategies

Per the docs, partners can choose:

| Strategy | Pros | Cons | When |
|---|---|---|---|
| **Event-driven** (recommended) | Real-time, low API quota burn | More wiring (EventBridge rules, Lambda) | If you already have AWS-hosted infrastructure (we do) |
| **Polling via ListOpportunities** | Simpler, no EventBridge rules | Higher latency, eats daily quota | If you're on-prem or quota isn't a concern |

This project uses event-driven for inbound (AWS → HubSpot) and HubSpot webhooks for outbound (HubSpot → AWS).

## 5. Sandbox first, always

Every change to the ACE submission code path runs through sandbox tests before it touches production. The IAM policy condition `partnercentral:Catalog: Sandbox` enforces this for dev environments — even if code accidentally passes `Catalog: AWS`, the API rejects with `AccessDeniedException`.

## 6. ClientToken UUIDs

Never reuse a `ClientToken`. Generate a UUID per logical operation. For replays after a Lambda timeout, persist the ClientToken in DynamoDB before the call so the retry uses the same one (correctly recovering from a partial failure).

## 7. Tag everything

The `Tags` field on `CreateOpportunity` and `StartEngagementFromOpportunityTask` accepts up to 200 key/value pairs. Use this for:

- `Source: GovWin` (so AWS can identify cross-CRM origin)
- `GovWinOppId: OPP263150` (for cross-reference)
- `PandoraEnv: prod` (for ops debugging)
- `IntegrationVersion: v1.0.0` (for feature toggling later)

Tags don't count against the field-validation limits and provide free observability.

## 8. EventBridge event dedup window

AWS's at-least-once guarantee means you should consider the same event id valid for at least 24 hours. Set a DynamoDB TTL of 86400 seconds on dedup keys.

## 9. Do not call `GetOpportunity` for every webhook event

If a HubSpot deal changes and we want to sync to AWS, we already have the deal payload in the webhook. Don't add a `GetOpportunity` round-trip just to get the `LastModifiedDate` — instead, store the most-recent `LastModifiedDate` in DynamoDB after each ACE call, and use that as the optimistic-lock value. Only re-fetch on `ConflictException`.

## 10. Document the three manual fields prominently

`PrimaryNeedsFromAws`, `Project.DeliveryModels`, and the Solution association (via `AssociateOpportunity`) cannot be auto-populated from GovWin data. They must come from the BD team in HubSpot. The README must call this out clearly so users don't expect a fully-automated flow.
