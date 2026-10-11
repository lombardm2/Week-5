"""LAYER 2 -- PRIMARY-KEY UNIQUENESS (+ SCD2 integrity of the branch reference)."""
import pytest

from checks.lumen_checks import duplicate_keys, fanout_fingerprint, rows, sample

KEYS = [
    ("stg_branch_history", ["branch_id", "valid_from"]),
    ("stg_branches", ["branch_id"]),
    ("stg_customers", ["customer_id"]),
    ("stg_accounts", ["account_id"]),
    ("accounts", ["account_id"]),
    ("stg_daily_balances", ["account_id", "balance_date"]),
    ("exceptions_balance_spikes", ["account_id", "balance_date"]),
    ("fct_branch_deposits_daily", ["branch_id", "balance_date"]),
]


@pytest.mark.parametrize("table,cols", KEYS, ids=[f"{t}[{','.join(c)}]" for t, c in KEYS])
def test_primary_key_unique(con, table, cols):
    dups = duplicate_keys(con, table, cols)
    hint = ""
    if dups and "account_id" in cols and len(cols) == 1:
        hint = "\n  DIAGNOSIS: " + fanout_fingerprint(con, table, "account_id")
    assert not dups, f"{table}: {len(dups)} duplicated keys {cols}; sample: {sample(dups)}{hint}"


def test_exactly_one_current_version_per_branch(con):
    bad = rows(con, """select branch_id, count(*) filter (where is_current) as n_current
                       from stg_branch_history group by branch_id having n_current <> 1""")
    assert not bad, f"branches without exactly one current row: {bad}"


def test_branch_validity_windows_do_not_overlap(con):
    bad = rows(con, """select a.branch_id, a.valid_from, b.valid_from
                       from stg_branch_history a join stg_branch_history b
                         on a.branch_id = b.branch_id and a.valid_from < b.valid_from
                        and a.valid_to >= b.valid_from""")
    assert not bad, f"overlapping SCD2 windows (point-in-time joins would fan out): {bad}"
