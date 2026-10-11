"""LAYER 3 -- NOT-NULL CONSTRAINTS. For the published table, nullability comes from the contract."""
import pytest
import yaml

from checks.lumen_checks import null_count
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

_contract = yaml.safe_load((ROOT / "contracts/accounts.yml").read_text())
CONTRACT_NOT_NULL = [(_contract["dataset"]["table"], c["name"])
                     for c in _contract["schema"]["columns"] if not c.get("nullable", True)]

INTERNAL_NOT_NULL = [
    ("stg_branches", "branch_id"), ("stg_branches", "branch_name"), ("stg_branches", "region"),
    ("stg_customers", "customer_id"), ("stg_customers", "segment"),
    ("stg_accounts", "account_id"), ("stg_accounts", "customer_id"), ("stg_accounts", "branch_id"),
    ("stg_daily_balances", "account_id"), ("stg_daily_balances", "balance_date"),
    ("stg_daily_balances", "ledger_balance"),
    ("fct_branch_deposits_daily", "branch_id"), ("fct_branch_deposits_daily", "total_balance"),
    ("fct_branch_deposits_daily", "avg_customer_balance"),
    ("quarantine_accounts", "quarantine_reason"), ("quarantine_daily_balances", "quarantine_reason"),
]
CASES = INTERNAL_NOT_NULL + CONTRACT_NOT_NULL


@pytest.mark.parametrize("table,col", CASES, ids=[f"{t}.{c}" for t, c in CASES])
def test_not_null(con, table, col):
    n = null_count(con, table, col)
    assert n == 0, f"{table}.{col} has {n} NULLs"
