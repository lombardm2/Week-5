#!/usr/bin/env python3
"""
Validate a Lumen data contract in three independent stages:

  1. CONTRACT  - the YAML itself is well-formed (JSON Schema meta-validation)
  2. DATA      - the built table conforms: schema, types, nullability, PK, allowed
                 values, ranges, patterns, references, row count, freshness
  3. POLICY    - versus the base branch's contract, every change is classified as
                 breaking / non-breaking and the semver bump is sufficient

Exit code is a bitmask so CI logs say *which* stage failed:
  0 = pass   1 = data violation   2 = change-policy violation   4 = malformed contract
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
META_SCHEMA = ROOT / "contracts/_meta/datacontract.schema.json"
EXIT_DATA, EXIT_POLICY, EXIT_INVALID = 1, 2, 4
TYPE_ALIASES = {"INT": "INTEGER", "INT4": "INTEGER", "INT8": "BIGINT", "STRING": "VARCHAR",
                "TEXT": "VARCHAR", "BOOL": "BOOLEAN", "TIMESTAMP_NTZ": "TIMESTAMP", "FLOAT8": "DOUBLE"}


@dataclass
class Finding:
    stage: str      # contract | data | policy
    check: str
    status: str     # pass | warn | fail
    detail: str


@dataclass
class Change:
    kind: str
    target: str
    detail: str
    breaking: bool


# ----------------------------------------------------------------------------- helpers
def norm_type(t: str) -> str:
    t = re.sub(r"\s+", "", str(t).upper())
    return TYPE_ALIASES.get(t, t)


def parse_decimal(t: str):
    m = re.fullmatch(r"DECIMAL\((\d+),(\d+)\)", norm_type(t))
    return (int(m.group(1)), int(m.group(2))) if m else None


def is_widening(old: str, new: str) -> bool:
    o, n = norm_type(old), norm_type(new)
    if (o, n) in {("INTEGER", "BIGINT"), ("SMALLINT", "INTEGER"), ("SMALLINT", "BIGINT")}:
        return True
    od, nd = parse_decimal(o), parse_decimal(n)
    return bool(od and nd and nd[1] == od[1] and nd[0] > od[0])


def semver(v: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in v.split("."))  # type: ignore[return-value]


def resolve_bound(value, now: dt.datetime):
    if value == "today":
        return now.date()
    if value == "now":
        return now
    return value


def sql_literal(v) -> str:
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dt.datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    if isinstance(v, dt.date):
        return f"DATE '{v.isoformat()}'"
    s = str(v).replace("'", "''")
    return f"DATE '{s}'" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else f"'{s}'"


# ----------------------------------------------------------------------------- stage 1
def validate_structure(contract: dict, label: str) -> list[Finding]:
    schema = json.loads(META_SCHEMA.read_text())
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(contract), key=lambda e: list(e.path))
    if errors:
        return [Finding("contract", f"{label}:structure", "fail",
                        f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}") for e in errors]
    f = contract["freshness"]
    out = [Finding("contract", f"{label}:structure", "pass", "matches lumen.datacontract/v1 meta-schema")]
    if f["warn_after_hours"] > f["error_after_hours"]:
        out.append(Finding("contract", f"{label}:freshness_order", "fail", "warn_after_hours > error_after_hours"))
    cols = [c["name"] for c in contract["schema"]["columns"]]
    for pk in contract["dataset"]["primary_key"]:
        if pk not in cols:
            out.append(Finding("contract", f"{label}:primary_key", "fail", f"PK column {pk!r} not in schema"))
    if contract["changelog"][-1]["version"] != contract["version"] and \
            all(e["version"] != contract["version"] for e in contract["changelog"]):
        out.append(Finding("contract", f"{label}:changelog", "fail", f"no changelog entry for {contract['version']}"))
    return out


# ----------------------------------------------------------------------------- stage 2
def validate_data(con, contract: dict, now: dt.datetime) -> list[Finding]:
    F: list[Finding] = []
    table = contract["dataset"]["table"]
    add = lambda check, ok, detail, warn=False: F.append(  # noqa: E731
        Finding("data", check, "pass" if ok else ("warn" if warn else "fail"), detail))

    actual = dict(con.execute("select column_name, data_type from information_schema.columns "
                              "where table_name = ? order by ordinal_position", [table]).fetchall())
    if not actual:
        add("table_exists", False, f"table {table!r} not found in warehouse")
        return F
    total = con.execute(f"select count(*) from {table}").fetchone()[0]

    expected = {c["name"]: c for c in contract["schema"]["columns"]}
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    add("schema.missing_columns", not missing, f"missing: {missing}" if missing else "all contracted columns present")
    if contract["schema"].get("additional_columns", "forbid") == "forbid":
        add("schema.unexpected_columns", not extra,
            f"uncontracted columns published: {extra}" if extra else "no uncontracted columns")

    for name, spec in expected.items():
        if name not in actual:
            continue
        ok = norm_type(actual[name]) == norm_type(spec["type"])
        add(f"type.{name}", ok, f"expected {spec['type']}, found {actual[name]}")

        if not spec["nullable"]:
            n = con.execute(f"select count(*) from {table} where {name} is null").fetchone()[0]
            add(f"not_null.{name}", n == 0, f"{n} NULL values")

        if "allowed_values" in spec:
            vals = ", ".join(sql_literal(v) if not isinstance(v, str) else "'" + v.replace("'", "''") + "'"
                             for v in spec["allowed_values"])
            bad = con.execute(f"select {name}, count(*) from {table} where {name} is not null "
                              f"and {name} not in ({vals}) group by 1 order by 2 desc limit 5").fetchall()
            add(f"allowed_values.{name}", not bad, f"out-of-domain values: {bad}" if bad else "all values in domain")

        if "range" in spec:
            lo = resolve_bound(spec["range"].get("min"), now)
            hi = resolve_bound(spec["range"].get("max"), now)
            conds = ([f"{name} < {sql_literal(lo)}"] if lo is not None else []) + \
                    ([f"{name} > {sql_literal(hi)}"] if hi is not None else [])
            n = con.execute(f"select count(*) from {table} where {' or '.join(conds)}").fetchone()[0]
            add(f"range.{name}", n == 0, f"{n} values outside [{lo}, {hi}]")

        if "pattern" in spec:
            pat = spec["pattern"].replace("'", "''")
            n = con.execute(f"select count(*) from {table} where {name} is not null "
                            f"and not regexp_full_match({name}, '{pat}')").fetchone()[0]
            add(f"pattern.{name}", n == 0, f"{n} values not matching {spec['pattern']}")

        if "references" in spec:
            ref = spec["references"]
            n = con.execute(f"select count(*) from {table} c where c.{name} is not null and not exists "
                            f"(select 1 from {ref['table']} p where p.{ref['column']} = c.{name})").fetchone()[0]
            add(f"references.{name}", n == 0, f"{n} rows reference missing {ref['table']}.{ref['column']}")

    pk = contract["dataset"]["primary_key"]
    if all(c in actual for c in pk):
        cols = ", ".join(pk)
        dups = con.execute(f"select count(*) from (select {cols} from {table} group by {cols} having count(*) > 1)").fetchone()[0]
        extra_rows = con.execute(f"select count(*) - count(distinct ({cols})) from {table}").fetchone()[0]
        add("primary_key.unique", dups == 0,
            f"{dups} duplicated keys ({extra_rows} surplus rows of {total})" if dups else f"{total} rows, all keys unique")
        nulls = con.execute(f"select count(*) from {table} where " + " or ".join(f"{c} is null" for c in pk)).fetchone()[0]
        add("primary_key.not_null", nulls == 0, f"{nulls} rows with NULL key")

    rc = contract.get("quality", {}).get("row_count", {})
    if rc:
        ok = total >= rc.get("min", 0) and total <= rc.get("max", float("inf"))
        add("quality.row_count", ok, f"{total} rows (bounds {rc})")

    fr = contract["freshness"]
    if fr["column"] in actual:
        latest = con.execute(f"select max({fr['column']}) from {table}").fetchone()[0]
        if latest is None:
            add("freshness", False, "no timestamp values")
        else:
            age_h = (now - latest).total_seconds() / 3600
            detail = f"latest {fr['column']}={latest} age={age_h:.1f}h (warn>{fr['warn_after_hours']}h, error>{fr['error_after_hours']}h)"
            if age_h > fr["error_after_hours"]:
                add("freshness", False, detail)
            else:
                add("freshness", age_h <= fr["warn_after_hours"], detail, warn=True)
    return F


def _bound_key(v):
    """Comparable key for a range bound. 'today'/'now' are moving bounds (treated as +inf)."""
    if v in ("today", "now"):
        return float("inf")
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return dt.date.fromisoformat(str(v)).toordinal()
    except ValueError:
        return str(v)


def range_widened(base: dict | None, head: dict | None) -> bool:
    """True if head admits any value base did not. Incomparable bounds => conservatively breaking."""
    if not base:
        return False                      # adding a range is a tightening
    if not head:
        return True                       # removing a range admits everything
    try:
        for k, looser in (("min", lambda h, b: h < b), ("max", lambda h, b: h > b)):
            if base.get(k) is None:
                continue
            if head.get(k) is None or looser(_bound_key(head[k]), _bound_key(base[k])):
                return True
        return False
    except TypeError:
        return True


# ----------------------------------------------------------------------------- stage 3
def diff_contracts(base: dict, head: dict) -> list[Change]:
    ch: list[Change] = []
    if base["dataset"]["table"] != head["dataset"]["table"]:
        ch.append(Change("table_renamed", "dataset.table",
                         f"{base['dataset']['table']} -> {head['dataset']['table']}", True))
    if base["dataset"]["primary_key"] != head["dataset"]["primary_key"]:
        ch.append(Change("primary_key_changed", "dataset.primary_key",
                         f"{base['dataset']['primary_key']} -> {head['dataset']['primary_key']}", True))

    bcols = {c["name"]: c for c in base["schema"]["columns"]}
    hcols = {c["name"]: c for c in head["schema"]["columns"]}
    for name in bcols.keys() - hcols.keys():
        ch.append(Change("column_removed", name, "column no longer published (renames appear as remove + add)", True))
    for name in sorted(hcols.keys() - bcols.keys()):
        ch.append(Change("column_added", name, f"new column type {hcols[name]['type']}", False))

    for name in sorted(bcols.keys() & hcols.keys()):
        b, h = bcols[name], hcols[name]
        if norm_type(b["type"]) != norm_type(h["type"]):
            wid = is_widening(b["type"], h["type"])
            ch.append(Change("column_type_widened" if wid else "column_type_changed", name,
                             f"{b['type']} -> {h['type']}", not wid))
        if b["nullable"] != h["nullable"]:
            relaxed = h["nullable"]
            ch.append(Change("nullable_relaxed" if relaxed else "nullable_tightened", name,
                             f"nullable {b['nullable']} -> {h['nullable']}", relaxed))
        bv, hv = b.get("allowed_values"), h.get("allowed_values")
        if bv != hv:
            if bv is None or (hv is not None and set(hv) - set(bv)):
                added = set(hv or []) - set(bv or []) if bv else "domain constraint removed"
                ch.append(Change("allowed_values_expanded", name, f"added {added}", True))
            elif hv is None:
                ch.append(Change("allowed_values_expanded", name, "domain constraint removed", True))
            else:
                ch.append(Change("allowed_values_narrowed", name, f"removed {set(bv) - set(hv)}", False))
        br, hr = b.get("range"), h.get("range")
        if br != hr:
            wider = range_widened(br, hr)
            ch.append(Change("range_widened" if wider else "range_narrowed", name, f"{br} -> {hr}", wider))
        if b.get("pattern") != h.get("pattern"):
            ch.append(Change("pattern_changed", name, f"{b.get('pattern')} -> {h.get('pattern')}", True))

    bf, hf = base["freshness"], head["freshness"]
    if hf["error_after_hours"] != bf["error_after_hours"] or hf["column"] != bf["column"]:
        relaxed = hf["error_after_hours"] > bf["error_after_hours"] or hf["column"] != bf["column"]
        ch.append(Change("freshness_relaxed" if relaxed else "freshness_tightened", "freshness",
                         f"error_after {bf['error_after_hours']}h -> {hf['error_after_hours']}h", relaxed))
    return ch


def required_bump(changes: list[Change]) -> str:
    if any(c.breaking for c in changes):
        return "major"
    return "minor" if changes else "none"


def actual_bump(base_v: str, head_v: str) -> str:
    b, h = semver(base_v), semver(head_v)
    if h < b:
        return "downgrade"
    if h[0] > b[0]:
        return "major"
    if h[1] > b[1]:
        return "minor"
    if h[2] > b[2]:
        return "patch"
    return "none"


RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


def validate_policy(base: dict, head: dict, mode: str = "enforce") -> tuple[list[Finding], list[Change]]:
    F: list[Finding] = []
    changes = diff_contracts(base, head)
    need, got = required_bump(changes), actual_bump(base["version"], head["version"])
    fail = "fail" if mode == "enforce" else "warn"
    summary = f"{base['version']} -> {head['version']} ({got}); changes require: {need}"

    if got == "downgrade":
        F.append(Finding("policy", "semver.direction", fail, f"version decreased: {summary}"))
    elif RANK[got] < RANK[need]:
        breaking = [f"{c.kind}({c.target})" for c in changes if c.breaking]
        why = f"BREAKING: {breaking}" if breaking else f"schema changes: {[c.kind for c in changes]}"
        F.append(Finding("policy", "semver.sufficient_bump", fail,
                         f"{summary}. {why}. Breaking changes need a MAJOR bump, a {head['breaking_change_policy'].get('deprecation_window_days', 30)}-day "
                         f"deprecation window, a changelog migration note and consumer sign-off."))
    else:
        F.append(Finding("policy", "semver.sufficient_bump", "pass", summary))

    if got == "major" and need == "major":
        entry = next((e for e in head["changelog"] if e["version"] == head["version"]), {})
        for req in ("breaking", "migration", "consumer_signoff"):
            ok = bool(entry.get(req))
            F.append(Finding("policy", f"major_bump.changelog.{req}", "pass" if ok else fail,
                             f"changelog[{head['version']}].{req} {'present' if ok else 'missing'}"))
        if entry.get("consumer_signoff"):
            listed = {c["team"] for c in head["info"]["consumers"]}
            missing = listed - set(entry["consumer_signoff"])
            F.append(Finding("policy", "major_bump.all_consumers_signed", "pass" if not missing else fail,
                             f"missing sign-off from: {sorted(missing)}" if missing else "all consumers signed off"))
    return F, changes


# ----------------------------------------------------------------------------- report
ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}


def report(contract_path: str, findings: list[Finding], changes: list[Change], out: str | None) -> None:
    print(f"\n=== CONTRACT VALIDATION: {contract_path} ===")
    for stage in ("contract", "data", "policy"):
        rows = [f for f in findings if f.stage == stage]
        if not rows:
            continue
        print(f"\n[{stage.upper()}]")
        for f in rows:
            if f.status != "pass" or os.environ.get("VERBOSE"):
                print(f"  {ICON[f.status]}  {f.check:<34} {f.detail}")
        n_pass = sum(f.status == "pass" for f in rows)
        print(f"  ... {n_pass}/{len(rows)} checks passed")
    if changes:
        print("\n[CHANGES vs BASE]")
        for c in changes:
            print(f"  {'BREAKING ' if c.breaking else 'additive '} {c.kind:<26} {c.target:<16} {c.detail}")

    payload = {"contract": contract_path, "findings": [asdict(f) for f in findings],
               "changes": [asdict(c) for c in changes]}
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(payload, indent=2, default=str))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(f"### Contract `{contract_path}`\n\n| Stage | Check | Status | Detail |\n|---|---|---|---|\n")
            for f in findings:
                if f.status != "pass":
                    fh.write(f"| {f.stage} | `{f.check}` | {ICON[f.status]} | {f.detail} |\n")
            if changes:
                fh.write("\n| Change | Target | Breaking | Detail |\n|---|---|---|---|\n")
                for c in changes:
                    fh.write(f"| {c.kind} | `{c.target}` | {'yes' if c.breaking else 'no'} | {c.detail} |\n")
            fh.write("\n")
    # GitHub annotations surface failures on the PR's Files/Checks tab
    if os.environ.get("GITHUB_ACTIONS"):
        for f in findings:
            if f.status == "fail":
                print(f"::error file={contract_path},title=contract {f.stage}: {f.check}::{f.detail}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--warehouse", default=str(ROOT / "build/warehouse.duckdb"))
    ap.add_argument("--base-contract", help="Contract file from the base branch, for change-policy checks")
    ap.add_argument("--policy-mode", choices=["enforce", "warn"], default="enforce")
    ap.add_argument("--skip-data", action="store_true")
    ap.add_argument("--now", help="Override 'now' (ISO, UTC) for freshness tests")
    ap.add_argument("--report", help="Write JSON report here")
    a = ap.parse_args(argv)

    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    head = yaml.safe_load(Path(a.contract).read_text())
    findings = validate_structure(head, "head")
    changes: list[Change] = []
    code = 0
    if any(f.status == "fail" for f in findings):
        report(a.contract, findings, changes, a.report)
        return EXIT_INVALID

    if not a.skip_data:
        con = duckdb.connect(a.warehouse, read_only=True)
        findings += validate_data(con, head, now)
        con.close()

    if a.base_contract and Path(a.base_contract).exists() and Path(a.base_contract).stat().st_size:
        base = yaml.safe_load(Path(a.base_contract).read_text())
        base_struct = validate_structure(base, "base")
        if all(f.status != "fail" for f in base_struct):
            pf, changes = validate_policy(base, head, a.policy_mode)
            findings += pf
    else:
        findings.append(Finding("policy", "base_contract", "pass", "no base contract (new contract) - policy diff skipped"))

    if any(f.stage == "data" and f.status == "fail" for f in findings):
        code |= EXIT_DATA
    if any(f.stage == "policy" and f.status == "fail" for f in findings):
        code |= EXIT_POLICY
    report(a.contract, findings, changes, a.report)
    verdict = "PASSED" if code == 0 else f"FAILED (exit {code}: " + ", ".join(
        n for bit, n in [(EXIT_DATA, "data"), (EXIT_POLICY, "change-policy"), (EXIT_INVALID, "contract")] if code & bit) + ")"
    print(f"\nRESULT: {verdict}")
    return code


if __name__ == "__main__":
    sys.exit(main())
