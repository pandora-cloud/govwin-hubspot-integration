# Security policy

Pandora Cloud takes security seriously. This project handles credentials for three external systems (Deltek GovWin IQ, HubSpot, AWS Partner Central) and routes federal contracting opportunity data, so secure-by-default is a baseline expectation.

## Supported versions

| Version | Supported |
|---|---|
| v2.x (end-to-end with direct AWS Partner Central API) | Yes |
| v1.x (GovWin to HubSpot only; ACE submission added in v2) | Security fixes only |
| < v1.0 | No |

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.** Use one of these channels instead, in order of preference:

1. **GitHub private security advisory** (preferred). [Open one here](https://github.com/pandora-cloud/govwin-hubspot-integration/security/advisories/new). This routes to the maintainers without becoming public.
2. **Encrypted email** to <pc@pandoracloud.net>. Encrypt with our PGP public key:
   - Fingerprint: `59B2414BE40D2BC8F1A67745D1165A8FF46CC177`
   - Public key: `.well-known/security/pandora-cloud-public.asc` in this repo, also published to `keys.openpgp.org`.
3. **Plain-text email** to <pc@pandoracloud.net> if encryption is impractical. We will accept the report but will respond using PGP if your message did not include your own public key.

Include in your report:

- A description of the issue and its impact
- Reproduction steps or a proof-of-concept (do not test against systems you don't own)
- Your suggested mitigation if you have one

### Response SLAs

| Severity | Definition | First response | Fix or mitigation |
|---|---|---|---|
| Critical | Active exploitation; credential or PII disclosure; data loss; ACE submission integrity | 24 hours | 7 calendar days |
| High | Authentication / signature-validation bypass; privilege escalation in IAM; webhook replay defeat | 3 business days | 14 calendar days |
| Medium | Missing rate-limit defenses; secret-handling weaknesses that don't disclose; logging-induced PII leak | 5 business days | 30 calendar days |
| Low | Hardening recommendations; defense-in-depth | 7 business days | Best-effort, often via Renovate / Dependabot |

If you do not receive a response within the first-response window, escalate by emailing <pc@pandoracloud.net> with `[ESCALATION]` in the subject.

## What we treat as in-scope

- Authentication and signature-validation flows (HubSpot `X-HubSpot-Signature-v3`, AWS SigV4, GovWin OAuth2)
- Secret handling (Secrets Manager paths, env var hygiene, log-output redaction)
- DynamoDB key construction and any user-controllable data flowing into URL paths or DynamoDB pks
- IAM policy scoping (especially the `partnercentral:Catalog: Sandbox` condition)
- Webhook receiver hardening (replay window, body-size cap, event-count cap)
- Cross-tenant or cross-deal data leakage in the sync logic

## Known design decisions

- The integration always defaults `ACE_CATALOG=Sandbox`. Production deployments must explicitly opt in.
- The Lambda execution role's IAM policy includes a `partnercentral:Catalog` condition that always pins to the configured catalog. Sandbox deployments cannot reach into production and vice versa, even if code accidentally passes the wrong catalog string.
- DynamoDB encryption-at-rest with AWS-managed keys is enabled by default.
- No VPC is required; all calls go to AWS service endpoints, GovWin's public API, and HubSpot's public API.

## IAM model

The project follows least privilege at every identity boundary. Three identities are involved, each with a documented and version-controlled policy.

| Identity | Used by | When | Policy location |
|---|---|---|---|
| Bootstrap operator | Security team, one-time per environment | One-shot setup | `terraform/bootstrap/policies/bootstrap-operator.json` (S3 state bucket creation + deployer role creation only) |
| Deployer role | `terraform apply` for the main module | Every deploy | Inline policies in `terraform/bootstrap/deployer_role.tf`. Scoped to `${name_prefix}-*` resource ARNs across S3, Lambda, API Gateway, SQS, SNS, DynamoDB, Secrets Manager, EventBridge, Step Functions, IAM, and CloudWatch Logs. |
| Lambda execution role | The deployed Lambdas at runtime | Continuous | `terraform/modules/lambda/main.tf` and `terraform/modules/ace/iam.tf`. Scoped to specific table / queue / secret ARNs. `partnercentral:*` actions use `Resource = "*"` because the Partner Central Selling API does not support resource-level IAM; this is mitigated by the `partnercentral:Catalog` condition that always pins to the configured catalog. |

The day-to-day deployer's personal IAM identity needs only `sts:AssumeRole` on the deployer role's ARN. CloudTrail records every assumption.

### Surviving wildcards in the policies (and why)

| Where | Wildcard | Justification |
|---|---|---|
| Lambda runtime: `partnercentral:*` actions | `Resource = "*"` | Partner Central Selling API does not support resource-level IAM. Mitigated by `partnercentral:Catalog` StringEquals condition pinning to `Sandbox` or `AWS` per deployment. |
| Lambda runtime: CloudWatch Logs | `arn:aws:logs:...:log-group:/aws/lambda/${name_prefix}-*:*` | The trailing `:*` is the AWS-required pattern to allow log-stream creation within the project's log groups. |
| Deployer role: `lambda:*EventSourceMapping` | `arn:aws:lambda:...:event-source-mapping:*` | Event source mapping ARNs are not predictable at policy-write time (they're UUIDs); the resource type itself only exists for Lambda, so this is bounded. |
| Deployer role: `apigateway:*` | `arn:aws:apigateway:...::/apis/*` | API Gateway HTTP API resource-level IAM is incomplete; the closest scoping is to all APIs in the account/region. |
| Deployer role: read-only `sts:GetCallerIdentity` and `ec2:DescribeRegions` | `Resource = "*"` | Both are AWS-required and cannot be scoped. They are read-only and used by Terraform to discover the current account ID and region list. |

No AWS administrator privileges are required at any point. The bootstrap-operator policy is ~30 IAM actions; the deployer policy is ~70 actions across 11 inline policies, all scoped to project-prefix ARNs.

## Things that are explicitly NOT vulnerabilities

- The integration logs request paths, status codes, and identifiers (deal IDs, GovWin opp IDs, AWS opportunity IDs). Free-text deal content is not logged.
- HubSpot webhook subscriptions ship `active: false` by default in the developer-platform project. They must be explicitly activated.
- Default AWS credentials precedence (env vars, profile, instance role). The integration follows boto3 defaults; misconfigured operator credentials are out of scope.
