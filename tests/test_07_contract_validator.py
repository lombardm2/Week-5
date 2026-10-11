"""
LAYER 7 -- THE VALIDATOR IS ITSELF TESTED.
Each breaking-change class must be classified correctly, the semver gate must fail
when the bump is insufficient, and the CLI must exit non-zero on data violations.
"""
import copy
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("validate_contract", ROOT / "scripts/validate_contract.py")
vc = importlib.util.module_from_spec(_spec)
sys.modules["validate_contract"] = vc
_spec.loader.exec_module(vc)

BASE = yaml.safe_load((ROOT / "contracts/accounts.yml").read_text())


def col(c, name):
    return next(x for x in c["schema"]["columns"] if x["name"] == name)


def kinds(base, head):
    return {(c.kind, c.breaking) for c in vc.diff_contracts(base, head)}


@pytest.mark.parametrize("mutate,expected", [
    (lambda c: c["schema"]["columns"].pop(), ("column_removed", True)),
    (lambda c: col(c, "account_status").update(name="status"), ("column_removed", True)),
    (lambda c: c["schema"]["columns"].append({"name": "region", "type": "VARCHAR", "nullable": True}), ("column_added", False)),
    (lambda c: col(c, "branch_id").update(type="VARCHAR"), ("column_type_changed", True)),
    (lambda c: col(c, "branch_id").update(type="BIGINT"), ("column_type_widened", False)),
    (lambda c: col(c, "interest_rate").update(type="DECIMAL(8,4)"), ("column_type_widened", False)),
    (lambda c: col(c, "interest_rate").update(type="DECIMAL(6,2)"), ("column_type_changed", True)),
    (lambda c: col(c, "customer_id").update(nullable=True), ("nullable_relaxed", True)),
    (lambda c: col(c, "account_type").update(allowed_values=["CHECKING", "SAVINGS", "MONEY_MARKET", "CD", "HSA"]), ("allowed_values_expanded", True)),
    (lambda c: col(c, "account_type").update(allowed_values=["CHECKING", "SAVINGS"]), ("allowed_values_narrowed", False)),
    (lambda c: col(c, "interest_rate").update(range={"min": 0, "max": 0.25}), ("range_widened", True)),
    (lambda c: col(c, "interest_rate").update(range={"min": 0, "max": 0.10}), ("range_narrowed", False)),
    (lambda c: col(c, "open_date").update(range={"min": "1980-01-01", "max": "today"}), ("range_widened", True)),
    (lambda c: col(c, "account_id").update(pattern="^ACC-[0-9]+$"), ("pattern_changed", True)),
    (lambda c: c["dataset"].update(primary_key=["account_id", "customer_id"]), ("primary_key_changed", True)),
    (lambda c: c["freshness"].update(error_after_hours=48), ("freshness_relaxed", True)),
    (lambda c: c["freshness"].update(error_after_hours=25), ("freshness_tightened", False)),
])
def test_change_classification(mutate, expected):
    head = copy.deepcopy(BASE)
    mutate(head)
    assert expected in kinds(BASE, head)


def _with(version, mutate=None, changelog_extra=None):
    head = copy.deepcopy(BASE)
    if mutate:
        mutate(head)
    head["version"] = version
    head["changelog"].append({"version": version, "summary": "test", **(changelog_extra or {})})
    return head


def _status(findings, check):
    return [f.status for f in findings if f.check == check]


def test_breaking_change_with_minor_bump_fails():
    head = _with("1.1.0", lambda c: col(c, "account_status").update(name="status"))
    f, _ = vc.validate_policy(BASE, head)
    assert _status(f, "semver.sufficient_bump") == ["fail"]


def test_breaking_change_with_major_bump_but_no_signoff_fails():
    head = _with("2.0.0", lambda c: col(c, "account_status").update(name="status"))
    f, _ = vc.validate_policy(BASE, head)
    assert "fail" in _status(f, "major_bump.changelog.consumer_signoff")


def test_breaking_change_with_major_bump_and_full_signoff_passes():
    teams = [c["team"] for c in BASE["info"]["consumers"]]
    head = _with("2.0.0", lambda c: col(c, "account_status").update(name="status"),
                 {"breaking": True, "migration": "dual-publish 30 days", "consumer_signoff": teams})
    f, _ = vc.validate_policy(BASE, head)
    assert all(x.status == "pass" for x in f), [x for x in f if x.status != "pass"]


def test_additive_change_needs_minor_bump():
    add = lambda c: c["schema"]["columns"].append({"name": "region", "type": "VARCHAR", "nullable": True})  # noqa: E731
    f_none, _ = vc.validate_policy(BASE, _with("1.0.0", add))
    f_minor, _ = vc.validate_policy(BASE, _with("1.1.0", add))
    assert _status(f_none, "semver.sufficient_bump") == ["fail"]
    assert _status(f_minor, "semver.sufficient_bump") == ["pass"]


def test_warn_mode_never_fails():
    head = _with("1.0.1", lambda c: c["schema"]["columns"].pop())
    f, _ = vc.validate_policy(BASE, head, mode="warn")
    assert all(x.status != "fail" for x in f)


def test_malformed_contract_rejected():
    bad = copy.deepcopy(BASE)
    del bad["freshness"]
    assert any(f.status == "fail" for f in vc.validate_structure(bad, "head"))


@pytest.fixture
def tiny_warehouse(tmp_path):
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create table stg_customers as select 'C000001' as customer_id")
    con.execute("create table stg_branches as select 101 as branch_id")
    con.execute("""create table accounts as select
        'ACC-0000001'::varchar account_id, 'C000001'::varchar customer_id, 101::integer branch_id,
        'CHECKING'::varchar account_type, 'ACTIVE'::varchar account_status, date '2020-01-01' open_date,
        0.0100::decimal(6,4) interest_rate, 'USD'::varchar currency, timestamp '2026-01-01 05:00:00' _loaded_at
        from range(1500)""")  # 1,500 identical keys -> PK violation by construction
    con.close()
    return path


def test_cli_exits_nonzero_on_data_violation(tiny_warehouse):
    code = vc.main(["--contract", str(ROOT / "contracts/accounts.yml"), "--warehouse", str(tiny_warehouse),
                    "--now", "2026-01-01T06:00:00"])
    assert code & vc.EXIT_DATA


def test_cli_exits_nonzero_on_stale_data(tiny_warehouse):
    con = duckdb.connect(str(tiny_warehouse))
    con.execute("create or replace table accounts as select * replace ('ACC-' || lpad((row_number() over ())::varchar, 7, '0') as account_id) from accounts")
    con.close()
    fresh = vc.main(["--contract", str(ROOT / "contracts/accounts.yml"), "--warehouse", str(tiny_warehouse), "--now", "2026-01-01T06:00:00"])
    stale = vc.main(["--contract", str(ROOT / "contracts/accounts.yml"), "--warehouse", str(tiny_warehouse), "--now", "2026-01-02T08:00:00"])
    assert fresh == 0
    assert stale & vc.EXIT_DATA
