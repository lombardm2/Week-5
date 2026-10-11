PY   ?= python
BASE ?= origin/main

.PHONY: install data build test contract gate queues promote rollback status clean
install:  ; $(PY) -m pip install -r requirements.txt
data:     ; $(PY) generator/generate_core_banking.py --out data/raw
build: data ; $(PY) pipeline/build.py
test:     ; $(PY) -m pytest
contract: ; scripts/validate_contracts.sh $(BASE)
queues:   ; $(PY) scripts/export_review_queues.py
gate:     ; scripts/run_gate_local.sh $(BASE)          # same steps as CI; runs both jobs even if one fails
promote:  ; $(PY) scripts/promote.py promote --release-id local-$$(date -u +%Y%m%dT%H%M%SZ)-$$(git rev-parse --short HEAD)
rollback: ; $(PY) scripts/promote.py rollback --reason "$(REASON)" $(if $(TO),--to $(TO),)
status:   ; $(PY) scripts/promote.py status
clean:    ; rm -rf data build .environments .pytest_cache
