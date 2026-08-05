# Spec — Constrain Gearset Generation to Owned Items (Trove Inventory Import)

**Status:** Ready to implement, not yet built.
**Depends on:** Nothing — additive filter, same shape as the existing `excluded_packs`/
`armor_restriction` filters already wired through the whole stack.

## Goal

Let the user import a Trove inventory export (CSV) and constrain the solver to only
select items/augments they actually own, instead of the full DDOBuilderV2 catalog.

## Scope, as decided across planning discussion

- **In scope:** named items and augments, matched by exact name against DDOBuilderV2.
- **Explicitly out of scope:** filigree matching (Trove's filigree names don't include
  tier/value and don't match DDOBuilderV2's naming format at all — confirmed 0% match
  rate on a real export; not attempted), and random/procedural loot items (names like
  `+1 Deflecting 2 Hide of Light Resistance 3` encode properties directly and have no
  corresponding DDOBuilderV2 entry to match against — structurally unsolvable without a
  separate name-parsing project).
- **DDOBuilderV2 is the definitive source.** Any CSV row whose `Name` doesn't match the
  corpus is silently ignored — no fuzzy matching, no error, no report. This is a
  deliberate simplicity choice, not a placeholder for future work.

## Row filtering (established via real-data validation this session)

```
Location != "SharedCrafting"
AND (Binding column absent OR Binding ∈ {"BtA", "BtC"})
AND Name matches a DDOBuilderV2 item or augment name exactly (else dropped)
```

**Column guarantees, per Trove:** only `SubscriptionHash`, `Character`, `Location`,
`Tab`, and `Name` are guaranteed present in an export. `Binding` (and everything else,
e.g. `Quantity`) is not. `Location` and `Name` are therefore required — a CSV missing
either is rejected outright — but `Binding` is read defensively: applied when the
column exists, skipped entirely (no rows excluded on its account) when it doesn't,
rather than erroring on the whole file or silently producing an empty result.

A `":"`-in-name heuristic to pre-filter obvious filigree rows was considered and
rejected — DDOBuilderV2 has ~25 legitimate items with `:` in their names (e.g.
`Legendary Prototype I: Siren Test`, `Page Regalia: Blasphemer's Manuscript`), so the
heuristic risked silently excluding real, ownable items. It's also redundant: filigree
rows already fail the exact-name match on their own (0% match rate verified), so
nothing is gained by filtering them earlier.

**Validated against a real 420-row export** (`TroveExport.Inventory.csv`):
`Location != SharedCrafting` + `Binding ∈ {BtA, BtC}` → 228 rows / 190 distinct names →
81.7% of the non-filigree, non-random-loot names matched DDOBuilderV2 exactly. The
`Binding` filter alone improved match quality substantially (65.3% → 81.7%) since bound
items skew toward real named gear while unbound rows are mostly tradeable
commodities/currency — a side benefit, not just a scope reduction.

## Design

### 1. CSV parsing (Go)

New file, e.g. `trove_inventory.go`, mirroring the structure of `ddobuilder_fetch.go`
(a focused, single-purpose file rather than growing `app.go` further).

```go
type TroveInventoryItem struct {
    Character string
    Location  string
    Name      string
    Binding   string
}

// ParseTroveInventoryCSV reads a Trove export and returns the deduplicated set of
// item/augment names that pass the Location/Binding filter above. Matching against
// DDOBuilderV2 happens later (Python side, see §2) — this function only applies the
// CSV-level filters and produces a plain name set.
func ParseTroveInventoryCSV(path string) (map[string]bool, error)
```

Uses Go's stdlib `encoding/csv` — no new dependency. Header row gives column names;
read by name (not fixed column index) so a future Trove export format change with
reordered columns doesn't silently break parsing.

### 2. Wire contract

New RPC, following the existing `GetAvailableItems`-style pattern:

```go
func (a *App) LoadTroveInventory(csvPath string) (TroveInventoryResult, error)

type TroveInventoryResult struct {
    Success      bool     `json:"success"`
    ErrorMessage string   `json:"errorMessage,omitempty"`
    TotalRows    int      `json:"totalRows"`
    OwnedNames   []string `json:"ownedNames"`   // post CSV-filter, pre DDOBuilderV2 match
}
```

`OptimizationPayload` gains one new field, matching `ExcludedPacks`'s existing shape:

```go
OwnedItemNames []string `json:"owned_item_names,omitempty"`  // empty/absent = unrestricted
```

