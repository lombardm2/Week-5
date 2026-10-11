#!/usr/bin/env bash
# Git-only demo. No gh CLI needed; the browser is used only to open the PR and watch checks.
#
#   1. push a branch that breaks the accounts contract  -> open the PR (link printed)
#   2. checks go red -> `git push` to main is REJECTED by branch protection
#   3. push the fix -> checks go green -> `git push` to main is ACCEPTED (PR shows merged)
#   4. promote-to-staging runs and tags a release
#   5. roll back by pushing a rollback/<staging-tag> git tag
#
# Prereqs: repo pushed from github-demo-start, branch protection set (docs/RUN_ORDER_GIT_ONLY.md).
set -uo pipefail

BRANCH=feature/branch-region-enrichment
EVID=docs/evidence/github
mkdir -p "$EVID"

say()   { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
pause() { printf '\n\033[1;33m>>> %s\033[0m\n' "$1"; read -r -p "    press [enter] to continue "; }

# ---------------------------------------------------------------- prechecks
REMOTE_URL=$(git remote get-url origin 2>/dev/null) || { echo "No 'origin' remote. See docs/RUN_ORDER_GIT_ONLY.md step 3."; exit 1; }
SLUG=$(printf '%s' "$REMOTE_URL" | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
WEB="https://github.com/${SLUG}"

if ! { git checkout -q main && git fetch -q origin && git merge -q --ff-only origin/main; }; then
  echo "Local main can't fast-forward to origin/main. Run: git checkout main && git reset --hard origin/main"
  exit 1
fi
if cmp -s models/marts/10_accounts.sql demo/fixed/10_accounts.sql; then
  echo "main already contains the fix. Push the pre-PR state first:"
  echo "  git push --force origin github-demo-start:main"
  exit 1
fi

# ---------------------------------------------------------------- 1. breaking change
say "Step 1: create the breaking change on ${BRANCH}"
git checkout -q -B "$BRANCH"
cp demo/broken/10_accounts.sql models/marts/10_accounts.sql
cp demo/broken/accounts.yml    contracts/accounts.yml
git --no-pager diff --stat
git commit -qam "feat(accounts): add branch region; rename account_status -> status"
git push -u --force origin "$BRANCH" 2>&1 | tee "$EVID/01_push_broken_branch.txt"

say "Open the pull request in your browser:"
echo "    ${WEB}/compare/main...${BRANCH}?expand=1"
echo "    Title: feat(accounts): add branch region for regional deposits view"
echo "    (body text is in demo/PR_BODY.md) -> click 'Create pull request'"
pause "Wait until the checks on the PR finish and are RED (~3-4 min). If branch protection is not set yet, set it now (RUN_ORDER step 5)."

# ---------------------------------------------------------------- 2. blocked merge
say "Step 2: try to merge the red PR by pushing it to main (expected: REJECTED)"
echo "\$ git push origin ${BRANCH}:main"
if git push origin "${BRANCH}:main" 2>&1 | tee "$EVID/02_merge_blocked.txt"; then
  :
fi
if grep -q "GH006\|protected branch\|Protected branch" "$EVID/02_merge_blocked.txt"; then
  say "Blocked by branch protection, as intended."
else
  echo "!! The push was not rejected. Branch protection is not active: check RUN_ORDER step 5, then re-run."
  exit 1
fi
pause "Narrate the five failing checks now (docs/RECORDING_SCRIPT.md, Scene 5)."

# ---------------------------------------------------------------- 3. fix + merge
say "Step 3: push the fix"
cp demo/fixed/10_accounts.sql models/marts/10_accounts.sql
cp demo/fixed/accounts.yml    contracts/accounts.yml
git --no-pager diff
git commit -qam "fix(accounts): join current branch version only; keep account_status; contract 1.1.0 additive"
git push origin "$BRANCH" 2>&1 | tee "$EVID/03_push_fix.txt"
pause "Wait until all checks on the PR are GREEN (~3-4 min)."

say "Merge: push the green branch to main (expected: ACCEPTED, PR shows 'merged')"
echo "\$ git push origin ${BRANCH}:main"
git push origin "${BRANCH}:main" 2>&1 | tee "$EVID/04_merge_accepted.txt"
if grep -q "GH006\|rejected\|error" "$EVID/04_merge_accepted.txt"; then
  echo "!! Push rejected. If checks are green, the branch rule probably has 'Require a pull request' ticked."
  echo "   Either untick it (RUN_ORDER step 5) or click 'Merge pull request' on the PR page, then continue."
  pause "Continue once main contains the fix."
fi
git checkout -q main && git fetch -q origin && git merge -q --ff-only origin/main
git --no-pager log --oneline --graph -5

# ---------------------------------------------------------------- 4. promotion
say "Step 4: promote-to-staging is running on the merge"
echo "    ${WEB}/actions/workflows/promote-staging.yml"
pause "Wait until promote-to-staging is green (~4-5 min)."
git fetch -q --tags origin
# Read releases from GitHub, not local tags. Names embed a UTC timestamp, so name order = time order.
REMOTE_TAGS=$(git ls-remote --tags --refs origin 'staging-*' | awk '{print $2}' | sed 's#refs/tags/##' | sort)
echo "Staging releases on GitHub (oldest first):"
printf '%s\n' "$REMOTE_TAGS" | sed 's/^/    /' | tee "$EVID/05_staging_tags.txt"

# ---------------------------------------------------------------- 5. rollback
TARGET=$(printf '%s\n' "$REMOTE_TAGS" | tail -2 | head -1)
COUNT=$(printf '%s\n' "$REMOTE_TAGS" | grep -c '^staging-')
if [ "$COUNT" -lt 2 ]; then
  echo "Need two staging tags to demonstrate rollback; found ${COUNT}. Check the Actions tab, then re-run step 5 by hand:"
  echo "  git tag -a rollback/<earlier staging tag> origin/main -m \"INC-0042 rollback drill\""
  echo "  git push origin rollback/<earlier staging tag>"
  exit 0
fi
say "Step 5: roll staging back to the previous release (${TARGET}) with a git tag"
echo "\$ git tag -a rollback/${TARGET} origin/main -m \"INC-0042 rollback drill\""
echo "\$ git push origin rollback/${TARGET}"
pause "Ready to trigger the rollback?"
git tag -a "rollback/${TARGET}" origin/main -m "INC-0042 rollback drill"
git push origin "rollback/${TARGET}" 2>&1 | tee "$EVID/06_rollback_tag_push.txt"
echo "    ${WEB}/actions/workflows/rollback-staging.yml"
say "Done. Show the rollback-staging run summary on camera. Command output is saved in ${EVID}/."
