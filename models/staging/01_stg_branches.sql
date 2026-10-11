-- Branch reference is SCD Type 2. Grain of history = (branch_id, valid_from).
-- stg_branches exposes ONLY the current version: grain = branch_id. Join to this, never to history.
create or replace table stg_branch_history as
select
    cast(branch_id as integer)  as branch_id,
    branch_name,
    region,
    branch_manager,
    cast(valid_from as date)    as valid_from,
    cast(valid_to as date)      as valid_to,
    cast(is_current as boolean) as is_current
from raw_branches;

create or replace table stg_branches as
select branch_id, branch_name, region, branch_manager, valid_from
from stg_branch_history
where is_current;
