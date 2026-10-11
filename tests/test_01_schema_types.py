"""LAYER 1 -- SCHEMA & TYPES. Physical columns, order and types match the declared schema."""
import pytest

import yaml

from checks.lumen_checks import cast_failures, column_types, rows
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


EXPECTED = yaml.safe_load((ROOT / "tests/expected_schemas.yml").read_text())


def _diff(expected: dict, actual: dict) -> str:
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    wrong = {c: (expected[c], actual[c]) for c in expected if c in actual and expected[c] != actual[c]}
    return f"missing={missing} unexpected={extra} type_mismatch(expected,actual)={wrong}"


@pytest.mark.parametrize("table", sorted(EXPECTED))
def test_internal_table_schema(con, table):
    actual = column_types(con, table)
    expected = {k: str(v) for k, v in EXPECTED[table].items()}
    assert actual == expected, f"{table}: {_diff(expected, actual)}"


def test_published_accounts_schema_matches_contract(con, contract):
    expected = {c["name"]: c["type"] for c in contract["schema"]["columns"]}
    actual = column_types(con, contract["dataset"]["table"])
    assert actual == expected, f"accounts vs contract v{contract['version']}: {_diff(expected, actual)}"


@pytest.mark.parametrize("table,col,typ,key", [
    ("raw_accounts", "branch_id", "INTEGER", "account_id"),
    ("raw_accounts", "open_date", "DATE", "account_id"),
    ("raw_accounts", "interest_rate", "DECIMAL(6,4)", "account_id"),
    ("raw_accounts", "_loaded_at", "TIMESTAMP", "account_id"),
    ("raw_daily_balances", "balance_date", "DATE", "account_id"),
    ("raw_daily_balances", "ledger_balance", "DECIMAL(18,2)", "account_id"),
    ("raw_branches", "branch_id", "INTEGER", "branch_id"),
])
def test_raw_values_cast_cleanly(con, table, col, typ, key):
    """Key/measure columns must cast with zero failures; try_cast must never hide data loss here."""
    bad = cast_failures(con, table, col, typ, key)
    assert not bad, f"{len(bad)} values in {table}.{col} fail cast to {typ}: {bad[:5]}"


def test_every_attribute_cast_failure_is_logged(con):
    """Non-key cast failures are tolerated only if logged to dq_issues -- never silently nulled."""
    failed = {r[0] for r in cast_failures(con, "raw_customers", "date_of_birth", "DATE", "customer_id")}
    logged = {r[0] for r in rows(con, "select record_key from dq_issues where column_name = 'date_of_birth'")}
    assert failed == logged, f"unlogged={failed - logged} phantom={logged - failed}"
