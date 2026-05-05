# AI tooling disclosure

This project is built and maintained by humans. AI assistants (currently Claude Code, with occasional Copilot for editor-side completions) are used as productivity tools alongside other developer tooling — IDEs, linters, formatters, language servers. They are **not credited as commit co-authors** because the listed human committer remains accountable for every line that lands in the repository.

We publish this disclosure so federal procurement officers, security reviewers, and downstream forks have an honest answer to the question "was AI involved in writing this code." The shape of that answer matters more than its existence.

## What AI tools are used for

- Mechanical refactors (renames, import sorting, type-annotation upgrades).
- Drafting documentation, commit messages, and PR descriptions for the maintainer to review and edit.
- Test-case scaffolding and parametrization across pre-existing assertion patterns.
- Code review against the `feature-dev:code-reviewer` agent on changes the maintainer has already written.
- Investigating AWS API contract questions against the boto3 service model and AWS-published docs.
- Drafting and reviewing Terraform module structure where conventions are stable.

## What AI tools are NOT used for, without human verification

- **AWS API integration without verification against AWS documentation and live Sandbox testing.** Every AWS Partner Central Selling-API call, every IAM action, every quota assumption is verified against AWS's published reference and tested in the Sandbox catalog before merging. The AI's output is treated as a draft that the maintainer reviews against the source of truth.
- **Security boundaries.** IAM policies, signature validation, secret handling, and the FIPS endpoint enforcement in `src/aws_clients.py` are reviewed line-by-line by the maintainer. The AI does not have authority to relax a security control.
- **Federal compliance decisions.** Mappings to NIST 800-53, CMMC L2, or any federal control framework are written by the maintainer; the AI may suggest framings but does not author the final compliance claim.
- **Merging, deploying, or pushing to protected branches.** AI tools have no agency to merge a PR, push to `main`, apply Terraform to a live AWS account, or run anything that affects external state without an explicit human-issued command at runtime.

## Accountability

The committer named in `git log` (currently Isi Lawson, GPG-signed with key `43B0993A33C72B7055D8F9DAF40A2F21D13A0A0B`) is accountable for every change. If a bug, vulnerability, or incorrect compliance claim ships, the response process in [`SECURITY.md`](SECURITY.md) routes to that human. The AI tool produced no commits; the human produced commits that were drafted with AI assistance.

## Why we don't list AI as a co-author

Three reasons:

1. **Accountability clarity.** A `Co-Authored-By: Claude` trailer divides responsibility between a person and a tool that cannot be held responsible. The human reviewer is on the hook for every line either way; the trailer obscures that.
2. **Federal contracting context.** Our audience is AWS partners doing work in or adjacent to federal systems. Provenance scrutiny is increasingly part of due-diligence questionnaires. We give a clear, written answer here so we never have to give a hedged one verbally.
3. **Tool-vs-author convention.** No mature project lists VS Code, ruff, mypy, or Copilot Workspaces as a co-author. Treating Claude Code differently would imply a different accountability model than we actually operate under.

## Provenance of pre-2026-05-04 commits

Commits made before 2026-05-04 included `Co-Authored-By: Claude Opus 4.6 (1M context)` trailers. On 2026-05-04 those trailers were removed from the public-repository commit history via `git filter-repo` ahead of the public launch, after consideration of how the audience reads such trailers (see [GitHub issue #22](https://github.com/pandora-cloud/govwin-hubspot-integration/issues/22) for the rationale). The actual code, code review, and accountability model for those commits is unchanged: the human committer reviewed every line, validated every AWS API call, and tested the result in Sandbox.

This file IS the audit trail. Future commits use the framing in this document — AI as a productivity tool, the human as accountable.
