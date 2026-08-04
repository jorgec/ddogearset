# Plan — Duplicate Stat Visibility & Item Search by Stat

**Status:** Planning only, not implemented.
**Depends on:** Nothing from Phase 10 directly; both features are additive and can be built independently of each other.

Two independent features:

1. **Summary page**: show, per stat, how many distinct equipped sources contribute to it.
2. **New page**: browse/search all items granting a given stat, grouped by bonus type, sorted highest-to-lowest value, restricted to `max_level - 6 .. max_level`.

---

## Feature A — Duplicate Stat Sources on the Summary Page

### Scope (per user decision)

Purely a **frontend** computation over data already sent to the client today — no backend or wire-contract change. "Duplicate" means *any stat currently fed by more than one equipped source*, regardless of whether those sources legitimately stack (e.g. Filigrees) or would collide under DDO's non-stacking rule. This is a simple, honest "here's everything currently contributing to this number" view — not an attempt to model which sources are winning vs. superseded (that would require exposing non-credited sources, which the backend doesn't send today; explicitly out of scope per the chosen option).

### Data already available

- `$resultStore.allEffects: Record<string, string[]>` — keyed by stat name, each entry is an array of source strings already formatted as `"{value} {bonusType} ({sourceName})"` (see `python/optimizer.py`'s `all_effects_out` construction). **The array length for a given stat IS the source count** — no new data needed.
- `$resultStore.slots: Record<string, SlotDetail>` — per-slot `{item, augments, filigrees, set_bonus_contributions}`, used by `Summary.svelte`'s existing `locateSource()` (`Summary.svelte:69-135`) to resolve a source string back to a slot name. Reused as-is.

### Design

1. **Parsing helper** — a small function `parseEffectSource(raw: string): {value: number, bonusType: string, sourceName: string | null}` using the regex `^(-?[\d.]+)\s+(\S+)(?:\s+\((.+)\))?$` (mirrors the exact format `optimizer.py` writes: `f"{val} {b_type} ({sname})"`, with a fallback for the no-parens case `f"{val} {b_type}"` that appears when `sources_tracking` for that `(stat, bonus_type)` is empty). Put this alongside `locateSource()` in `Summary.svelte`, or extract both into a small `frontend/src/lib/utils/effectSources.ts` module if it turns out to be reused elsewhere (recommended, since Feature B's result view will likely also want per-source formatting).
2. **Derived store / computed value** — `duplicatedStats: {stat: string, sources: {value, bonusType, sourceName, slot}[]}[]`, filtered to entries where `allEffects[stat].length > 1`, sorted by source count descending (most-duplicated stats first). Computed the same way `groupedEffects` already is (`Summary.svelte:33-35`), as a reactive `$:` block.
3. **UI placement** — new collapsible section in `Summary.svelte`, using the existing `Accordion.svelte` component (already built this session for the tiered-solver form), titled something like "Duplicated Stat Sources". Each stat renders as a row: stat name, source count badge, then an expandable list of `{value} {bonusType} — {sourceName} ({slot})` lines (reusing `locateSource()` for the slot lookup exactly as the existing effect list does).
4. **No filtering by bonus type or "waste" detection** — per the chosen scope, every stat with ≥2 sources shows up, including ordinary multi-filigree Stacking stats (e.g. Ranged Power with 10 Stacking filigree sources is expected and will appear here too). The section is informational, not a warning list. Consider a short static caption clarifying this ("Stats fed by more than one equipped source — not necessarily wasted; Stacking-type bonuses are expected to have many.") so it doesn't read as an alert.

### Acceptance criteria

- AC-1: A stat with exactly 1 source in `allEffects` never appears in the duplicated-stats list.
- AC-2: A stat with N≥2 sources appears with all N sources listed, each resolved to its equipping slot via the existing `locateSource()` logic (or "Unknown" if resolution fails, matching current behavior).
- AC-3: The list is sorted by source count descending.
- AC-4: No RPC call, no `ResultPayload` field, no Go/Python change is required — verified by building and testing this feature entirely within `Summary.svelte` (+ the optional extracted util module) using only fields the frontend already receives today.
- AC-5: Section is empty/hidden gracefully when no stat has 2+ sources (e.g. `calculate_only` results with a sparse gearset).

### Effort estimate

Small — one new accordion section in an existing component, one derived computation, no backend surface. Suitable for a single builder pass.

---

## Feature B — Item Search by Stat Page

### Scope (per user decision)

New page, added to the existing tab-switch SPA (`frontend/src/App.svelte`'s `currentTab` store, `frontend/src/lib/store.ts:107` — a `writable<'solver'|'editor'|'filigrees'|'summary'>`; add a new literal, e.g. `'itemSearch'`, plus a header tab button and an `{:else if}` branch, matching how `'filigrees'` was added). Backend matching **reuses Python's `normalize_stat_name`** (per the chosen option) so search results are guaranteed consistent with what the solver itself would recognize for the same stat — no second, drifting definition of "what counts as Ranged Power."

### Why not a Go-only implementation

`docs/ITEM_DETAIL_SPEC.md` establishes INV-1: Go performs structural XML projection only and must never re-implement `normalize_stat_name` (a large heuristic function in `python/optimizer.py` handling synonyms, compound Type+Item XML tag combos, elemental spellpower groupings, etc. — see `python/optimizer.py:181-~260`). A Go-side literal-string-match implementation would silently diverge from what the solver actually matches for the same stat name, producing a "search" feature that lies about what's really usable for that priority. Reusing Python keeps a single source of truth.

### Backend design

**New solver mode: `mode: "stat_search"`**, added alongside the existing `optimize` / `calculate` / `alternatives` modes in `python/solver.py`'s `VALID_MODES` / `normalize_mode`.

Request shape (new, sent from Go via the same temp-file-payload mechanism `runSolver()` in `app.go` already uses for the other modes):

```jsonc
{
  "mode": "stat_search",
  "stat": "Ranged Power",       // a single stat name, as picked from statTaxonomy.ts
  "max_level": 34                // same field already sent for optimize/calculate;
                                  // search range is [max_level - 6, max_level], mirroring
                                  // the existing GetAvailableItems (app.go:568) pattern
}
```

**`python/solver.py` main()`** gains a `stat_search` branch (alongside the existing `alternatives` early-return branch) that:
1. Runs the *existing* `parse_items`, `parse_augments`, `parse_filigrees`, `parse_sets` with `priorities=[stat]` (exactly how every other mode already scopes parsing to the priority list — no new parsing logic, just a single-stat priority list).
2. Walks every returned item/augment/filigree's `buffs` list (already the `(stat, bonus_type, value)` tuples `normalize_stat_name` produced during parsing) and, for each buff whose `stat` matches, emits one result row.
3. Filters by `max_level - 6 <= ml <= max_level` (mirrors `app.go:568`'s existing `GetAvailableItems` range logic, ported to Python since this new mode lives there — not duplicated logic in the sense of INV-1, since matching stays Python-only; this is just an ML window is a one-line comparison, not a heuristic).
4. Sorts by value descending.

Result shape:

```jsonc
{
  "stat": "Ranged Power",
  "results": [
    {
      "sourceType": "item" | "augment" | "filigree",
      "sourceName": "Legendary Calamitous Heavy Crossbow",
      "bonusType": "Enhancement",
      "value": 23.0,
      "ml": 34,
      "slots": ["Weapon1"],           // item's equip slots, empty for augments/filigrees
      "pack": "Magic of Myth Drannor" // null for augments/filigrees (no pack concept there today)
    },
    ...
  ]
}
```

Grouped by `bonusType` and value-sorted **on the frontend**, not the backend — the backend returns one flat, value-sorted list; the page groups client-side into per-bonus-type buckets (Enhancement, Quality, Insightful, Artifact, Stacking, ...), preserving the value-descending order within each bucket. Keeping grouping client-side avoids baking a specific UI shape into the wire contract and matches how `allEffects`/`groupedEffects` already works in `Summary.svelte`.

### Go side

New RPC on `*App`, e.g. `SearchItemsByStat(stat string, maxLevel int) (StatSearchResult, error)`, following the exact same pattern as the recently-added `GetSlotAlternatives` (`app.go`): build a payload, call the shared `runSolver()` helper, unmarshal into a new `StatSearchResult` struct (mirroring `AlternativesResult`'s pattern of embedding a typed slice). Add corresponding types (`StatSearchEntry` etc.) and regenerate wails bindings, same workflow already used twice this session.

No new Go-side XML parsing, no new cache — this is a pure passthrough RPC like `RunOptimization`/`GetSlotAlternatives`, not like `GetItemDetails`/`GetSetBonus` (which are Go-native index lookups).

### Frontend design

**New page component**: `frontend/src/lib/components/domain/ItemSearch.svelte` (or similar), wired into `App.svelte`'s tab switch.

- Stat picker at the top — **reuse `StatPicker.svelte`** (built this session for the tiered-solver form) in single-select mode, since it already wraps the canonical `statTaxonomy.ts` tree with drill-down + search. No new stat-picking UI needed.
- On stat selection, call `SearchItemsByStat(stat, $configStore.max_level)`, show a loading state (this is a subprocess call, expect roughly the same latency as an `alternatives` request observed this session — low single-digit seconds, not instant).
- Results rendered as a list of collapsible sections per bonus type (using `Accordion.svelte` again), each section's rows sorted highest-to-lowest value, each row showing source name, value, ML, and (for items) equip slot(s)/pack.
- Consider a max_level input or defaulting to `$configStore.max_level` (the character's configured level) so the "6 levels below" window matches the currently-open gearset's context, consistent with how `GetAvailableItems` is already scoped elsewhere in the app.

### Acceptance criteria

- AC-1: Selecting a stat via the picker and searching returns only items/augments/filigrees whose `ml` falls in `[max_level - 6, max_level]` inclusive.
- AC-2: Results are grouped by `bonusType`, each group internally sorted by `value` descending.
- AC-3: A stat with zero matches (e.g. a mistyped custom stat with no XML data behind it) shows an empty state, not an error.
- AC-4: The same stat name searched here and used as a tier-1 priority in the solver produce consistent results — i.e. an item that shows up in this search is guaranteed to be a valid source the solver could also select for that priority (since both paths go through the same `normalize_stat_name` call). This is the core correctness guarantee motivating the "reuse Python" decision and should be spot-checked manually against a known stat during implementation.
- AC-5: `go build`/`go vet`/`go test`, `pytest python/tests/`, and `npm run check` all stay clean; wails bindings regenerated for the new RPC/types.

### Open items to decide during implementation (not blocking the plan)

- Whether filigrees/augments need a `slots`-equivalent concept for display (e.g. "usable on Weapon" vs "usable on Minor Artifact") — likely derivable from existing filigree/augment type data already parsed, worth confirming against real data during the build rather than speculating here.
- Whether a max_level override control is needed on the page itself, or whether always deriving it from the currently-loaded gearset's `max_level` is sufficient for v1.

### Effort estimate

Medium — one new Python solver mode (small, reuses existing parsing/matching), one new Go RPC + types + bindings regen (small, precedented pattern from `GetSlotAlternatives`), one new frontend page (medium, but reuses `StatPicker.svelte` and `Accordion.svelte` from this session's work). Suitable for a single builder pass per layer (Python, Go, frontend), similar to how Phase 10 was sequenced.

---

## Suggested Build Order

1. Feature A first — small, frontend-only, no dependencies, quick win.
2. Feature B — Python mode, then Go RPC, then frontend page (same dependency order Phase 10 used: backend contract before the UI that consumes it).
