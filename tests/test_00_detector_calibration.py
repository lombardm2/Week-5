"""
LAYER 0 -- DETECTOR CALIBRATION (runs against RAW).
A suite that passes on clean data proves nothing. Here we point every detector at the
raw extracts, where the generator planted known defects, and require it to find EXACTLY
the planted set: no misses (recall) and no false alarms (precision).
"""
from checks.lumen_checks import cast_failures, duplicate_keys, rows


def test_detects_duplicate_account_rows(con, manifest):
    found = sorted(r[0] for r in duplicate_keys(con, "raw_accounts", ["account_id"]))
    assert found == manifest["violations"]["raw_accounts"]["duplicate_account_ids"]


def test_detects_orphan_branch_references(con, manifest):
    found = sorted({r[0] for r in rows(con, """
        select a.account_id from raw_accounts a
        where not exists (select 1 from raw_branches b where b.branch_id = a.branch_id)""")})
    assert found == manifest["violations"]["raw_accounts"]["orphan_branch_account_ids"]


def test_detects_orphan_customer_references(con, manifest):
    found = sorted({r[0] for r in rows(con, """
        select a.account_id from raw_accounts a
        where coalesce(a.customer_id, '') <> ''
          and not exists (select 1 from raw_customers c where c.customer_id = a.customer_id)""")})
    assert found == manifest["violations"]["raw_accounts"]["orphan_customer_account_ids"]


def test_detects_null_customer_ids(con, manifest):
    found = sorted({r[0] for r in rows(con, "select account_id from raw_accounts where coalesce(customer_id,'') = ''")})
    assert found == manifest["violations"]["raw_accounts"]["null_customer_account_ids"]


def test_detects_invalid_account_types(con, manifest):
    found = sorted({r[0] for r in rows(con, """select account_id from raw_accounts
        where account_type not in ('CHECKING','SAVINGS','MONEY_MARKET','CD')""")})
    assert found == manifest["violations"]["raw_accounts"]["invalid_account_type_account_ids"]


def test_detects_type_cast_failures(con, manifest):
    found = sorted(r[0] for r in cast_failures(con, "raw_customers", "date_of_birth", "DATE", "customer_id"))
    assert found == manifest["violations"]["raw_customers"]["malformed_dob_customer_ids"]


def test_detects_duplicate_balance_rows(con, manifest):
    found = sorted((r[0], r[1]) for r in duplicate_keys(con, "raw_daily_balances", ["account_id", "balance_date"]))
    planted = sorted((r["account_id"], r["balance_date"]) for r in manifest["violations"]["raw_daily_balances"]["duplicate_rows"])
    assert found == planted


def test_detects_null_balances(con, manifest):
    found = sorted(rows(con, "select account_id, balance_date from raw_daily_balances where coalesce(ledger_balance,'') = ''"))
    planted = sorted((r["account_id"], r["balance_date"]) for r in manifest["violations"]["raw_daily_balances"]["null_balance_rows"])
    assert found == planted


def test_detects_orphan_balance_accounts(con, manifest):
    found = sorted({r[0] for r in rows(con, """select b.account_id from raw_daily_balances b
        where not exists (select 1 from raw_accounts a where a.account_id = b.account_id)""")})
    assert found == manifest["violations"]["raw_daily_balances"]["orphan_account_ids"]


def test_branch_reference_is_a_fanout_hazard(con, manifest):
    """Documents the trap from last quarter: branch_id alone is NOT unique in the reference."""
    dup_branches = sorted(int(r[0]) for r in duplicate_keys(con, "raw_branches", ["branch_id"]))
    assert dup_branches == manifest["reference"]["scd_branch_ids"]
    naive = rows(con, "select count(*) from raw_accounts a join raw_branches b using (branch_id)")[0][0]
    safe = rows(con, "select count(*) from raw_accounts a join raw_branches b using (branch_id) where b.is_current = 'true'")[0][0]
    assert naive > safe, "Naive join should inflate rows; if not, the hazard fixture is broken"
