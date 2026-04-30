# Contributing

Thanks for considering a contribution. This project is an open-source pipeline from Deltek GovWin IQ to AWS Partner Central via HubSpot CRM, maintained by Pandora Cloud LLC.

## Ways to contribute

- **Bug reports.** Open a GitHub issue with the bug-report template. Logs, the relevant config (with secrets redacted), and reproduction steps are the most helpful inputs.
- **Feature requests.** Use the feature-request template. We prioritize requests that reflect a real federal AWS partner workflow over hypothetical extensions.
- **Pull requests.** See below.

## Pull requests

1. Fork the repo and create a topic branch from `main` (e.g. `feature/add-FOO`, `fix/BAR-edge-case`).
2. Match existing code style:
   - Python: ruff for lint, mypy for types, pytest for tests. `make lint` and `make test` must pass.
   - Terraform: `terraform fmt -recursive` and `terraform validate` must pass.
3. Add tests. Every behavior change should add or update a unit test. Tests live under `tests/unit/`.
4. Keep commits focused and descriptive. The first line of each commit message should explain the *why*, not the *what*.
5. Update documentation alongside code. The docs in `docs/` are part of the deliverable.
6. Open a PR using the template. Include a short summary, rationale, and test plan.

## What we will likely not merge

- Changes that introduce a paid dependency. The point of this project is end-to-end OSS.
- Tight coupling to Pandora Cloud's federal AWS practice (it should remain general-purpose).
- New features that aren't accompanied by tests.
- Style-only refactors that touch unrelated code.

## Response time

This is a side-of-desk project for Pandora Cloud. We aim to respond to issues and PRs within five business days. If a thread goes longer than two weeks without a maintainer reply, ping it once and move on; we'll get to it.

## Paid support

If you need a faster turnaround, deployment help, federal compliance review, or feature work prioritized, Pandora Cloud offers paid services around this codebase. Reach out at <pc@pandoracloud.net>.

## License

By contributing, you agree that your contributions are licensed under the same MIT license as the project.
