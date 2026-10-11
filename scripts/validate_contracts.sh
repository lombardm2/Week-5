#!/usr/bin/env bash
# Validate every contract in contracts/ against the warehouse and, if a base ref is
# given, against that ref's version of the contract (breaking-change policy).
# Usage: scripts/validate_contracts.sh [BASE_REF] [enforce|warn]
set -uo pipefail
BASE_REF="${1:-}"
MODE="${2:-enforce}"
mkdir -p build/contracts
rc=0
for c in contracts/*.yml; do
  name=$(basename "$c" .yml)
  base_file="build/contracts/base_${name}.yml"
  : > "$base_file"
  if [ -n "$BASE_REF" ] && git cat-file -e "${BASE_REF}:${c}" 2>/dev/null; then
    git show "${BASE_REF}:${c}" > "$base_file"
    echo "Change-policy base: ${BASE_REF}:${c} (version $(grep -m1 '^version:' "$base_file" | awk '{print $2}'))"
  else
    echo "No base for ${c} at '${BASE_REF:-<none>}' -> policy diff skipped"
  fi
  python scripts/validate_contract.py --contract "$c" --base-contract "$base_file" \
    --policy-mode "$MODE" --report "build/contracts/${name}_report.json"
  rc=$(( rc | $? ))
done
exit "$rc"
