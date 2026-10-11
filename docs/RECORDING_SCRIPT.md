# Recording script (~12 minutes)

Drive the GitHub portion with `scripts/demo_pr_flow.sh` (it pauses between steps).
Numbers below are from `docs/evidence/`. The generator is seeded, so counts reproduce exactly;
dates shift with the run date.

---

## Scene 1: The ask (0:00–0:45)

**Screen:** README control matrix.

> Last quarter a join fan-out against the branch reference overstated average balances in
> the CFO's deposits packet for eleven days. Nothing errored. Every column had the right type
> and no nulls; there were just more rows than there should have been. This repo turns that
> failure class into a blocked merge. I'll show it blocking a bad PR, then passing the fix.

## Scene 2: The data and the controls (0:45–3:00)

**Screen:** `data/raw/_manifest.json`, then `pytest -q` output by layer.

> The generator plants known defects: orphan branches and customers, null keys, duplicate
> loads, a malformed date, ten balance spikes, and one move of exactly 300% that must *not*
> flag. Nine of the 42 branches carry SCD2 history, so `branch_id` alone isn't unique in the
> reference. That's the trap from Q2.
>
> Layer 0 points every detector at the raw data and requires it to find exactly what was
> planted. A test suite that passes on clean data proves nothing; this proves the controls
> have teeth. Layers 1 to 5 cover schema and types, primary keys, not-nulls, relationships
> and quarantine accounting, and the 300% rule. Layer 6 is the direct control for the
> incident: enrichment must preserve row count, and the CFO mart must tie to the ledger to
> the cent, every day. Layer 7 tests the validator itself.

**Screen:** `contracts/accounts.yml`.

> The contract is the promise to finance, branch ops and regulatory reporting: schema,
> nullability, allowed values, ranges, a 26-hour freshness SLA, and a breaking-change policy.
> Renames, removals, type changes and relaxed constraints need a major version, a migration
> note and sign-off from every consumer. CODEOWNERS enforces the sign-off.

## Scene 3: Branch protection (3:00–3:30)

**Screen:** Settings → Branches → `main`, showing required checks `gate`, `layered-tests`,
`contract-validation`, with "include administrators" enabled.

## Scene 4: The breaking PR (3:30–4:30)

**Screen:** PR diff (`demo/broken/`).

> A plausible change: add region for a regional view. The developer joins `stg_branch_history`
> because that's where region lives, and while they're in there renames `account_status` to
> `status` to match branch ops. They did update the contract, and called it a minor bump.

**Screen:** Checks tab turns red. Then `gh pr merge` → refused by base branch policy.

## Scene 5: Reading the failures (4:30–9:30), the core of the recording

Five checks failed. Before fixing anything, I want to know how many *problems* that is.

**Screen:** `docs/evidence/01_broken_pr_gate.log`, or the job summaries.

### Check 1: `layered-tests › test_primary_key_unique[accounts[account_id]]`

> 954 duplicated `account_id`s in the published table.

**Pipeline health:** The interface no longer means "one row per account." Every consumer
that sums or counts over it is now wrong, silently.

**Symptom vs root cause:** Duplicates are a symptom with at least three candidate causes: a
double-loaded extract, broken dedupe in staging, or a fan-out join in enrichment.

**How I told them apart:**
- *Layer bisection.* In the same run, the PK test on `stg_accounts` passed, and so did the
  Layer 0 duplicate detector on raw. The source and staging are clean, so the defect enters
  between `stg_accounts` and `accounts`. Only one file in the diff sits there: `10_accounts.sql`.
- *Fingerprint.* The failure message prints it: all 954 duplicates sit on the 9 branches
  with SCD2 history, and each account's multiplicity (2) equals its branch's version count
  (2). A double load would scatter duplicates across all branches and show up in raw. This
  pattern can only come from joining history on `branch_id` without `is_current`.

### Check 2: `layered-tests › test_enrichment_preserves_account_cardinality`

> 4,482 rows in, 5,436 rows out: +954.

**Pipeline health:** An enrichment step changed the grain. Enrichment should only add
columns; any row-count change is by definition a join to a non-unique key.

**Symptom vs root cause:** This is the closest statement of the root cause. It names the
step, not just the effect.

**How I told them apart:** The surplus is exactly 954, the same number as Check 1 and the
contract's "954 surplus rows of 5,436." Three independent checks reporting the same number
indicate one cause, not three.

### Check 3: `layered-tests › test_mart_reconciles_to_ledger_every_day`

> 60 of 60 days off. First day: ledger $39.22M, mart $47.43M, +$8.21M (about 21% overstated).

**Pipeline health:** This is the Q2 incident reproduced: the CFO mart no longer ties to the
general ledger. Of all the checks, this one has the most business impact.

**Symptom vs root cause:** Pure surface symptom. The mart's SQL is unchanged in this PR, so
fixing anything in the mart would mask the problem rather than solve it.

