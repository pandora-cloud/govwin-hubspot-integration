# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Future entries are generated automatically by [release-please](https://github.com/googleapis/release-please) from conventional commit messages on `main`.

## [2.2.0](https://github.com/pandora-cloud/govwin-hubspot-integration/compare/v2.1.0...v2.2.0) (2026-05-05)


### Features

* **ace:** explicit HubSpot lifecyclestage -&gt; ACE LifeCycle.Stage table ([dbd9eec](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/dbd9eecd7ce1f45b7b4b6d9bd2cd89236f6de9e5)), closes [#7](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/7)
* **ace:** parameterize ExpectedCustomerSpend.TargetCompany ([05155c9](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/05155c9e95a179a8a514d9ea3b1a437ab329421f))
* **security:** enforce FIPS endpoints and pin partnercentral-selling to us-east-1 ([010154b](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/010154bcc53e01555af383265ab0d61b2639faa5))
* **setup_hubspot_webhooks:** add dryRun mode for config-change validation ([831d5a3](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/831d5a3f869374f0880e72f3bbe1c1a759a5f48c)), closes [#2](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/2)


### Bug Fixes

* **ace:** always emit Marketing.Source on UpdateOpportunity payloads ([8f51f42](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/8f51f42ef46b482c82431165cd63ac6832d92695)), closes [#19](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/19)


### Documentation

* address audit blockers + merge testing docs + write operations runbook ([cc14bbe](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/cc14bbe86bc934b5b5ac31337f6a05998d8af6f3))
* AI tooling disclosure (AI_USE.md) ([b437b9c](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/b437b9c6f875c017196555a929936891d115b57a))
* **ai_use:** correct cross-link to discussion issue [#22](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/22) ([120357b](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/120357b4be1b082baee3e05d3140d004ccb63de6))
* extended HubSpot-to-ACE field mapping matrix ([33e6b49](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/33e6b491ba223ab483db8cdd69345109e512f256))
* field-mapping reference scaffold (GovWin -&gt; HubSpot -&gt; ACE) ([9d8b4d5](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/9d8b4d5b157d02667b6068e9cf0f3fb3ec080783))


### CI / Build

* add fips job + commit-signing setup script + readme anchor fix ([7639b01](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/7639b01359d81d9579b2749481dcdb255dbdfd64))
* drop duplicate --fail from trufflehog extra_args (action already passes it) ([7efad69](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/7efad692f06dc8688107e507c1ca31104fe8839e))
* **release-please:** repair workflow + add config + bump pyproject version to 2.1.0 ([e5a5614](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/e5a5614a2bfbebd64e37e18a43cd61d3aa262190))
* renovate auto-labels per ecosystem (terraform / python / actions / docker) ([b868f8c](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/b868f8c817b919fac924b0f421a093d83f9e977d)), closes [#8](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/8)
* replace gitleaks-action with trufflehog for secret scanning ([39dd677](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/39dd6775c39e817b6bac3e9a7646e77223331def))
* supply-chain workflows + pre-commit + renovate + dependabot ([ce21948](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/ce2194815e3c3b00ca50736d39264bb5b941dc06))


### Tests

* **ace:** doctest the _split_csv helper and wire doctest runner into pytest ([9257d8d](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/9257d8d9386c54321a28766dd25bf8bcd07805fc)), closes [#4](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/4)
* hubspot signature fixture for offline development ([7c4cf55](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/7c4cf559dd214eace53958d91a28b967456e0cdc)), closes [#9](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/9)
* **mapping:** lock in NAICS 541330 -&gt; Professional Services routing ([6552d69](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/6552d693e5e433c271433f470fa8a56216310c70)), closes [#1](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/1)
* scripts/fault_inject.py exercises DLQ + webhook + EventBridge + SNS paths ([04d69ac](https://github.com/pandora-cloud/govwin-hubspot-integration/commit/04d69acc913b1c476be24efa27141bb0e8aed023))

## [Unreleased]

### Added
- Apache License, Version 2.0 (replaces MIT) with explicit patent grant.
- `ace_partner_company_name` Terraform variable + `ACE_PARTNER_COMPANY_NAME` env var. Sets `ExpectedCustomerSpend.TargetCompany` on every AWS Partner Central submission. Default `"Partner Company"` is harmless in Sandbox; production must override per deployment.
- `src/aws_clients.py`: centralized boto3 client construction with FIPS endpoint enforcement and us-east-1 pinning for `partnercentral-selling`. All call sites refactored.
- `scripts/verify_fips.py`: CI-runnable check that every AWS service we use resolves to a FIPS endpoint.
- FIPS endpoints active in production: `AWS_USE_FIPS_ENDPOINT=true` on every Lambda, `use_fips_endpoint = true` on the Terraform AWS provider. Tests and LocalStack opt out via the same env var because moto / LocalStack do not implement FIPS-suffixed hostnames.
- OSS scaffolding: GitHub issue forms (bug, feature) + config.yml routing security/help/paid-support, MAINTAINERS.md, SUPPORT.md, CODEOWNERS, FUNDING.yml, SECURITY-INSIGHTS.yml, .editorconfig, .pre-commit-config.yaml, renovate.json, .github/dependabot.yml.
- Supply-chain workflows: CodeQL (security-extended + security-and-quality), OpenSSF Scorecard (badge gated until first-run review), CycloneDX SBOM on release, SLSA provenance on release.
- `scripts/generate_security_pgp.sh` + `.well-known/security/` for encrypted vulnerability disclosure.
- ACE-specific troubleshooting table in the deployment guide (signature mismatch, ConflictException, ValidationException, ResourceNotFoundException, ThrottlingException).
- Step 9b.i in the deployment guide: how to retrieve numeric HubSpot pipeline-stage IDs for `ace_trigger_stages`.
- Option A in step 9d: invoke the `setup_hubspot_webhooks` Lambda to activate webhook subscriptions instead of editing `webhooks-hsmeta.json` by hand.

### Changed
- LocalStack pinned to `localstack/localstack:3.8` (community edition). The `:latest` tag began requiring a paid auth token in mid-2026.
- `make local-test` now runs only `tests/integration/`; the unit tests use moto and should not be run against LocalStack.
- `src/ace/client.py` partnercentral-selling client is now hard-pinned to us-east-1, regardless of the operator-configured `aws_region`. This is an AWS-side endpoint constraint; non-us-east-1 deployments previously failed silently.
- Documentation merged: `docs/testing.md` consolidated into `docs/testing-in-your-account.md`. The merged doc is the single canonical place for the test pyramid + smoke matrices + production rollout reference.
- README + deployment guide: stale Step Functions references replaced with `aws lambda invoke` of the orchestrator (the v2.1 architecture used Lambda + SQS, not Step Functions).
- README + deployment guide Terraform-version requirement aligned at `>= 1.11`.
- README configuration table: added `ace_partner_company_name`, `ace_default_solution_id`, `ace_trigger_stages`. Default `sync_schedule` corrected to `rate(1 hour)`.
- `hubspot-app/src/app/webhooks/webhooks-hsmeta.json`: every subscription reset to `"active": false` so first `hs project upload` does not flood a placeholder URL.
- Repository scrubbed of maintainer-specific identifiers in places where the OSS audience would otherwise inherit them: AWS account IDs, real Solution IDs, real API gateway hostnames, contact emails, and "Pandora-only" prose all replaced with placeholders, generic phrasing, or parameterized config.

### Fixed
- `src/ace/client.py` previously used `config.aws.region` for the partnercentral-selling boto3 client, which would 404 on any deployment configured to a region other than us-east-1. Now hard-coded to `us-east-1` via `make_client`.
- `tests/integration/test_localstack_state.py` constructed `AppConfig` without the required `ace=` argument; pre-existing bug, surfaced when LocalStack was finally runnable.

## [v2.1.0] - 2026-04-30

### Added
- X-Ray Active tracing on every Lambda for end-to-end observability.
- CloudWatch alarms on DLQ depth, orchestrator/worker error counts, ACE submission failure counts.
- IAM bootstrap module (`terraform/bootstrap/`) with MFA-gated deployer role and a separate one-time bootstrap-operator policy.
- Sandbox MFA escape hatch (`require_mfa_to_assume_deployer = false` + `acknowledge_no_mfa_for_sandbox_only = true`) with a mandatory expiry date.

### Changed
- **Architecture**: replaced the v2.0 Step Functions chain with EventBridge Scheduler + SQS fan-out + reserved-concurrency-governed Lambdas. Removes the 256KB inter-state payload limit and lets each opportunity batch retry independently.
- ACE submission path now atomically reserves ClientTokens in DynamoDB via conditional writes; concurrent SQS retries cannot mint duplicate ACE opportunities.

## [v2.0.0] - 2026-04-28

### Added
- HubSpot to AWS Partner Central submission half: `submit_to_ace`, `update_in_ace`, `handle_ace_event`, `hubspot_webhook_receiver`, `setup_hubspot_webhooks` Lambdas.
- AWS Partner Central Selling API direct integration (`src/ace/`) replacing the prior dependency on a paid third-party connector.
- HubSpot developer-platform 2025.2+ webhook app (`hubspot-app/`).
- Three-call submission flow: `CreateOpportunity` -> `AssociateOpportunity` -> `StartEngagementFromOpportunityTask`.
- Optimistic locking on `UpdateOpportunity` via `LastModifiedDate` with `ConflictException` retry.
- EventBridge subscription on `aws.partnercentral-selling` to mirror AWS-side state changes back to HubSpot.
- 11-scenario sandbox smoke matrix and `scripts/sandbox_smoke.py` automation for scenarios 1-10.
- HubSpot `govwin_ace_*` BD-editable property surface for the three ACE-required fields and supporting marketing/use-case context.

### Changed
- ACE catalog defaults to `Sandbox`. Production deployments must explicitly set `ace_catalog = "AWS"`. IAM policy adds a `partnercentral:Catalog: Sandbox` condition when in Sandbox mode.

## [v1.0.0] - 2026-04-08

### Added
- GovWin to HubSpot sync: hourly Step Function (in v1; superseded by v2.1's EventBridge Scheduler + Lambda + SQS).
- GovWin WSAPI V3 client with OAuth2, rate limiting (4,000/hr), and discovery modes (marked / saved-search / bookmarked / date-range).
- HubSpot CRM v3 API client with batch upsert, custom properties (`govwin_*`), pipeline mapping, and contact/company associations.
- DynamoDB-backed sync state (cursors, opportunity update dates, entity mappings).
- 130 unit tests including production-data quirk regression tests.
- Pre-deployment validation script (`scripts/validate.py`).
- Dry-run script (`scripts/dry_run.py`).
- LocalStack integration test suite.

[Unreleased]: https://github.com/pandora-cloud/govwin-hubspot-integration/compare/v2.1.0...HEAD
[v2.1.0]: https://github.com/pandora-cloud/govwin-hubspot-integration/compare/v2.0.0...v2.1.0
[v2.0.0]: https://github.com/pandora-cloud/govwin-hubspot-integration/compare/v1.0.0...v2.0.0
[v1.0.0]: https://github.com/pandora-cloud/govwin-hubspot-integration/releases/tag/v1.0.0
