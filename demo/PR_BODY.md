## What changed
Adds `region` to the published `accounts` table for the regional deposits view, and
renames `account_status` → `status` to match branch-ops naming.

## Data-contract impact
- [x] Additive only → contract bumped to 1.1.0

## Join cardinality
- [ ] Every new join targets a relation unique on the join key
