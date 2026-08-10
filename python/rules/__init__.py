"""DDO domain rules: XML -> effects, stat naming, bonus-type stacking, set
counting, and physical-rule validation.

The load-bearing property of this package is what it does NOT contain: no pulp,
no ILP, and no search restriction (ML window, armor/weapon style, excluded
packs, owned-items, raid cap). `optimizer.py` imports from here; nothing here
imports `optimizer`.

That is what makes "recalculation cannot inherit a search restriction" true by
construction rather than by discipline — there is no code path from this package
to one. See docs/0.5.0/01_RECALC_SPEC_AND_PHASED_PLAN.md §3.6 and Phase 2.
"""
