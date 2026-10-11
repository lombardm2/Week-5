"""
LAYER 4 -- REFERENTIAL RELATIONSHIPS + QUARANTINE ACCOUNTING.
Quarantine is a control, not a trash can: every raw record must be accounted for as
either staged or quarantined, and quarantine volume is bounded.
"""
import pytest

from checks.lumen_checks import orphans, rows, sample, scalar

MAX_QUARANTINE_RATE = 0.02

RELATIONSHIPS = [
    ("stg_accounts", "customer_id", "stg_customers", "customer_id"),
    ("stg_accounts", "branch_id", "stg_branches", "branch_id"),
    ("accounts", "customer_id", "stg_customers", "customer_id"),
    ("accounts", "branch_id", "stg_branches", "branch_id"),
    ("stg_daily_balances", "account_id", "accounts", "account_id"),
    ("exceptions_balance_spikes", "account_id", "accounts", "account_id"),
    ("fct_branch_deposits_daily", "branch_id", "stg_branches", "branch_id"),
]


@pytest.mark.parametrize("child,ccol,parent,pcol", RELATIONSHIPS,
                         ids=[f"{c}.{cc}->{p}.{pc}" for c, cc, p, pc in RELATIONSHIPS])
def test_foreign_key(con, child, ccol, parent, pcol):
    bad = orphans(con, child, ccol, parent, pcol)
    assert not bad, f"{len(bad)} orphan {child}.{ccol} values not in {parent}.{pcol}: {sample(bad)}"


def test_every_raw_account_is_staged_or_quarantined(con):
    raw = scalar(con, "select count(distinct account_id) from raw_accounts")
    staged = scalar(con, "select count(*) from stg_accounts")
    quarantined = scalar(con, "select count(*) from quarantine_accounts")
    overlap = scalar(con, "select count(*) from stg_accounts s join quarantine_accounts q using (account_id)")
    assert overlap == 0, f"{overlap} accounts are both staged and quarantined"
    assert raw == staged + quarantined, f"raw={raw} != staged={staged} + quarantined={quarantined} (records lost)"


def test_every_raw_balance_row_is_staged_or_quarantined(con):
    raw = scalar(con, "select count(*) from raw_daily_balances")
    staged = scalar(con, "select count(*) from stg_daily_balances")
    quarantined = scalar(con, "select count(*) from quarantine_daily_balances")
    assert raw == staged + quarantined, f"raw={raw} != staged={staged} + quarantined={quarantined}"


@pytest.mark.parametrize("raw_sql,q_table", [
    ("select count(distinct account_id) from raw_accounts", "quarantine_accounts"),
    ("select count(*) from raw_daily_balances", "quarantine_daily_balances"),
])
def test_quarantine_rate_bounded(con, raw_sql, q_table):
    raw = scalar(con, raw_sql)
    q = scalar(con, f"select count(*) from {q_table}")
    reasons = rows(con, f"select quarantine_reason, count(*) from {q_table} group by 1 order by 2 desc")
    assert q / raw <= MAX_QUARANTINE_RATE, (
        f"{q_table}: {q}/{raw} = {q / raw:.2%} exceeds {MAX_QUARANTINE_RATE:.0%}. "
        f"A quarantine surge usually means an upstream key/schema change, not bad records. by reason: {reasons}")
