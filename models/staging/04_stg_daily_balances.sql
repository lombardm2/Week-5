create or replace table _balances_typed as
select
    account_id,
    try_cast(balance_date as date)            as balance_date,
    try_cast(ledger_balance as decimal(18,2)) as ledger_balance,
    row_number() over (partition by account_id, balance_date order by account_id) as _rn
from raw_daily_balances;

create or replace table _balances_classified as
select
    b.*,
    case
        when b._rn > 1                then 'duplicate_account_date'
        when b.ledger_balance is null then 'null_ledger_balance'
        when ra.account_id is null    then 'orphan_account_id'
        when sa.account_id is null    then 'parent_account_quarantined'
    end as quarantine_reason
from _balances_typed b
left join (select distinct account_id from raw_accounts) ra on b.account_id = ra.account_id
left join stg_accounts sa on b.account_id = sa.account_id;

create or replace table quarantine_daily_balances as
select account_id, balance_date, ledger_balance, quarantine_reason
from _balances_classified
where quarantine_reason is not null;

create or replace table stg_daily_balances as
select account_id, balance_date, ledger_balance
from _balances_classified
where quarantine_reason is null;
