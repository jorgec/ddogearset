"""DDO domain rules: XML -> effects, stat naming, bonus-type stacking, set
counting, and physical-rule validation.

The load-bearing property of this package is what it does NOT contain: no pulp,
no ILP, and no search restriction (ML window, armor/weapon style, excluded
packs, owned-items, raid cap). `optimizer.py` imports from here; nothing here
imports `optimizer`. The ETL's Transform stage (`etl/`) also imports from here —
it is the same extraction the search uses, called with keep_unmatched=True and
no candidacy filter.

See docs/0.5.0/00_ETL_START_HERE.md §7.
"""