**Important UX default, per earlier discussion:** an empty/absent `owned_item_names` means
*no restriction* (today's full-catalog behavior), not "own nothing." This avoids an
empty-item-pool footgun for anyone who hasn't loaded a CSV — the restriction is opt-in
per solve, not a standing mode that silently activates.

### 3. Python — filter application

`python/solver.py` reads `owned_item_names` the same way it reads `excluded_packs`
today (`parsed_data.get('owned_item_names', [])`), passes it down to
`optimizer.parse_items`/`parse_augments`.

`python/optimizer.py`'s `parse_items`/`parse_augments` each gain one more optional
parameter (`owned_names: set[str] | None = None`) and one more `if` alongside the
existing pack-exclusion check:

```python
if owned_names is not None and name not in owned_names:
    continue
```

This is the entire matching logic — deliberately just a Python `set` membership check,
no normalization, no fuzzy matching, consistent with "DDOBuilderV2 is definitive, exact
match or silently drop" from the scope decision above. Applied identically to both
`parse_items` and `parse_augments` (filigrees are never touched, per scope).

### 4. Frontend

- A file picker in `JobConfigurationForm.svelte` (new accordion section, or folded into
  an existing one — likely its own small section given it's a standalone toggle) calling
  `LoadTroveInventory`, showing `TotalRows` and the count of names that came out the
  other side of the CSV-level filter (not yet matched against DDOBuilderV2 — that only
  happens at solve time, so there's no "N matched" count available until a solve runs).
- A toggle: "Only use items I own" — disabled/unchecked by default, and disabled
  entirely (not just unchecked) until a CSV has been loaded, so it can't be silently
  turned on with nothing behind it.
- `configStore` gains `owned_item_names: string[]` (empty array by default), sent as-is
  in `OptimizationPayload` — empty array serializes the same as "not restricted" per
  the backend default above.
- No "match report" UI in this pass — unmatched names are silently dropped per scope,
  consistent with there being no reporting requirement decided for this feature.

## Acceptance criteria

- AC-1: A CSV row with `Location == "SharedCrafting"` never contributes a name to the
  owned-names set.
- AC-2: A CSV row with `Binding` other than `BtA`/`BtC` (including `"None"` and empty)
  never contributes a name, PROVIDED the `Binding` column exists at all — it isn't
  guaranteed by Trove, so when the column is absent this filter is skipped rather than
  excluding every row (or erroring the whole file).
- AC-3: With `owned_item_names` empty or absent, solver behavior is byte-identical to
  today (full catalog, no restriction) — this is a regression guard, not just a default.
- AC-4: With `owned_item_names` populated, `parse_items`/`parse_augments` return only
  entries whose `name` is in the set; no partial/fuzzy matches.
- AC-5: A name in the CSV that doesn't exist in DDOBuilderV2 causes no error and no
  entry — verified against the real 420-row export at implementation time, using the
  same match-rate methodology already validated during planning (~65–82% depending on
  exact filter combination).
- AC-6: Loading a new CSV replaces the previous owned-names set entirely (no
  accumulation across multiple loads in one session).

## Edge cases

- EC-1: Empty CSV (header only) → `TotalRows: 0`, `OwnedNames: []`, toggle stays
  disabled (nothing to restrict to).
- EC-2: CSV with a BOM or different line-ending convention (Trove exports have shown a
  UTF-8 BOM in testing) — Go's `encoding/csv` handles this natively as long as the BOM
  is stripped before the reader is constructed; verify explicitly rather than assuming.
- EC-3: Duplicate rows for the same name (e.g. owning 2 of the same ring on different
  characters) — collapse to a single set entry; quantity is irrelevant to this feature
  (the solver doesn't model "you only have one, so it can't also be in a different
  slot" — out of scope, matches how the app already treats the catalog as infinite
  supply).
- EC-4: A name that matches a DDOBuilderV2 *augment* rather than an *item* (or both) —
  both `parse_items` and `parse_augments` apply the same filter independently, so a
  name matching only one still restricts correctly on that side.

## Effort estimate (unchanged from planning discussion)

**Small–Medium, ~1–2 days.** No open design risk remaining — filigree matching and
random-loot handling (the two things that would have made this Medium–Large) are both
explicitly out of scope. Backend plumbing mirrors the existing `excluded_packs` filter
almost exactly; the only genuinely new code is the CSV parser itself.
