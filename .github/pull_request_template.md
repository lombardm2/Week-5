## What changed

## Data-contract impact
- [ ] No change to the published `accounts` interface
- [ ] Additive only (new column / tightened constraint) → contract MINOR bump
- [ ] Breaking (remove/rename/retype/relax) → contract MAJOR bump, changelog migration note, consumer sign-off, 30-day deprecation

## Join cardinality
- [ ] Every new join targets a relation unique on the join key (state which test proves it)

## Evidence
`make gate` output / CI link:
