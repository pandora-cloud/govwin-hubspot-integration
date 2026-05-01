#!/usr/bin/env bash
# Open every issue in .github/seed-issues.yml against the configured repo.
#
# Run AFTER:
#   1. The GitHub repo `github.com/pandora-cloud/govwin-hubspot-integration` exists.
#   2. The GitLab -> GitHub mirror is wired and has propagated at least once.
#   3. `gh auth login` has been run (brew install gh && gh auth login).
#
# Re-runnable: pass `--check` to dry-run (prints what would be opened).
# By default, opens every issue once. After a successful run, delete or
# truncate .github/seed-issues.yml so re-runs do not duplicate.

set -euo pipefail

REPO="${REPO:-pandora-cloud/govwin-hubspot-integration}"
SEED="${SEED:-.github/seed-issues.yml}"
MODE="${1:-create}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not installed. brew install gh && gh auth login." >&2
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "yq not installed. brew install yq." >&2
  exit 1
fi

count=$(yq -r '.issues | length' "$SEED")
echo "Found $count seed issues in $SEED. Target repo: $REPO. Mode: $MODE."
echo

for i in $(seq 0 $((count - 1))); do
  title=$(yq -r ".issues[$i].title" "$SEED")
  labels=$(yq -r ".issues[$i].labels | join(\",\")" "$SEED")
  body=$(yq -r ".issues[$i].body" "$SEED")

  echo "[$((i+1))/$count] $title"
  echo "    labels: $labels"

  if [[ "$MODE" == "--check" ]]; then
    continue
  fi

  url=$(gh issue create \
    --repo "$REPO" \
    --title "$title" \
    --label "$labels" \
    --body "$body")
  echo "    -> $url"
  sleep 1   # polite pause to avoid GitHub rate-limiting on bulk creation
done

echo
echo "Done. Truncate .github/seed-issues.yml so future runs do not duplicate:"
echo "    git rm .github/seed-issues.yml && git commit -m 'chore: seed issues opened'"
