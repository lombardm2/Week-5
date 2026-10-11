#!/usr/bin/env bash
# Drive the recorded demo on GitHub:
#   1. open a PR that breaks the accounts contract -> checks fail, merge is refused
#   2. push the fix -> checks pass -> merge -> promote-to-staging runs
# Prereqs: gh auth login; repo pushed; scripts/setup_github.sh already run.
set -uo pipefail
BRANCH=feature/branch-region-enrichment
EVID=docs/evidence/github
mkdir -p "$EVID"
pause() { read -r -p $'\n>>> '"$1"$' [enter] '; }

git checkout main && git pull --ff-only
if cmp -s models/marts/10_accounts.sql demo/fixed/10_accounts.sql; then
  echo "main already contains the fix. Push the pre-PR state first:"
  echo "  git push --force origin github-demo-start:main"
  exit 1
fi
git checkout -B "$BRANCH"
cp demo/broken/10_accounts.sql models/marts/10_accounts.sql
cp demo/broken/accounts.yml    contracts/accounts.yml
git commit -am "feat(accounts): add branch region; rename account_status -> status"
git push -u origin "$BRANCH" --force-with-lease
PR_URL=$(gh pr create --base main --head "$BRANCH" \
  --title "feat(accounts): add branch region for regional deposits view" --body-file demo/PR_BODY.md)
echo "Opened $PR_URL"

pause "Watch the checks run (expected: FAIL)"
gh pr checks "$PR_URL" --watch | tee "$EVID/01_broken_checks.txt"
pause "Attempt to merge the red PR (expected: refused by branch protection)"
gh pr merge "$PR_URL" --squash 2>&1 | tee "$EVID/02_merge_refused.txt"

pause "Push the fix"
cp demo/fixed/10_accounts.sql models/marts/10_accounts.sql
cp demo/fixed/accounts.yml    contracts/accounts.yml
git commit -am "fix(accounts): join current branch version only; keep account_status; contract 1.1.0 additive"
git push
sleep 10
gh pr checks "$PR_URL" --watch | tee "$EVID/03_fixed_checks.txt"

pause "Merge the green PR"
gh pr merge "$PR_URL" --squash --delete-branch 2>&1 | tee "$EVID/04_merged.txt"
git checkout main && git pull --ff-only
sleep 10
RUN_ID=$(gh run list --workflow promote-staging.yml --branch main --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status | tee "$EVID/05_promote.txt"
gh release list >/dev/null 2>&1; git fetch --tags && git tag -l 'staging-*' | tail -3
