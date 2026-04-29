# AWS Partner Central Selling API quotas

> Snapshot from https://docs.aws.amazon.com/partner-central/latest/selling-api/quotas.html captured 2026-04-28.

## Per-account API rate limits

| Bucket | Operations | Burst | Daily | Adjustable? |
|---|---|---|---|---|
| **Read** | `GetOpportunity`, `GetAwsOpportunitySummary`, `ListOpportunities`, `ListSolutions`, `GetEngagementInvitation`, `ListEngagementInvitations` | 10/sec | 100,000/24h | Yes (Service Quotas console) |
| **Write** | `CreateOpportunity`, `UpdateOpportunity`, `AssociateOpportunity`, `DisassociateOpportunity`, `RejectEngagementInvitation`, `AssignOpportunity`, `StartEngagementFromOpportunityTask`, `StartEngagementByAcceptingInvitationTask` | 1/sec | 10,000/24h | Yes (Service Quotas console) |

Quotas are rolling 24h windows, not calendar days.

## Per-opportunity association limits

| Resource type | Max associated per opportunity |
|---|---|
| AWS products | 20 |
| Partner solutions | 10 |
| AWS Marketplace private offers | 1 |

## Throttling behavior

Exceeded quotas return `ThrottlingException` (HTTP 400). The standard pattern is exponential backoff via `tenacity` (already used in this project for HubSpot and GovWin clients — same approach applies here).

## Headroom analysis for this project

At Pandora's current scale (~11 marked opportunities, hourly sync) we use roughly:

- 11 read calls per sync cycle (HubSpot deal lookup + ACE state check) = 264/day
- 1-3 write calls per sync per changed opp = ~50-100/day worst case

Both are < 0.5% of the daily quotas. Safe by orders of magnitude.

For a hypothetical OSS user syncing 1,000+ opportunities/hour, the **write quota becomes a real constraint** — at 1/sec they could only push 3,600/hour. Would need `Step Functions Map state maxConcurrency=1` and a ServiceQuotas request to AWS for an increase.

## Recommended client-side guards

1. Use `tenacity` exponential backoff on `ThrottlingException`
2. Add a token-bucket rate limiter analogous to `src/govwin/rate_limiter.py`, configured for 1 write/sec or 10 reads/sec
3. For batch operations, prefer event-driven sync over polling to minimize daily-quota burn (per AWS best practices)
