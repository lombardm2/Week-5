#!/usr/bin/env python3
"""
Deterministic synthetic core-banking dataset for Lumen Community Bank.

Produces four raw extracts (all strings, as a core system export would land):
  branches.csv        42 branches, SCD Type 2 -- 9 branches carry a historical row,
                      so branch_id alone is NOT unique (the fan-out trap from last quarter)
  customers.csv       3,000 customers
  accounts.csv        4,500 accounts
  daily_balances.csv  60 days of end-of-day ledger balances per account

Every defect is planted on purpose and recorded in _manifest.json so the test
suite can prove it detects *exactly* what was planted (detector calibration).
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260311
N_CUSTOMERS = 3000
N_ACCOUNTS = 4500
N_DAYS = 60

FIRST = ["Maria", "James", "Linda", "Robert", "Patricia", "Michael", "Jennifer", "David",
         "Elizabeth", "William", "Susan", "Joseph", "Karen", "Thomas", "Nancy", "Daniel",
         "Lisa", "Matthew", "Betty", "Anthony", "Sandra", "Mark", "Ashley", "Steven"]
LAST = ["Anderson", "Nelson", "Johnson", "Larson", "Peterson", "Schmidt", "Mueller", "Olson",
        "Kowalski", "Novak", "Hansen", "Jensen", "Becker", "Wagner", "Hoffman", "Klein",
        "Lindqvist", "Garcia", "Martinez", "Nguyen", "Brown", "Miller", "Wilson", "Moore"]
CITIES = ["Aurora", "Peoria", "Rockford", "Joliet", "Naperville", "Elgin", "Waukegan",
          "Champaign", "Bloomington", "Decatur", "Evanston", "Springfield", "Quincy",
          "Galesburg", "Moline", "Kankakee", "DeKalb", "Ottawa", "Dubuque", "Davenport",
          "Cedar Rapids", "Iowa City", "Waterloo", "Ames", "Madison", "Janesville", "Kenosha",
          "Racine", "Green Bay", "Appleton", "Oshkosh", "Eau Claire", "La Crosse", "Wausau",
          "South Bend", "Fort Wayne", "Lafayette", "Gary", "Elkhart", "Kokomo", "Muncie",
          "Terre Haute"]
REGIONS = ["Lakeshore", "Prairie", "River Valley", "North Woods", "Metro"]
ACCOUNT_TYPES = ["CHECKING", "SAVINGS", "MONEY_MARKET", "CD"]
STATUSES = ["ACTIVE", "DORMANT", "CLOSED"]
RATE_RANGES = {"CHECKING": (0.0005, 0.0050), "SAVINGS": (0.0050, 0.0400),
               "MONEY_MARKET": (0.0200, 0.0450), "CD": (0.0300, 0.0525)}


def iso(d: dt.date) -> str:
    return d.isoformat()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--as-of", default=None, help="Last balance date (default: yesterday UTC)")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else (now.date() - dt.timedelta(days=1))
    dates = [as_of - dt.timedelta(days=N_DAYS - 1 - i) for i in range(N_DAYS)]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def person() -> str:
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"

    # ------------------------------------------------------------------ branches (SCD2)
    branch_ids = list(range(101, 143))
    scd_ids = sorted(int(x) for x in rng.choice(branch_ids, 9, replace=False))
    b_rows = []
    for i, bid in enumerate(branch_ids):
        name = f"Lumen {CITIES[i]}"
        region = REGIONS[i % len(REGIONS)]
        if bid in scd_ids:  # 2025 regional realignment + manager change
            b_rows.append(dict(branch_id=bid, branch_name=name, region=REGIONS[(i + 1) % 5],
                               branch_manager=person(), valid_from="2018-01-01",
                               valid_to="2025-06-30", is_current="false"))
            b_rows.append(dict(branch_id=bid, branch_name=name, region=region,
                               branch_manager=person(), valid_from="2025-07-01",
                               valid_to="9999-12-31", is_current="true"))
        else:
            b_rows.append(dict(branch_id=bid, branch_name=name, region=region,
                               branch_manager=person(), valid_from="2015-01-01",
                               valid_to="9999-12-31", is_current="true"))
    branches = pd.DataFrame(b_rows)

    # ------------------------------------------------------------------ customers
    cust_ids = [f"C{i:06d}" for i in range(1, N_CUSTOMERS + 1)]
    dob_days = rng.integers(0, (dt.date(2005, 12, 31) - dt.date(1940, 1, 1)).days, N_CUSTOMERS)
    home_branch = rng.choice(branch_ids, N_CUSTOMERS)
    customers = pd.DataFrame({
        "customer_id": cust_ids,
        "first_name": rng.choice(FIRST, N_CUSTOMERS),
        "last_name": rng.choice(LAST, N_CUSTOMERS),
        "date_of_birth": [iso(dt.date(1940, 1, 1) + dt.timedelta(days=int(d))) for d in dob_days],
        "segment": rng.choice(["RETAIL", "SMALL_BUSINESS"], N_CUSTOMERS, p=[0.85, 0.15]),
        "home_branch_id": home_branch.astype(str),
        "created_at": [f"{iso(dt.date(2000, 1, 1) + dt.timedelta(days=int(d)))}T09:00:00"
                       for d in rng.integers(0, 8000, N_CUSTOMERS)],
    })
    bad_dob_idx = rng.choice(N_CUSTOMERS, 2, replace=False)
    for idx, bad in zip(bad_dob_idx, ["1987-13-41", "31/02/1979"]):  # type defects
        customers.loc[idx, "date_of_birth"] = bad
    malformed_dob_ids = sorted(customers.loc[bad_dob_idx, "customer_id"].tolist())

    # ------------------------------------------------------------------ accounts
    acct_ids = [f"ACC-{i:07d}" for i in range(1, N_ACCOUNTS + 1)]
    cust_idx = rng.integers(0, N_CUSTOMERS, N_ACCOUNTS)
    acct_branch = np.where(rng.random(N_ACCOUNTS) < 0.8, home_branch[cust_idx],
                           rng.choice(branch_ids, N_ACCOUNTS))
    acct_type = rng.choice(ACCOUNT_TYPES, N_ACCOUNTS, p=[0.45, 0.35, 0.10, 0.10])
    status = rng.choice(STATUSES, N_ACCOUNTS, p=[0.85, 0.10, 0.05]).astype(object)
    rates = np.array([round(rng.uniform(*RATE_RANGES[t]), 4) for t in acct_type])
    max_open = (as_of - dt.timedelta(days=90) - dt.date(2000, 1, 1)).days
    open_dates = [iso(dt.date(2000, 1, 1) + dt.timedelta(days=int(d)))
                  for d in rng.integers(0, max_open, N_ACCOUNTS)]

    # Disjoint pools of accounts for each planted defect
    perm = [int(x) for x in rng.permutation(N_ACCOUNTS)]
    pools, cursor = {}, 0
    for name, size in [("orphan_branch", 7), ("orphan_customer", 5), ("null_customer", 4),
                       ("invalid_type", 2), ("dup_account", 3), ("spike_5x", 8),
                       ("spike_302", 1), ("sign_flip", 1), ("boundary_300", 1),
                       ("null_balance", 3), ("dup_balance", 4)]:
        pools[name] = perm[cursor:cursor + size]
        cursor += size
    for name in ("spike_5x", "spike_302", "sign_flip", "boundary_300"):
        status[pools[name]] = "ACTIVE"

    accounts = pd.DataFrame({
        "account_id": acct_ids,
        "customer_id": [cust_ids[i] for i in cust_idx],
        "branch_id": acct_branch.astype(str),
        "account_type": acct_type.astype(object),
        "account_status": status,
        "open_date": open_dates,
        "interest_rate": [f"{r:.4f}" for r in rates],
        "currency": "USD",
        "_loaded_at": now.isoformat(),
    })
    accounts.loc[pools["orphan_branch"], "branch_id"] = "199"          # branch never existed
    accounts.loc[pools["orphan_customer"], "customer_id"] = [f"C99{k:04d}" for k in range(5)]
    accounts.loc[pools["null_customer"], "customer_id"] = ""
    accounts.loc[pools["invalid_type"], "account_type"] = "XYZ"
    accounts_raw = pd.concat([accounts, accounts.loc[pools["dup_account"]]], ignore_index=True)

    # ------------------------------------------------------------------ daily balances
    start = np.maximum(rng.lognormal(mean=8.5, sigma=1.1, size=N_ACCOUNTS), 50.0)
    rets = np.clip(rng.normal(0, 0.015, (N_ACCOUNTS, N_DAYS)), -0.08, 0.08)
    rets[:, 0] = 0.0
    bal = np.round(np.maximum(start[:, None] * np.cumprod(1 + rets, axis=1), 25.0), 2)
    bal[status == "CLOSED", :] = 0.0

    expected_flags, boundary = [], []
    for i in pools["spike_5x"] + pools["spike_302"]:
        d = int(rng.integers(5, N_DAYS - 5))
        mult = 5.0 if i in pools["spike_5x"] else 4.02
        bal[i, d] = round(bal[i, d - 1] * mult, 2)
        expected_flags.append({"account_id": acct_ids[i], "balance_date": iso(dates[d])})
    i = pools["sign_flip"][0]                       # overdraft: +200 -> -500 = -350%
    d = int(rng.integers(5, N_DAYS - 5))
    bal[i, :d], bal[i, d:] = 200.00, -500.00
    expected_flags.append({"account_id": acct_ids[i], "balance_date": iso(dates[d])})
    i = pools["boundary_300"][0]                    # exactly +300%: must NOT flag (strict >)
    d = int(rng.integers(5, N_DAYS - 5))
    bal[i, :d], bal[i, d:] = 1000.00, 4000.00
    boundary.append({"account_id": acct_ids[i], "balance_date": iso(dates[d])})

    balances = pd.DataFrame({
        "account_id": np.repeat(acct_ids, N_DAYS),
        "balance_date": np.tile([iso(x) for x in dates], N_ACCOUNTS),
        "ledger_balance": np.char.mod("%.2f", bal.reshape(-1)),
    })
    null_rows, dup_rows = [], []
    for i in pools["null_balance"]:
        d = int(rng.integers(1, N_DAYS - 1))
        balances.loc[i * N_DAYS + d, "ledger_balance"] = ""
        null_rows.append({"account_id": acct_ids[i], "balance_date": iso(dates[d])})
    dup_idx = []
    for i in pools["dup_balance"]:
        d = int(rng.integers(0, N_DAYS))
        dup_idx.append(i * N_DAYS + d)
        dup_rows.append({"account_id": acct_ids[i], "balance_date": iso(dates[d])})
    orphan_ids = ["ACC-9999991", "ACC-9999992"]
    orphans = pd.DataFrame({
        "account_id": np.repeat(orphan_ids, N_DAYS),
        "balance_date": np.tile([iso(x) for x in dates], len(orphan_ids)),
        "ledger_balance": np.char.mod("%.2f", np.round(rng.uniform(100, 9000, N_DAYS * 2), 2)),
    })
    balances_raw = pd.concat([balances, balances.loc[dup_idx], orphans], ignore_index=True)

    # ------------------------------------------------------------------ write
    branches.to_csv(out / "branches.csv", index=False)
    customers.to_csv(out / "customers.csv", index=False)
    accounts_raw.to_csv(out / "accounts.csv", index=False)
    balances_raw.to_csv(out / "daily_balances.csv", index=False)

    ids = lambda pool: sorted(acct_ids[k] for k in pools[pool])  # noqa: E731
    manifest = {
        "seed": args.seed, "as_of": iso(as_of), "generated_at": now.isoformat(),
        "row_counts": {"branches": len(branches), "customers": len(customers),
                       "accounts": len(accounts_raw), "daily_balances": len(balances_raw)},
        "reference": {"scd_branch_ids": scd_ids, "distinct_branches": len(branch_ids)},
        "violations": {
            "raw_customers": {"malformed_dob_customer_ids": malformed_dob_ids},
            "raw_accounts": {
                "duplicate_account_ids": ids("dup_account"),
                "orphan_branch_account_ids": ids("orphan_branch"),
                "orphan_customer_account_ids": ids("orphan_customer"),
                "null_customer_account_ids": ids("null_customer"),
                "invalid_account_type_account_ids": ids("invalid_type"),
            },
            "raw_daily_balances": {
                "orphan_account_ids": orphan_ids, "orphan_rows": len(orphans),
                "duplicate_rows": dup_rows, "null_balance_rows": null_rows,
            },
        },
        "business_rule_balance_spike": {
            "threshold": "abs(day-over-day move) > 300% of prior balance",
            "expected_flags": sorted(expected_flags, key=lambda r: r["account_id"]),
            "boundary_not_flagged": boundary,
        },
    }
    (out / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Generated as_of={as_of}: " + ", ".join(f"{k}={v:,}" for k, v in manifest["row_counts"].items()))


if __name__ == "__main__":
    main()
