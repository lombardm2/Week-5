#!/usr/bin/env python3
"""Load raw extracts (as strings) into DuckDB and run models in layer order."""
import argparse
import json
import subprocess
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = {"raw_branches": "branches.csv", "raw_customers": "customers.csv",
       "raw_accounts": "accounts.csv", "raw_daily_balances": "daily_balances.csv"}
LAYERS = ["staging", "marts"]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data/raw"))
    ap.add_argument("--warehouse", default=str(ROOT / "build/warehouse.duckdb"))
    args = ap.parse_args()

    wh = Path(args.warehouse)
    wh.parent.mkdir(parents=True, exist_ok=True)
    wh.unlink(missing_ok=True)
    con = duckdb.connect(str(wh))

    for table, fname in RAW.items():
        path = (Path(args.raw) / fname).as_posix().replace("'", "''")
        con.execute(f"create table {table} as select * from read_csv('{path}', header=true, all_varchar=true)")

    for layer in LAYERS:
        for sql_file in sorted((ROOT / "models" / layer).glob("*.sql")):
            try:
                con.execute(sql_file.read_text())
            except duckdb.Error as exc:
                raise SystemExit(f"BUILD FAILED in {sql_file.relative_to(ROOT)}: {exc}")
            print(f"  built {sql_file.relative_to(ROOT)}")

    tables = [r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_name not like '\\_%' escape '\\' order by 1").fetchall()]
    counts = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in tables}
    (wh.parent / "build_manifest.json").write_text(json.dumps({"git_sha": git_sha(), "row_counts": counts}, indent=2))
    width = max(map(len, counts))
    for t, n in counts.items():
        print(f"  {t:<{width}}  {n:>9,}")
    con.close()


if __name__ == "__main__":
    main()