**How I told them apart:** The test prints branch-level ratios of mart to ledger: exactly
2.0000 on nine branches, 1.0 on the other 33. Exact integer multiples on a subset of
branches mean rows were duplicated. Bad values or a unit change give non-integer ratios or
hit every branch. The nine branch IDs are the same nine from Check 1.

It also explains why Q2 hid for eleven days. `avg_customer_balance` is sum divided by
`count(distinct customer_id)`. The fan-out doubles the numerator, but the distinct count is
immune, so customer and account counts looked normal while the average inflated. Only a
reconciliation to the ledger catches that.

### Check 4: `contract-validation › data › primary_key.unique`

> 954 duplicated keys (954 surplus rows of 5,436).

**Pipeline health:** The producer is breaking its promise to consumers, not just failing an
internal test. This check runs against the same contract consumers rely on.

**Symptom vs root cause:** Same root cause as Checks 1–3, seen from the consumer's side.
I count it once.

**What passed matters too:** every type, nullability, allowed-value, range, pattern and
freshness check on the contract passed. Fan-out doesn't corrupt any value; it only
multiplies rows. That's why column-level testing alone missed Q2.

### Check 5: `contract-validation › policy › semver.sufficient_bump`

> 1.0.0 → 1.1.0 (minor); changes require: major. BREAKING: `column_removed(account_status)`.

**Pipeline health:** The data pipeline is fine on this point. This is a governance failure:
a breaking interface change is shipping as if it were additive.

**Symptom vs root cause:** This is a *separate, independent* root cause, and the only
failure with no data symptom anywhere in the repo.

**How I told them apart:**
- The data checks on the renamed column passed (`not_null.status`, `allowed_values.status`),
  and the schema test passed, because the developer moved the SQL and the contract together.
  A check of data against the contract can't see this.
- Only the diff against `main`'s contract sees that a column consumers depend on disappeared.
- No in-repo test fails because nothing in this repo reads `account_status`. The harm lands
  outside: the contract's consumer list says finance-reporting filters on it for the CFO
  packet. The contract is how teams outside this repo get a vote.

### Summary on screen

| # | Failing check | Root cause |
|---|---|---|
| 1 | PK uniqueness on `accounts` | **A**: fan-out join to SCD2 history |
| 2 | Enrichment preserves cardinality | **A** |
| 3 | Mart reconciles to ledger | **A** (business-facing symptom) |
| 4 | Contract `primary_key.unique` | **A** (consumer view) |
| 5 | Contract `semver.sufficient_bump` | **B**: unversioned breaking rename |

> Five red checks, two problems. The method: find the lowest layer that fails, check whether
> the numbers match across independent checks, look for exact-multiple fingerprints, and use
> the checks that *passed* to rule causes out. Calibration passed, so the detectors are
> healthy; the business-rule tests passed because they run upstream of the defect, which
> further localizes it.

## Scene 6: The fix (9:30–10:45)

**Screen:** diff `demo/broken` → `demo/fixed`.

> Root cause A: join `stg_branches`, the current-version view that is unique on `branch_id`.
> Root cause B: keep `account_status`. Adding `region` is genuinely additive, so 1.1.0 is right.
> If we did want the rename, that's a 2.0.0 with a dual-publish window and sign-off from all
> three consumer teams, and the validator enforces each of those.

**Screen:** checks turn green (106 tests; 35/35 contract data checks; policy: `column_added`
additive). Merge. *promote-to-staging* run: gate re-runs on the merge commit, promotes, smoke
check passes, tag `staging-…` created.

## Scene 7: Rollback (10:45–11:45)

**Screen:** Actions → *rollback-staging* inputs, then `docs/evidence/04_rollback_drill.log`.

> Rollback is a pointer swap to an immutable, tagged release, re-validated by the same gate.
> It refuses without a reason or an unknown tag, it's serialized with promotions, and in warn
> mode it tells you which columns consumers lose. In this drill, rolling back to 1.0.0 removes
> `region`. Then revert the PR on main so the next merge doesn't redeploy it.

## Scene 8: Close (11:45–12:00)

> The incident class is now a required check: cardinality and reconciliation on every grain,
> a contract consumers can rely on, and a gate that fails closed.

---

## Appendix: honest notes for Q&A

- **Harness flaw found during the build.** The first dry run produced 8 extra failures in
  `test_07` because the validator's unit tests read the live contract file under review. I
  moved them to a frozen fixture (`tests/fixtures/accounts_contract_v1.yml`). Lesson: tests
  of the controls must be hermetic, or every legitimate contract change produces false alarms.
- **Why the spike rule warns rather than blocks.** One account moving 400% is a customer
  event, so it goes to Deposit Ops via the review-queue artifact. Hundreds moving on the same
  day is a pipeline signature, so that blocks.
