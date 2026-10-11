"""
LAYER 6 -- GRAIN & RECONCILIATION (the direct control for last quarter's incident).
A join fan-out does not change any single value's type or nullability -- it silently
multiplies rows. These tests catch it by asserting cardinality is preserved across
enrichment and that the CFO mart ties out to the ledger to the cent, every day.
"""
from checks.lumen_checks import rows, scalar


def test_enrichment_preserves_account_cardinality(con):
    staged = scalar(con, "select count(*) from stg_accounts")
    published = scalar(con, "select count(*) from accounts")
    distinct = scalar(con, "select count(distinct account_id) from accounts")
    assert published == staged == distinct, (
        f"stg_accounts={staged:,} rows -> accounts={published:,} rows ({distinct:,} distinct). "
        f"Enrichment changed row count by {published - staged:+,}: a join to a non-unique key.")


def test_mart_reconciles_to_ledger_every_day(con):
    breaks = rows(con, """
        with ledger as (select balance_date, sum(ledger_balance) amt from stg_daily_balances group by 1),
             mart   as (select balance_date, sum(total_balance) amt from fct_branch_deposits_daily group by 1)
        select l.balance_date, l.amt, m.amt, m.amt - l.amt
        from ledger l full join mart m using (balance_date)
        where l.amt is distinct from m.amt order by 1""")
    detail = ""
    if breaks:
        day = breaks[0][0]
        by_branch = rows(con, """
            with ledger as (select a.branch_id, sum(d.ledger_balance) amt from stg_daily_balances d
                            join stg_accounts a using (account_id) where d.balance_date = ? group by 1),
                 mart as (select branch_id, total_balance amt from fct_branch_deposits_daily where balance_date = ?)
            select l.branch_id, round(m.amt / l.amt, 4) as ratio from ledger l join mart m using (branch_id)
            where m.amt <> l.amt order by 1""", [day, day])
        detail = (f"\n  Branch-level ratios mart/ledger on {day}: {by_branch}"
                  f"\n  Integer ratios on a subset of branches = rows duplicated by a join, not bad source data.")
    assert not breaks, (f"{len(breaks)} days where mart != ledger. first: date={breaks[0][0]} "
                        f"ledger={breaks[0][1]:,} mart={breaks[0][2]:,} delta={breaks[0][3]:+,}{detail}")


def test_mart_account_counts_reconcile(con):
    bad = scalar(con, """
        with l as (select balance_date, count(distinct account_id) n from stg_daily_balances group by 1),
             m as (select balance_date, sum(n_accounts) n from fct_branch_deposits_daily group by 1)
        select count(*) from l full join m using (balance_date) where l.n is distinct from m.n""")
    assert bad == 0, f"{bad} days where mart account counts != ledger account counts"


def test_avg_customer_balance_definition(con):
    bad = scalar(con, """select count(*) from fct_branch_deposits_daily
                         where avg_customer_balance <> cast(total_balance / n_customers as decimal(18,2))""")
    assert bad == 0, f"{bad} rows where avg_customer_balance != total_balance / n_customers"
