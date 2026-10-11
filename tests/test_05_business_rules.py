"""
LAYER 5 -- BUSINESS RULES.
Rule: flag any account whose daily balance moves more than 300% day over day.
A handful of flags is a business event (route to Deposit Ops review -- warn, don't block).
A *surge* of flags on one day is a pipeline defect signature (e.g. a cents->dollars unit
change upstream) and blocks the merge.
"""
from checks.lumen_checks import rows, scalar

MAX_DAILY_FLAG_RATE = 0.005


def _independent_spikes(con) -> set[tuple]:
    """Re-derive the rule in Python on integer cents, independent of the SQL model."""
    data = rows(con, """select account_id, balance_date, cast(ledger_balance * 100 as bigint)
                        from stg_daily_balances order by account_id, balance_date""")
    flagged, prev_acct, prev = set(), None, None
    for acct, day, cents in data:
        if acct == prev_acct and prev is not None:
            if (prev == 0 and cents != 0) or (prev != 0 and abs(cents - prev) > 3 * abs(prev)):
                flagged.add((acct, day.isoformat()))
        prev_acct, prev = acct, cents
    return flagged


def test_spike_model_matches_independent_implementation(con):
    model = {(a, d.isoformat()) for a, d in rows(con, "select account_id, balance_date from exceptions_balance_spikes")}
    independent = _independent_spikes(con)
    assert model == independent, f"model-only={sorted(model - independent)[:5]} missed={sorted(independent - model)[:5]}"


def test_planted_spikes_are_flagged_and_boundary_is_not(con, manifest):
    rule = manifest["business_rule_balance_spike"]
    model = {(a, d.isoformat()) for a, d in rows(con, "select account_id, balance_date from exceptions_balance_spikes")}
    expected = {(r["account_id"], r["balance_date"]) for r in rule["expected_flags"]}
    boundary = {(r["account_id"], r["balance_date"]) for r in rule["boundary_not_flagged"]}
    assert expected <= model, f"missed planted spikes: {sorted(expected - model)}"
    assert not (boundary & model), f"exact-300% boundary wrongly flagged: {sorted(boundary & model)}"


def test_no_mass_spike_day(con):
    worst = rows(con, """
        with f as (select balance_date, count(distinct account_id) n from exceptions_balance_spikes group by 1),
             a as (select balance_date, count(distinct account_id) n from stg_daily_balances group by 1)
        select a.balance_date, coalesce(f.n, 0), a.n, coalesce(f.n, 0) / a.n as rate
        from a left join f using (balance_date) order by rate desc limit 1""")[0]
    day, flagged, active, rate = worst
    assert rate <= MAX_DAILY_FLAG_RATE, (
        f"{day}: {flagged}/{active} accounts ({rate:.2%}) moved >300%. That is a pipeline signature "
        f"(unit/scale change, duplicated load, partial prior day), not customer behaviour.")


def test_account_opened_before_first_balance(con):
    bad = scalar(con, """select count(*) from accounts a
                         join (select account_id, min(balance_date) d from stg_daily_balances group by 1) b
                           using (account_id) where a.open_date > b.d""")
    assert bad == 0, f"{bad} accounts have balances before their open_date"
