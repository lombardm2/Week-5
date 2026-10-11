-- PUBLISHED INTERFACE. Governed by contracts/accounts.yml.
-- Any change to columns, types, nullability or allowed values here is a contract change.
create or replace table accounts as
select
    account_id,
    customer_id,
    branch_id,
    account_type,
    account_status,
    open_date,
    interest_rate,
    currency,
    _loaded_at
from stg_accounts;
