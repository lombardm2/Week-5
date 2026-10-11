-- A non-key attribute that fails its type cast is NULLED and LOGGED to dq_issues.
-- (The customer still exists; quarantining them would orphan real accounts.)
create or replace table _customers_typed as
select
    customer_id,
    first_name,
    last_name,
    date_of_birth                          as date_of_birth_raw,
    try_cast(date_of_birth as date)        as date_of_birth,
    segment,
    try_cast(home_branch_id as integer)    as home_branch_id,
    try_cast(created_at as timestamp)      as created_at
from raw_customers;

create or replace table dq_issues as
select 'stg_customers' as table_name, customer_id as record_key, 'date_of_birth' as column_name,
       date_of_birth_raw as raw_value, 'type_cast_failed:DATE' as issue
from _customers_typed
where date_of_birth is null and coalesce(date_of_birth_raw, '') <> '';

create or replace table stg_customers as
select customer_id, first_name, last_name, date_of_birth, segment, home_branch_id, created_at
from _customers_typed;
