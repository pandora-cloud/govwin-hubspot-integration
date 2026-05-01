## Summary

What this PR does, in 1-3 sentences. Lead with the *why*.

## Related issues

Closes #
References #

## Test plan

- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] `.venv/bin/mypy src/` passes
- [ ] Terraform changes validated with `terraform fmt -recursive` and `terraform validate`
- [ ] Documentation in `docs/` updated alongside the code change
- [ ] New behavior covered by tests in `tests/unit/`

## Risk and rollback

- Blast radius if this goes wrong:
- How to roll back (revert commit / `terraform apply` of prior tag / manual cleanup):

## Checklist

- [ ] No secrets, account IDs, or internal-only paths in committed code
- [ ] No new paid dependencies
- [ ] Commit message explains the *why*, not the *what*
- [ ] If touching the ACE submission path, sandbox smoke matrix re-run (see `docs/testing-in-your-account.md`)
- [ ] If touching boto3 client construction, FIPS endpoint resolution still verifies via `PYTHONPATH=. .venv/bin/python scripts/verify_fips.py`
- [ ] No `boto3.client(...)` direct calls added (use `src.aws_clients.make_client` so FIPS + region pinning stay enforced)
