# lumen-deposits-controls

Automated controls that stop the Q2 deposits-packet failure class (silent join fan-out
against the SCD2 branch reference) from reaching production, and a gate that blocks the
merge when they fail.

```
make install && make gate        # same steps as CI, ~10 seconds
```

## What runs on every pull request

| Job (required check) | What it does | Exit on failure |
|---|---|---|
| `layered-tests` | Generates the synthetic core-banking data, builds the warehouse, runs 106 tests in 8 layers | pytest non-zero |
| `contract-validation` | Validates `contracts/*.yml`: structure, data conformance, breaking-change policy vs the PR's base branch | bitmask: 1 data, 2 policy, 4 malformed |
| `gate` | Fails closed unless both jobs succeeded. This is the check branch protection requires | 1 |

On merge to `main`, `promote-to-staging` re-runs the identical gate on the merge commit,
promotes an immutable release, smoke-checks it against the contract, and tags it
(`staging-<UTC>-<sha>`). Tags are rollback targets. See [docs/ROLLBACK.md](docs/ROLLBACK.md).

## Control matrix

| Failure class | Control | Where |
|---|---|---|
| **Join fan-out (the Q2 incident)** | Enrichment must preserve row count; mart must tie to the ledger to the cent, every day; PK uniqueness on every published grain; SCD2 integrity (one current row, no overlapping windows); failure message prints a fan-out fingerprint | `test_06`, `test_02`, `checks/lumen_checks.py::fanout_fingerprint` |
| Detectors that silently stopped working | Every detector is run against raw data with planted defects and must find exactly the planted set | `test_00` |
| Schema / type drift | Ordered column+type match for every table; published table checked against the contract; zero cast failures on keys and measures; tolerated attribute cast failures must be logged | `test_01`, contract `type.*` |
| Duplicate keys | PK uniqueness on 8 grains | `test_02`, contract `primary_key.*` |
| Missing values | Not-null on internal tables; for `accounts`, nullability is read from the contract | `test_03` |
| Referential breaks | 7 FK relationships; every raw record is staged or quarantined (none lost); quarantine rate ≤ 2% | `test_04` |
| Balance moves > 300% day over day | Flagged to `exceptions_balance_spikes` (review queue, not a blocker); SQL rule cross-checked against an independent Python implementation in integer cents; exact-300% boundary must not flag; > 0.5% of accounts flagged on one day blocks (pipeline signature, e.g. a cents/dollars change) | `test_05`, `models/marts/20_*.sql` |
| Unversioned breaking change to the interface | Contract diff vs base: removed/renamed/retyped columns, relaxed nullability, expanded enums, widened ranges, PK change, relaxed freshness → MAJOR bump + migration note + sign-off from every consumer | `scripts/validate_contract.py`, CODEOWNERS |
| Stale data | Freshness SLA on `_loaded_at`: warn > 24h, fail > 26h | contract `freshness` |
| A broken validator | Validator unit-tested for every change class and for non-zero exit on bad and stale data | `test_07` |

## Layout

```
generator/generate_core_banking.py   42 branches (9 with SCD2 history), 3,000 customers, 4,500 accounts,
                                     60 days of balances; planted defects recorded in data/raw/_manifest.json
models/staging/                      typed, deduped; key failures quarantined with reason codes
models/marts/10_accounts.sql         PUBLISHED INTERFACE (governed by contracts/accounts.yml)
models/marts/20_*.sql, 30_*.sql      spike exceptions; CFO branch deposits mart
contracts/accounts.yml               producer-consumer contract (+ _meta/ JSON Schema)
scripts/validate_contract.py         contract validator (exit non-zero on violation)
scripts/promote.py                   immutable releases + atomic pointer swap; rollback; audit log
tests/                               layers 00–07
.github/workflows/                   pr-gate (reusable), promote-staging, rollback-staging (git tag or web)
demo/                                the deliberately broken PR and its fix
docs/evidence/                       captured gate output for every step of the demo
docs/RECORDING_SCRIPT.md             walkthrough + per-check root-cause narration
```

## Running the demo on GitHub (git only)

Follow **[docs/RUN_ORDER_GIT_ONLY.md](docs/RUN_ORDER_GIT_ONLY.md)**. In short: create an empty
public repo on github.com, `git push origin github-demo-start:main`, then run
`bash scripts/demo_git_only.sh`. It opens the breaking PR, shows `git push` to `main` being
**rejected** by the gate, pushes the fix, shows the same push **accepted**, and triggers the
rollback by pushing a `rollback/<staging-tag>` git tag.

`main` in this local repo already contains a dry-run merge (see `docs/evidence/`);
`github-demo-start` is the same code before PR #1, which is what the live demo needs.
If you do have the GitHub CLI, `scripts/setup_github.sh` and `scripts/demo_pr_flow.sh` automate
the same steps.

## Scope notes

- **Staging target.** `scripts/promote.py` ships a filesystem adapter so promotion and rollback
  run end to end locally and in CI. On GitHub-hosted runners that directory is ephemeral, so the
  durable records are the release tag and the 90-day release artifact. For the production
  warehouse, keep the three verbs and swap the adapter (Snowflake `ALTER SCHEMA … SWAP WITH`,
  BigQuery view repoint, Postgres view replace in one transaction).
- **Allowed values** for `account_type` are enforced by the contract on output and duplicated in
  the staging quarantine rule. If they drift apart, the contract check fails, which is the intent.
