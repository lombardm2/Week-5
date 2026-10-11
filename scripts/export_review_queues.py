#!/usr/bin/env python3
"""Export human review queues (spike exceptions, quarantines, DQ issues) as CSV artifacts."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "build/review_queues"
out.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(str(ROOT / "build/warehouse.duckdb"), read_only=True)
for table in ["exceptions_balance_spikes", "quarantine_accounts", "quarantine_daily_balances", "dq_issues"]:
    con.execute(f"copy (select * from {table}) to '{(out / (table + '.csv')).as_posix()}' (header)")
    n = con.execute(f"select count(*) from {table}").fetchone()[0]
    print(f"{table:<28} {n:>6} rows -> build/review_queues/{table}.csv")
