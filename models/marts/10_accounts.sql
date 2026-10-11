-- PUBLISHED INTERFACE. Governed by contracts/accounts.yml.
-- Region comes from stg_branches (current version only: unique on branch_id), so this
-- join cannot change row count. test_enrichment_preserves_account_cardinality proves it.
create or replace table accounts as
select
    a.account_id,
    a.customer_id,
    a.branch_id,
    a.account_type,
    a.account_status,
    a.open_date,
    a.interest_rate,
    a.currency,
    a._loaded_at,
    b.region
from stg_accounts a
join stg_branches b
    on a.branch_id = b.branch_id;
