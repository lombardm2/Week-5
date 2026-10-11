#!/usr/bin/env bash
# Run exactly what the PR gate runs in CI, locally. Usage: scripts/run_gate_local.sh [BASE_REF]
set -uo pipefail
BASE_REF="${1:-origin/main}"
echo "================ DATA-QUALITY GATE (base: ${BASE_REF}) ================"
python generator/generate_core_banking.py --out data/raw || exit 1
python pipeline/build.py || { echo "GATE: FAIL (build)"; exit 1; }
echo; echo "---------------- job: layered-tests ----------------"
python -m pytest --junitxml=build/junit.xml; T=$?
python scripts/export_review_queues.py >/dev/null
echo; echo "---------------- job: contract-validation ----------------"
scripts/validate_contracts.sh "$BASE_REF"; C=$?
echo; echo "================ GATE SUMMARY ================"
printf "layered-tests        %s (exit %s)\n" "$([ $T -eq 0 ] && echo PASS || echo FAIL)" "$T"
printf "contract-validation  %s (exit %s)\n" "$([ $C -eq 0 ] && echo PASS || echo FAIL)" "$C"
if [ $T -eq 0 ] && [ $C -eq 0 ]; then echo "gate                 PASS -> mergeable"; exit 0; fi
echo "gate                 FAIL -> merge blocked"; exit 1
