-- PUBLISHED INTERFACE. Governed by contracts/accounts.yml.
-- feat: add branch region for the regional deposits view; align status naming with branch-ops
create or replace table accounts as
select
    a.account_id,
    a.customer_id,
    a.branch_id,
    a.account_type,
    a.account_status as status,
    a.open_date,
    a.interest_rate,
    a.currency,
    a._loaded_at,
    b.region
from stg_accounts a
left join stg_branch_history b      -- history has region over time
    on a.branch_id = b.branch_id;
