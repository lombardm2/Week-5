# Rollback runbook: staging

Every promotion creates an immutable release and a git tag `staging-<UTC>-<sha7>`.
Rolling back means serving a previous release again. It never means hand-editing tables.

## Decide which path

| Situation | Path | Time |
|---|---|---|
| Bad release is live in staging, consumers affected now | **A: rollback workflow** | minutes |
| Bad change is merged but you can wait for a normal deploy | **B: revert PR** | one gate run |
| GitHub Actions unavailable, or local/staging host access | **C: CLI pointer swap** | seconds |

## A. Rollback workflow (default)

1. Find the last good tag. Names embed a UTC timestamp, so name order is time order:
   `git ls-remote --tags --refs origin 'staging-*' | awk '{print $2}' | sort | tail -5`
2. Trigger the rollback **with git** (the annotated tag message is the reason, and the tag itself
   is the audit record):
   ```
   git fetch origin
   git tag -a rollback/<staging-tag> origin/main -m "INC-0042 accounts fan-out"
   git push origin rollback/<staging-tag>
   ```
   Or from the web: Actions → **rollback-staging** → Run workflow (`release_tag`, `reason`).
   Both routes refuse unknown tags, non-staging tags and blank reasons
   (`scripts/resolve_rollback.sh`).
3. The workflow verifies the tag, re-runs the full gate on the tagged code with the contract
   policy in **warn** mode (the step summary lists what consumers lose relative to `main`),
   then redeploys it as `rollback-<UTC>-of-<tag>` under the `staging` environment.
4. Shares the `deploy-staging` concurrency group with promotion, so a rollback and a promotion
   can never interleave.

## B. Revert PR

`git revert -m 1 <merge-sha>` → open PR → the gate must pass → merge → normal promotion.
Use this to fix `main` after path A. **Path A without path B means the next merge
re-deploys the bad change.**

## C. CLI pointer swap

```
python scripts/promote.py --env staging status
python scripts/promote.py --env staging rollback --reason "INC-0042"            # previous release
python scripts/promote.py --env staging rollback --to <release_id> --reason "…"  # specific release
```

Atomic `CURRENT` swap; no rebuild. Refuses without `--reason` or with an unknown release.
Every action is appended to `history.jsonl` with actor and reason.
A tested drill is in `docs/evidence/04_rollback_drill.log`.

## Contract considerations

If the release you roll back to has an **older contract major or minor version**, consumers
that adopted the newer version lose columns (the warn-mode diff names them). Notify every
team in `info.consumers` of `contracts/accounts.yml` before or immediately after rolling back.

## If a published number was wrong (restatement)

Rolling back fixes what is served next, not what was already sent.

1. Identify the affected window: first bad release (from `history.jsonl` or tags) to rollback time.
2. Rebuild `fct_branch_deposits_daily` for those dates from the good release and diff against
   what was published. `test_mart_reconciles_to_ledger_every_day` gives the per-day delta.
3. Send finance-reporting the corrected figures with the per-branch delta and the root cause
   in one line.
