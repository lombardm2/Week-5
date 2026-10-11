#!/usr/bin/env python3
"""
Promote / roll back warehouse releases: immutable releases + atomic pointer swap.

Layout under --root:
  <env>/releases/<release_id>/warehouse.duckdb
  <env>/releases/<release_id>/release.json   git sha, contract versions, row counts
  <env>/CURRENT                               release_id being served (swapped atomically)
  <env>/history.jsonl                         append-only audit log

This filesystem adapter runs locally and in CI. In production the same verbs map onto
the warehouse: build each release into an immutable schema, then swap the serving alias
in one transaction (Snowflake ALTER SCHEMA ... SWAP WITH, BigQuery view repoint,
Postgres CREATE OR REPLACE VIEW). Rollback never rebuilds; it re-points.
"""
import argparse
import datetime as dt
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def actor() -> str:
    return os.environ.get("GITHUB_ACTOR") or getpass.getuser()


def env_dir(root: str, env: str) -> Path:
    return Path(root) / env


def current(d: Path) -> str | None:
    p = d / "CURRENT"
    return p.read_text().strip() if p.exists() else None


def swap_pointer(d: Path, release_id: str) -> None:
    tmp = d / "CURRENT.tmp"
    tmp.write_text(release_id + "\n")
    os.replace(tmp, d / "CURRENT")          # atomic on POSIX


def log(d: Path, **event) -> None:
    with open(d / "history.jsonl", "a") as fh:
        fh.write(json.dumps({"at": now(), "actor": actor(), **event}) + "\n")


def history(d: Path) -> list[dict]:
    p = d / "history.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def promote(a) -> int:
    d = env_dir(a.root, a.env)
    rel = d / "releases" / a.release_id
    if rel.exists():
        print(f"release {a.release_id} already exists (releases are immutable)", file=sys.stderr)
        return 1
    rel.mkdir(parents=True)
    shutil.copy2(a.warehouse, rel / "warehouse.duckdb")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    contracts = {p.stem: yaml.safe_load(p.read_text())["version"] for p in (ROOT / "contracts").glob("*.yml")}
    bm = Path(a.warehouse).parent / "build_manifest.json"
    meta = {"release_id": a.release_id, "env": a.env, "git_sha": sha, "contracts": contracts,
            "built_at": now(), "row_counts": json.loads(bm.read_text())["row_counts"] if bm.exists() else {}}
    (rel / "release.json").write_text(json.dumps(meta, indent=2))
    prev = current(d)
    swap_pointer(d, a.release_id)
    log(d, action="promote", release=a.release_id, previous=prev, git_sha=sha, contracts=contracts, reason=a.reason)
    print(f"[{a.env}] promoted {a.release_id} (git {sha[:7]}, contracts {contracts}); previous={prev}")
    return 0


def rollback(a) -> int:
    d = env_dir(a.root, a.env)
    cur = current(d)
    target = a.to
    if not target:   # previous release that was served before the current one
        served = [e["release"] for e in history(d) if e["action"] in ("promote", "rollback")]
        earlier = [r for r in served if r != cur]
        target = earlier[-1] if earlier else None
    if not target or not (d / "releases" / target / "warehouse.duckdb").exists():
        print(f"no valid rollback target (requested={a.to!r}); available: "
              f"{sorted(p.name for p in (d / 'releases').glob('*'))}", file=sys.stderr)
        return 1
    if not a.reason:
        print("--reason is required for rollback (incident ticket / explanation)", file=sys.stderr)
        return 1
    swap_pointer(d, target)
    log(d, action="rollback", release=target, previous=cur, reason=a.reason)
    meta = json.loads((d / "releases" / target / "release.json").read_text())
    print(f"[{a.env}] ROLLED BACK {cur} -> {target} (git {meta['git_sha'][:7]}, contracts {meta['contracts']})")
    return 0


def status(a) -> int:
    d = env_dir(a.root, a.env)
    print(f"[{a.env}] CURRENT = {current(d)}")
    for e in history(d)[-10:]:
        print(f"  {e['at']}  {e['action']:<8} {e['release']:<44} prev={e.get('previous')}  {e.get('reason') or ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.environ.get("RELEASE_ROOT", str(ROOT / ".environments")))
    ap.add_argument("--env", default="staging")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("promote")
    p.add_argument("--release-id", required=True)
    p.add_argument("--warehouse", default=str(ROOT / "build/warehouse.duckdb"))
    p.add_argument("--reason", default="merge to main")
    r = sub.add_parser("rollback")
    r.add_argument("--to", help="release_id to restore (default: previously served release)")
    r.add_argument("--reason", required=False)
    sub.add_parser("status")
    a = ap.parse_args()
    return {"promote": promote, "rollback": rollback, "status": status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
