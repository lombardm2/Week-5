#!/usr/bin/env bash
# One-time repo setup: staging environment + branch protection that makes `gate` a
# required check (this is what turns a red check into a blocked merge).
# Usage: scripts/setup_github.sh owner/repo [--solo-demo]
#   --solo-demo  sets required approvals to 0 so a single person can record the demo;
#                use the default (1 approval + CODEOWNERS) for the real repository.
set -euo pipefail
REPO="${1:?usage: setup_github.sh owner/repo [--solo-demo]}"
APPROVALS=1; CODEOWNERS=true
if [ "${2:-}" = "--solo-demo" ]; then APPROVALS=0; CODEOWNERS=false; fi

gh api -X PUT "repos/${REPO}/environments/staging" \
  -F "deployment_branch_policy[protected_branches]=true" \
  -F "deployment_branch_policy[custom_branch_policies]=false" >/dev/null
echo "environment 'staging' ready (main only)"

gh api -X PUT "repos/${REPO}/branches/main/protection" --input - <<JSON
{
  "required_status_checks": {
    "strict": true,
    "checks": [{"context": "gate"}, {"context": "layered-tests"}, {"context": "contract-validation"}]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": ${APPROVALS},
    "require_code_owner_reviews": ${CODEOWNERS},
    "dismiss_stale_reviews": true
  },
  "required_conversation_resolution": true,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "branch protection on main: required checks gate, layered-tests, contract-validation; admins included"
gh api "repos/${REPO}/branches/main/protection/required_status_checks" --jq '.checks[].context'
