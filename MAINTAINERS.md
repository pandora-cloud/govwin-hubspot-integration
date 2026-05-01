# Maintainers

This project is maintained by [Pandora Cloud](https://pandoracloud.net), a Woman-Owned Small Business (WOSB), AWS Advanced Tier Partner, and federal contractor.

## Current maintainers

| Name | GitHub | GitLab | Areas | Time zone |
|---|---|---|---|---|
| Isi Lawson | @isi-pandora | @isi-pandora | All; CTO and primary maintainer | US Eastern |
| Kim | @kim-pandora | @kim-pandora | Maintainer | US Eastern |

## Response expectations

- **Bugs and PRs**: 5 business days for first response.
- **Security disclosures** (`SECURITY.md`): 7 calendar days for first response, 30 days for fix or mitigation.
- **GitHub Discussions**: best-effort, no SLA.

If a thread goes more than two weeks without a maintainer reply, ping it once and move on. We'll get back to it.

## Release ownership

Releases are cut by a current maintainer. The process:

1. Conventional commits since the last tag are aggregated into `CHANGELOG.md` automatically by [release-please](https://github.com/googleapis/release-please).
2. The release-please bot opens a PR with the version bump and changelog. A maintainer reviews and merges.
3. Merging the release PR triggers tag creation, GitHub release notes, and the SBOM + SLSA provenance attachments.

## Becoming a maintainer

We're a small project and don't have a formal escalation path. The route is:

1. Open meaningful PRs - bug fixes, well-tested features, documentation that holds up to scrutiny.
2. Help triage issues and answer Discussions questions.
3. After demonstrated sustained contribution (several months, multiple merged PRs), an existing maintainer can propose adding you to `MAINTAINERS.md` and `CODEOWNERS`. Decision requires unanimous consent of current maintainers.

We will not add anyone whose primary affiliation is with a competing CRM-integration product or a paid-CRM-connector vendor.

## Paid support

Pandora Cloud offers paid services around this codebase: deployment, federal compliance review, prioritized feature work, production incident support. Contact <pc@pandoracloud.net>.
