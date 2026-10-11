"""
Reusable data-quality primitives. Each returns the *offending records* (not just a
boolean) so a failing test prints evidence, and includes root-cause hints where a
failure pattern has a known signature (e.g. join fan-out).
"""
from __future__ import annotations

from typing import Sequence

import duckdb


def rows(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence | None = None) -> list[tuple]:
    return con.execute(sql, params or []).fetchall()


def scalar(con, sql: str, params: Sequence | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def column_types(con, table: str) -> dict[str, str]:
    return dict(rows(con, "select column_name, data_type from information_schema.columns "
                          "where table_name = ? order by ordinal_position", [table]))


def duplicate_keys(con, table: str, cols: Sequence[str]) -> list[tuple]:
    c = ", ".join(cols)
    return rows(con, f"select {c}, count(*) as n from {table} group by {c} having count(*) > 1 order by n desc, {c}")


def null_count(con, table: str, col: str) -> int:
    return scalar(con, f"select count(*) from {table} where {col} is null")


def orphans(con, child: str, child_col: str, parent: str, parent_col: str) -> list:
    return [r[0] for r in rows(con, f"""
        select distinct c.{child_col} from {child} c
        where c.{child_col} is not null
          and not exists (select 1 from {parent} p where p.{parent_col} = c.{child_col})
        order by 1""")]


def cast_failures(con, table: str, col: str, target_type: str, key: str) -> list[tuple]:
    return rows(con, f"""
        select {key}, {col} from {table}
        where coalesce({col}, '') <> '' and try_cast({col} as {target_type}) is null
        order by 1""")


def sample(items, n: int = 5) -> str:
    items = list(items)
    more = f" ... (+{len(items) - n} more)" if len(items) > n else ""
    return ", ".join(map(str, items[:n])) + more


def fanout_fingerprint(con, table: str, key: str, fk: str = "branch_id",
                       history: str = "stg_branch_history") -> str:
    """
    If duplicated keys concentrate on FK values that have >1 version in an SCD history
    table, and each key's multiplicity equals that FK's version count, the duplicates
    were manufactured by a join -- the source data is fine. Returns a human diagnosis.
    """
    res = rows(con, f"""
        with d as (select {key}, any_value({fk}) as fk, count(*) as n
                   from {table} group by {key} having count(*) > 1),
             v as (select branch_id, count(*) as versions from {history} group by branch_id)
        select count(*) as dup_keys,
               count(*) filter (where v.versions > 1)         as on_multi_version_fk,
               count(*) filter (where d.n = v.versions)        as multiplicity_matches_versions,
               list(distinct d.fk order by d.fk)               as fks
        from d left join v on d.fk = v.branch_id""")[0]
    dup_keys, on_multi, matches, fks = res
    if not dup_keys:
        return "no duplicates"
    verdict = ("ROOT-CAUSE SIGNATURE: join fan-out against SCD2 history (join on branch_id "
               "without is_current / validity-window predicate)."
               if dup_keys == on_multi == matches else
               "Duplicates do NOT match the SCD fan-out signature -- inspect source extract for double-load.")
    return (f"{dup_keys} duplicated {key}s; {on_multi} sit on {fk}s with >1 history version; "
            f"{matches} have multiplicity == version count; {fk}s involved: {fks}. {verdict}")
