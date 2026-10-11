-- Feeds the CFO weekly deposits packet. Grain: (branch_id, balance_date).
-- Joins only to one-row-per-key relations; reconciliation tests enforce that
-- sum(total_balance) equals the ledger for every balance_date.
create or replace table fct_branch_deposits_daily as
select
    a.branch_id,
    br.branch_name,
    br.region,
    d.balance_date,
    count(distinct a.account_id)                  as n_accounts,
    count(distinct a.customer_id)                 as n_customers,
    cast(sum(d.ledger_balance) as decimal(38,2))  as total_balance,
    cast(sum(d.ledger_balance) / count(distinct a.customer_id) as decimal(18,2)) as avg_customer_balance
from stg_daily_balances d
join accounts     a  on d.account_id = a.account_id
join stg_branches br on a.branch_id  = br.branch_id
group by all;
