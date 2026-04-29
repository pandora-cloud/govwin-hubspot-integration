# Security policy

Pandora Cloud LLC takes security seriously. This project handles credentials for three external systems (Deltek GovWin IQ, HubSpot, AWS Partner Central) and routes federal contracting opportunity data, so secure-by-default is a baseline expectation.

## Supported versions

| Version | Supported |
|---|---|
| v2.x (end-to-end with direct AWS Partner Central API) | Yes |
| v1.x (GovWin to HubSpot only, SaaSify required for ACE) | Security fixes only |
| < v1.0 | No |

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Email <pc@pandoracloud.net> with:

- A description of the issue and its impact
- Reproduction steps or a proof-of-concept (please do not test against systems you don't own)
- Your suggested mitigation if you have one

We aim to acknowledge within three business days and provide an initial assessment within seven. Severity-1 issues (active exploitation, credential exposure, data loss) are prioritized over feature work.

If you do not receive a response within seven business days, escalate by emailing <isi@pandoracloud.net> directly.

## What we treat as in-scope

- Authentication and signature-validation flows (HubSpot `X-HubSpot-Signature-v3`, AWS SigV4, GovWin OAuth2)
- Secret handling (Secrets Manager paths, env var hygiene, log-output redaction)
- DynamoDB key construction and any user-controllable data flowing into URL paths or DynamoDB pks
- IAM policy scoping (especially the `partnercentral:Catalog: Sandbox` condition)
- Webhook receiver hardening (replay window, body-size cap, event-count cap)
- Cross-tenant or cross-deal data leakage in the sync logic

## Known design decisions

- The integration always defaults `ACE_CATALOG=Sandbox`. Production deployments must explicitly opt in.
- The Lambda execution role is scoped per-environment via Terraform variables; production roles should not have Sandbox permissions and vice versa.
- DynamoDB encryption-at-rest with AWS-managed keys is enabled by default.
- No VPC is required; all calls go to AWS service endpoints, GovWin's public API, and HubSpot's public API.

## Things that are explicitly NOT vulnerabilities

- The integration logs request paths, status codes, and identifiers (deal IDs, GovWin opp IDs, AWS opportunity IDs). Free-text deal content is not logged.
- HubSpot webhook subscriptions ship `active: false` by default in the developer-platform project. They must be explicitly activated.
- Default AWS credentials precedence (env vars, profile, instance role). The integration follows boto3 defaults; misconfigured operator credentials are out of scope.
