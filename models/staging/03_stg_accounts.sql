-- Key / relationship failures are QUARANTINED with a reason, never silently dropped.
-- Reconciliation tests prove raw = staged + quarantined.
create or replace table _accounts_typed as
select
    account_id,
    nullif(customer_id, '')                   as customer_id,
    try_cast(branch_id as integer)            as branch_id,
    account_type,
    account_status,
    try_cast(open_date as date)               as open_date,
    try_cast(interest_rate as decimal(6,4))   as interest_rate,
    currency,
    try_cast(_loaded_at as timestamp)         as _loaded_at,
    row_number() over (partition by account_id order by _loaded_at desc) as _rn
from raw_accounts;

create or replace table _accounts_classified as
select
    a.*,
    case
        when a.customer_id is null then 'null_customer_id'
        when c.customer_id is null then 'orphan_customer_id'
        when b.branch_id   is null then 'orphan_branch_id'
        when a.account_type not in ('CHECKING','SAVINGS','MONEY_MARKET','CD') then 'invalid_account_type'
    end as quarantine_reason
from _accounts_typed a
left join stg_customers c on a.customer_id = c.customer_id
left join stg_branches  b on a.branch_id   = b.branch_id      -- current-only: 1 row per branch_id
where a._rn = 1;

create or replace table quarantine_accounts as
select account_id, customer_id, branch_id, account_type, account_status, open_date,
       quarantine_reason, current_timestamp as quarantined_at
from _accounts_classified
where quarantine_reason is not null;

create or replace table stg_accounts as
select account_id, customer_id, branch_id, account_type, account_status, open_date,
       interest_rate, currency, _loaded_at
from _accounts_classified
where quarantine_reason is null;
