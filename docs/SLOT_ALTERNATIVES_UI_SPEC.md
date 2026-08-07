# Spec — Per-Slot "Find Alternatives" Icon in Gearset Editor

**Status:** Implemented (`SlotAlternatives.svelte`, wired into `GearsetEditor.svelte`).
Verified end-to-end against a real saved gearset (10 ranked alternatives returned with
stat deltas) — see the "Decisions" section below for what shipped exactly as specified.
One implementation-time gotcha worth recording: the drawer component's slot-name prop
could NOT be called `slot` — that's a reserved Svelte attribute for named-slot content
projection, and `slot={...}` on a component is silently swallowed by the compiler
instead of reaching a prop of that name. Named `targetSlot` instead.

## Goal

In the Gearset Editor, add a gear icon next to each equipment slot row. Clicking it
finds 3–10 substitute items for that slot only — respecting the Trove owned-items
restriction if loaded — without re-running the full gearset optimization.

## Important finding before any of this gets built

**The backend for this already exists and is fully functional — it's just never been
called from the frontend.** `GetSlotAlternatives` (`app.go:702`), `AlternativesPayload`/
`AlternativesResult` (`app.go:417`, `454`), and the Python side (`solver.py`'s
`run_alternatives`, `optimizer.py`'s `find_slot_alternatives`) are all real, working
code — confirmed via source, not assumed. `grep` across `frontend/src` for
`GetSlotAlternatives`/`AlternativesPayload`/`alternatives` returns **zero** hits outside
the auto-generated Wails bindings. This is 100% new frontend work sitting on top of a
100% ready backend.

**One requirement can't be met as stated: "use the global search-time setting."**
`find_slot_alternatives` is enumeration-based, not an ILP solve — it locks every other
slot to the current gearset and scores each legal candidate for the target slot
directly (`optimizer.py:2351`, docstring: "requiring no ILP at all"). `max_search_time`
travels on the wire (because `AlternativesPayload` embeds the full `OptimizationPayload`)
but is never read on this code path (confirmed: only used at `solver.py:578`, inside the
non-alternatives branch that mode=="alternatives" returns before reaching). Practically
this means: **there's no time budget to set for this feature** — it runs in whatever time
enumeration takes, which the existing "cold-callable" framing suggests is fast regardless
of `max_search_time`. Nothing to configure; nothing broken by omitting it. Flagging so
this isn't silently glossed over.

The Trove/owned-items part of the ask, by contrast, needs **zero extra work** —
`owned_item_names` filtering happens in `parse_items`/`parse_augments` before the mode
dispatch (`solver.py`, confirmed before `mode == "alternatives"` check at `solver.py:568`),
so it's already applied to whatever candidate pool `find_slot_alternatives` sees. Spreading
`$configStore` (which already carries `owned_item_names`, kept live by
`JobConfigurationForm.svelte:40-42` regardless of which tab is mounted) into the payload
is all that's needed.

## UI

### Icon placement

`GearsetEditor.svelte`'s per-slot row (`baseSlots` loop, ~line 296) currently renders:
`[slot label] [item name button, or "Empty Slot" button] [X clear-icon button]`. Add the
new gear icon as a third button in that row, after the clear icon — inline hand-drawn SVG
matching the existing X-icon convention (no icon library dependency; none is installed).

Shown for **every** slot row, filled or empty — not just filled ones. Rationale:
`AlternativesPayload.current_item` already accepts `""` for an empty slot (the Go doc
comment explicitly supports "a hand-assembled gearset from the editor," which includes
gaps), so "suggest something for this empty slot" is the same call shape as "suggest a
replacement for this filled slot," just with an empty baseline. Confirm before building —
if you'd rather scope this to filled slots only for v1, that's a one-line condition.

### Trigger → call

```ts
const result = await GetSlotAlternatives({
  ...$configStore,
  target_slot: slot,
  current_item: $resultStore.gearSet[slot] ?? "",
  equipped_items: $resultStore.gearSet,
  count: 10,
  mode: 'alternatives',
} as unknown as main.AlternativesPayload);
```

Spreading `$configStore` carries `owned_item_names`, `stat_priorities`, `build_type`,
`excluded_packs`, etc. automatically — same pattern already used for `RunOptimization`
calls (`JobConfigurationForm.svelte:110`, `GearsetEditor.svelte:262`). `count: 10` is
proposed as a fixed value (Go clamps to [3,10] regardless, Python defaults to 5 if
absent) — no picker UI, since the ask was "3–10 suggestions," not "let the user choose
how many." Open question: confirm 10 is right, or if a smaller fixed number (e.g. 5) is
preferred to keep the result list short.

### Result presentation (net new — nothing today renders `AlternativeItem`)

A slide-in drawer (matching the existing `OwnedItems.svelte`/`ItemDetail.svelte` drawer
pattern — `svelte/transition`'s `fly`/`fade`, not a CSS class toggle) opens on click,
showing:
- Header: slot name, loading spinner while the call is in flight.
- A ranked list (`AlternativesResult.alternatives`, already sorted by `rank`): item name,
  ML, raid badge if `isRaid`, and the per-priority `statDeltas` vs. the current baseline
  (e.g. "+12 Melee Power, −3 PRR" relative to what's equipped now) — this is the
  actionable "why is this better/worse" info the backend already computes but nothing
  displays yet.
- Empty state: `Success: true` with zero alternatives is valid ("no legal candidates"),
  not an error — show "No alternatives found for this slot" rather than treating it as a
  failure.
- Error state: `Success: false` / `ErrorMessage` set — show the message, same toast/error
  convention used elsewhere in this app.

### Equip interaction

Clicking a suggestion in the list equips it, reusing the exact pattern
`GearsetEditor.svelte`'s existing `selectItem()` (line 152) already uses for the
item-search flow:
```ts
$resultStore.gearSet[slot] = alt.itemName;
$configStore.pre_equipped[slot] = alt.itemName;
delete $configStore.pre_filled_augments[slot]; // old item's augments no longer apply
$resultStore.gearSet = {...$resultStore.gearSet};
$configStore.pre_equipped = {...$configStore.pre_equipped};
$configStore.pre_filled_augments = {...$configStore.pre_filled_augments};
```
Whether to also apply `alt.augments`/`alt.filigrees` (the backend already computed an
optimal augment/filigree assignment for that candidate, per `AlternativeItem.augments`/
`filigrees`) or leave those slots for the user to fill in separately is an open design
question — applying them directly is more useful but a bigger behavioral change (silently
overwrites whatever augments were in those slots). Recommend applying them, since they're
computed specifically for this candidate and leaving them off would show a stat preview
the user then can't actually get without redoing that work by hand — but flagging as a
decision point, not assuming.

## Decisions (confirmed)

1. **Icon shown on empty slots too**, not just filled ones — as proposed.
2. **No count picker.** Always request `count: 10` (the backend's own max); it may
   return as few as 3 or fewer legal candidates, which is a valid non-error result
   (empty-state handling below still applies for zero).
3. **Equipping a suggestion applies its `augments`/`filigrees` too**, not just the bare
   item — as proposed.
4. **Confirm before equipping** (this is a change from the existing no-confirm
   `selectItem()` item-search flow, deliberately — alternatives is a bigger, less
   deliberate action than manually browsing/picking an item). After confirming and
   equipping, keep the item that was replaced available as a one-click "Restore"
   action — same shape as the existing stat-set-apply Undo pattern
   (`StatSetPicker.svelte`'s `applySet`/`showToast(..., [{label: 'Undo', ...}])`),
   reused here as a "Restore" action instead of "Undo" since it's restoring a specific
   prior item rather than reverting a batch of priority changes. The toast holds the
   pre-swap slot state (item name + its augments/filigrees) and writes it straight back
   into `pre_equipped`/`pre_filled_augments`/`pre_filled_filigrees` on click, mirroring
   how the undo snapshot already works for stat-set applies.

## Out of scope for this pass

- No changes to the backend — `GetSlotAlternatives`, `find_slot_alternatives`,
  `run_alternatives` are unmodified; this is purely wiring a UI onto an existing RPC.
- No search-time/budget control, per the finding above.
