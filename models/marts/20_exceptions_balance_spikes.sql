-- Business rule: flag any account whose balance moves by MORE than 300% of the prior
-- observed balance (absolute value, so a swing into overdraft is caught too).
-- Decimal comparison (no division) keeps the 300% boundary exact.
create or replace table exceptions_balance_spikes as
with seq as (
    select
        account_id,
        balance_date,
        ledger_balance,
        lag(ledger_balance) over w as prev_balance,
        lag(balance_date)   over w as prev_date
    from stg_daily_balances
    window w as (partition by account_id order by balance_date)
)
select
    account_id,
    balance_date,
    prev_date,
    prev_balance,
    ledger_balance,
    case when prev_balance = 0 then null
         else cast((ledger_balance - prev_balance) / abs(prev_balance) as double) end as pct_move
from seq
where prev_balance is not null
  and (
        (prev_balance = 0 and ledger_balance <> 0)
     or abs(ledger_balance - prev_balance) > 3 * abs(prev_balance)
  );
