# Technical Specification — Item Detail Component + Go Display Parsing

**Branch:** `feature/tiered-priority-solver`
**Scope:** `internal/models/models.go`, `internal/services/parser.go`, `internal/services/enrichment.go`, `app.go`, new `frontend/src/lib/services/itemCatalog.ts`, new `frontend/src/lib/components/domain/ItemDetail.svelte`, `frontend/src/lib/components/domain/GearsetEditor.svelte`
**Explicitly independent of:** `docs/PHASE10_PLAN.md` (the tiered solver rework) — no file overlap, no wire-contract dependency in either direction. This can be built before, after, or in parallel with Phase 10.
**Status:** Planning only — no implementation yet.

---

## 1. Overview and invariants

Today the frontend receives a thin `XMLItem` (`Name`, `Description`, `MinLevel`, `EquipmentSlot`, `DropLocations`, `ItemAugments[].Type`, `MinorArtifact`) and renders it by dumping DDOBuilder's own `Description` HTML via `{@html}` (`GearsetEditor.svelte:468-475`). There is no structured stat data, no augment-choice detail, no set-bonus detail, anywhere in the Go→frontend pipeline. This spec adds real structural parsing on the Go side and a reusable `ItemDetail.svelte` component that renders it.

### 1.1 Non-negotiable invariants

| ID | Invariant |
|---|---|
| **INV-1** | Go performs **structural projection only** — it mirrors what the XML says. It never re-implements `python/optimizer.py`'s `normalize_stat_name` matching heuristic or DDO's bonus-type stacking rules (`stacking`/`mythic`/`reaper` vs. max-of-one). Those stay single-sourced in Python. This is the load-bearing design decision of this spec — see §2.1. |
| **INV-2** | Every new scalar field added to a Go XML-parsed struct is `string`, not a typed `int`/`float`. Untyped-string parsing cannot fail on a malformed value; a typed field can, and per INV-3 that must never take down the whole cache. |
| **INV-3** | A single malformed field in a single `.item`/`.xml` file must never wipe the entire cache. Each parser walks its directory tolerating individual file failures (§3). |
| **INV-4** | The component always renders *something* useful from `itemName` alone. Richer context (`slotDetail`) is a pure enhancement, never a requirement — see §5. |
| **INV-5** | The "solver-credited" cross-reference (§6) is sourced only from `resultStore.slots` (Phase 9.2 data, the actual solve's output) — Go/the component never re-derives DDO stacking rules to compute it themselves. |

---

## 2. Go model additions (`internal/models/models.go`)

### 2.1 Why Go does not port `normalize_stat_name`

Measured from the real corpus (8,779 item files): 32,381 total `<Buff>` elements, of which 5,089 carry `Type` only (no value, no bonus type — Python's `parse_items` skips these because it requires `b_val and b_bonus`) and 3,182 more carry `Type`+`Item`+`Description1` with no value (also skipped). Roughly **25% of all item buffs are invisible to the solver by design.** Go's job is to show all of it; Python's job is to match a filtered subset against the user's priorities. These are different outputs from the same input, not two implementations of the same function — porting the matcher would be duplicating logic that must, by design, produce a different result.

### 2.2 New types

```go
// XMLBuff mirrors <Buff> verbatim. All scalar fields are strings — see INV-2.
type XMLBuff struct {
    Type          string `xml:"Type"`
    Item          string `xml:"Item"`
    Description1  string `xml:"Description1"`
    Value1        string `xml:"Value1"`
    Value2        string `xml:"Value2"`
    BonusType     string `xml:"BonusType"`
}

// XMLRequirement mirrors <Requirement> (nested under <Effect><Requirements>).
type XMLRequirement struct {
    Type string `xml:"Type"`
    Item string `xml:"Item"`
}

// XMLEffect mirrors <Effect>. Types is a slice because a single <Effect> may
// repeat <Type> (see WeaponOtherDamageBonus + WeaponOtherDamageBonusCritical
// pattern documented in docs/PHASE10_PLAN.md's proc research).
type XMLEffect struct {
    Types        []string         `xml:"Type"`
    Bonus        string           `xml:"Bonus"`
    Item         string           `xml:"Item"`
    AType        string           `xml:"AType"`
    Amount       string           `xml:"Amount"`
    Requirements []XMLRequirement `xml:"Requirements>Requirement"`
}

// XMLEmbeddedAugment mirrors <Augment> nested inside <ItemAugment> — an
// item-specific upgrade/crafting choice, distinct from the generic color-slot
// augment system (XMLAugment). SetBonus is populated only when choosing this
// specific augment grants set membership (the "conditional set bonus" case —
// see §2.4).
type XMLEmbeddedAugment struct {
    Name          string      `xml:"Name"`
    Description   string      `xml:"Description"`
    MinLevel      string      `xml:"MinLevel"`
    Icon          string      `xml:"Icon"`
    GrantAugment  string      `xml:"GrantAugment"`
    SetBonus      string      `xml:"SetBonus"`
    Effects       []XMLEffect `xml:"Effect"`
}

// XMLBaseDice mirrors <BaseDice>.
type XMLBaseDice struct {
    Number string `xml:"Number"`
    Sides  string `xml:"Sides"`
}
```

### 2.3 `XMLItem` additions

```go
type XMLItem struct {
    // --- existing fields, unchanged ---
    Name          string           `xml:"Name"`
    Description   string           `xml:"Description"`
    MinLevel      int              `xml:"MinLevel"`
    EquipmentSlot XMLEquipmentSlot `xml:"EquipmentSlot"`
    DropLocations []string         `xml:"DropLocation"`
    ItemAugments  []XMLItemAugment `xml:"ItemAugment"`
    MinorArtifact *string          `xml:"MinorArtifact"`
    RawXML        string           `xml:",innerxml" json:"-"`

    // --- new: structural projection ---
    Icon          string      `xml:"Icon"`
    Material      string      `xml:"Material"`
    SetBonuses    []string    `xml:"SetBonus"`   // top-level, unconditional set membership
    Buffs         []XMLBuff   `xml:"Buff"`
    Effects       []XMLEffect `xml:"Effect"`      // item-level clickies/SLAs (676 items corpus-wide)

    // --- new: weapon profile (present only when Weapon != "") ---
    Weapon               string        `xml:"Weapon"`
    AttackModifier        string       `xml:"AttackModifier"`
    DamageModifier         string      `xml:"DamageModifier"`
    DRBypass               []string    `xml:"DRBypass"`
    WeaponDamage            string     `xml:"WeaponDamage"`
    BaseDice                *XMLBaseDice `xml:"BaseDice"`
    CriticalMultiplier      string     `xml:"CriticalMultiplier"`
    CriticalThreatRange     string     `xml:"CriticalThreatRange"`

    // --- new: armor profile (present only when Armor != "") ---
    Armor                  string      `xml:"Armor"`
    ArmorBonus              string     `xml:"ArmorBonus"`
    ShieldBonus              string    `xml:"ShieldBonus"`
    MaximumDexterityBonus     string   `xml:"MaximumDexterityBonus"`
    ArcaneSpellFailure         string  `xml:"ArcaneSpellFailure"`
    ArmorCheckPenalty           string `xml:"ArmorCheckPenalty"`

    // --- new: acquisition enrichment, computed once at cache-load time, not parsed from this item's own XML ---
    PackID  string `xml:"-" json:"pack_id,omitempty"`
    WikiURL string `xml:"-" json:"wiki_url,omitempty"`
    IsRaid  bool   `xml:"-" json:"is_raid,omitempty"`
    RaidName string `xml:"-" json:"raid_name,omitempty"`
}
```

**Rationale for `*XMLBaseDice`** (pointer, not value): distinguishes "no `<BaseDice>` element" from "`<BaseDice>` present but empty," which the component needs to decide whether to render the Weapon Profile's dice line at all.

**Rationale for `PackID`/`WikiURL`/`IsRaid`/`RaidName` living on `XMLItem` itself** rather than a wrapper/second type: `GetItemDetails` already returns a bare `XMLItem`; adding fields here means zero new RPC and zero new frontend type to compose. They are computed once when the cache builds (§4.3), not per-request.

### 2.4 `XMLItemAugment` additions

```go
type XMLItemAugment struct {
    Type                string                `xml:"Type"`               // existing — color/slot type

    // --- new ---
    SelectedAugment     string                `xml:"SelectedAugment"`     // default choice, when present (115 items corpus-wide)
    SelectedLevelIndex  string                `xml:"SelectedLevelIndex"`
    Augments            []XMLEmbeddedAugment  `xml:"Augment"`             // embedded upgrade/crafting choices (1,970 items corpus-wide)
}
```

### 2.5 `XMLAugment` and `XMLFiligree` additions

```go
type XMLAugment struct {
    Name        string      `xml:"Name"`
    Description string      `xml:"Description"`
    Types       []string    `xml:"Type"`
    MinLevel    int         `xml:"MinLevel"`
    Effects     []XMLEffect `xml:"Effect"`   // NEW
    RawXML      string      `xml:",innerxml" json:"-"`
}

type XMLFiligree struct {
    Name        string      `xml:"Name"`
    Description string      `xml:"Description"`
    Menu        string      `xml:"Menu"`
    SetName     string      `json:"SetName"`
    Effects     []XMLEffect `xml:"Effect"`   // NEW — retains <Rare>-tagged effects for display
    RawXML      string      `xml:",innerxml" json:"-"`
}
```

**On `<Rare>`:** Python's `parse_filigrees` (`optimizer.py:328-332`) explicitly skips any `<Effect>` containing a `<Rare/>` marker when computing solver-relevant buffs (the upgraded variant isn't an additional stacking bonus — see `docs/PHASE9_PLAN.md` Phase 9.0). **Go's `Effects` field keeps every effect, Rare-tagged or not** — this is a display concern, and a user should be able to see that a filigree has a Rare variant even though the solver treats it as a single alternate value, not a stack. The component labels Rare-tagged effects distinctly (§7, Set Bonuses / Stats & Buffs rendering rules) rather than omitting them or conflating them with the base effect.

### 2.6 Set bonuses — replacing dead/wrong code

`internal/models/models.go`'s current `XMLSetData`/`XMLSet` targets the wrong XML shape (`<Sets><Set><Name>`; the real file `SetBonuses.xml` is `<SetBonuses><SetBonus><Type>`). `ParseSets` is never called from `app.go` — no `setsCache` exists today. **Replace, do not extend:**

```go
type XMLSetBonusData struct {
    XMLName   xml.Name       `xml:"SetBonuses"`
    SetBonuses []XMLSetBonus `xml:"SetBonus"`
}

type XMLSetBonus struct {
    Type  string       `xml:"Type"`
    Icon  string        `xml:"Icon"`
    Tiers []XMLSetTier `xml:"Buff"`
}

type XMLSetTier struct {
    EquippedCount string      `xml:"EquippedCount"`
    Description   string      `xml:"Description"`
    Effects       []XMLEffect `xml:"Effect"`
}
```

`FiligreeSets/*.xml`'s own inline `<SetBonus><Type>...</Type></SetBonus>` (currently `models.XMLSetBonus{Type}` at `models.go:52-54`, used by `XMLFiligreeData`) is a **separate, smaller type** — do not conflate it with the new top-level `XMLSetBonus` above; rename the existing inline one to `XMLFiligreeSetRef` to avoid a name collision, and give it its own `Tiers []XMLSetTier` field so filigree-set-bonus tiers render through the identical `SetBonusPanel` UI piece (§7) as item/armor set bonuses:

```go
// XMLFiligreeSetRef is the inline <SetBonus> block inside a *.Filigree.xml
// file's root — distinct from the standalone SetBonuses.xml entries.
type XMLFiligreeSetRef struct {
    Type  string       `xml:"Type"`
    Tiers []XMLSetTier `xml:"Buff"`
}
```

`XMLFiligreeData.SetBonus` changes type from `XMLSetBonus` to `XMLFiligreeSetRef`.

### 2.7 Conditional set-bonus membership — display it, do not fix the solver to match

One real example item (`+7 Combustion Epic Scorched Dagger`) has `<SetBonus>Epic Elemental Evil Set</SetBonus>` **nested inside `<ItemAugment><Augment>`** — i.e. the game grants that set membership only if that specific upgrade is chosen. `XMLEmbeddedAugment.SetBonus` (§2.2) carries this; the component must label it "conditional — requires the '…' upgrade" rather than presenting it as an unconditional property of the base item (§7).

**Known, separate, pre-existing divergence — record, do not fix here:** `python/optimizer.py:170`'s `parse_items` collects set-bonus membership via `item_node.findall('.//SetBonus')` — a **recursive** descendant search that does not distinguish top-level from `<ItemAugment><Augment>`-nested `<SetBonus>` tags. The solver therefore **currently credits this conditional set bonus unconditionally, for every such item, regardless of which upgrade (if any) is selected.** This is a genuine solver bug, entirely independent of this spec — it exists today, is not introduced by anything here, and displaying set membership correctly (conditionally) in the new panel will cause the panel to visibly disagree with the solver's actual behavior on these specific items. **Do not attempt to reconcile the two in this pass.** Record this as a deferred/known-issue item in `docs/PHASE9_PLAN.md` or an equivalent known-issues doc; fixing the solver's `.//SetBonus` search to respect the augment-choice condition is out of scope here.

---

## 3. Parser changes (`internal/services/parser.go`)

### 3.1 Prerequisite fix: per-file fault tolerance (mandatory, blocks everything else)

**Current behavior (bug):** `ParseItems`/`ParseAugments`/`ParseFiligrees`/`ParseSets` each `return err` from inside their `filepath.Walk` callback on any single file's `xml.Unmarshal` failure. Returning a non-nil error from a `filepath.WalkFunc` **aborts the entire walk**. `app.go`'s cache-loading (`startup()`) only checks `if err == nil` before assigning the result — so **one malformed field in any one of 8,779 item files yields zero cached items and a silently empty UI**, with no error surfaced anywhere the user would see it. This is pre-existing and becomes a live risk the moment typed-but-string-safe fields are added, since more struct surface area means more chances for an XML shape the parser doesn't expect (still safe per INV-2 — a mismatched *type* can't happen since everything is `string` — but a structurally unexpected document, e.g. truncated XML, still fails `xml.Unmarshal` entirely for that file).

**Required fix**, applied uniformly to `ParseItems`, `ParseAugments`, `ParseFiligrees`, and the new set-bonus parser (§3.2):

```go
// ParseItems scans the given directory for .item files, unmarshals them, and
// returns the successfully-parsed items plus the list of files that failed to
// parse (logged by the caller, never fatal to the walk).
func ParseItems(directory string) ([]models.XMLItem, []string, error) {
    var allItems []models.XMLItem
    var skipped []string

    err := filepath.Walk(directory, func(path string, info os.FileInfo, err error) error {
        if err != nil {
            return err // a filesystem-level walk error (permissions, etc.) still aborts — this is not an XML-content error
        }
        if info.IsDir() || !strings.HasSuffix(info.Name(), ".item") {
            return nil
        }
        bytes, readErr := os.ReadFile(path)
        if readErr != nil {
            skipped = append(skipped, path)
            return nil // skip this file, continue the walk
        }
        var data models.XMLItemData
        if unmarshalErr := xml.Unmarshal(bytes, &data); unmarshalErr != nil {
            skipped = append(skipped, path)
            return nil // skip this file, continue the walk
        }
        allItems = append(allItems, data.Items...)
        return nil
    })

    return allItems, skipped, err
}
```

Same pattern for `ParseAugments`, `ParseFiligrees`. The new set-bonus parser (§3.2) follows it from the start. **`err` returned from the function is now only ever a genuine filesystem-level walk error** (directory doesn't exist, permission denied) — never an XML content error, since those are now caught and added to `skipped` instead of propagated.

### 3.2 New: `ParseSetBonuses`

```go
func ParseSetBonuses(directory string) ([]models.XMLSetBonus, []string, error) {
    // same fault-tolerant filepath.Walk pattern as §3.1, targeting *.xml files
    // under directory (SetBonuses.xml itself), unmarshaling into
    // models.XMLSetBonusData, returning .SetBonuses.
}
```

### 3.3 `ParseSets`/`XMLSetData`/`XMLSet` — deleted

These target the wrong XML shape and have zero callers today. Delete them outright rather than leaving unreferenced dead code alongside the new, correct `ParseSetBonuses`/`XMLSetBonus`.

---

## 4. `app.go` changes

### 4.1 New cache fields on `App`

```go
type App struct {
    ctx            context.Context
    logs           []string
    solverPath     string
    itemsCache     []models.XMLItem
    augmentsCache  []models.XMLAugment
    filigreesCache []models.XMLFiligree
    setBonusCache  []models.XMLSetBonus   // NEW

    itemsByName    map[string]int          // NEW — name -> index into itemsCache
    augmentsByName map[string]int          // NEW
    filigreesByName map[string]int         // NEW
    setsByName     map[string]int          // NEW

    initOnce       sync.Once
}
```

### 4.2 Index construction — extracted into one shared helper

All four caches follow the identical "parse, then build a name index" pattern. Add:

```go
func buildNameIndex[T any](items []T, nameOf func(T) string) map[string]int {
    idx := make(map[string]int, len(items))
    for i, it := range items {
        idx[nameOf(it)] = i
    }
    return idx
}
```

Called once after each `Parse*` call in both `startup()` and `UpdateExternalSources()` (§4.4). Requires Go generics (module already targets a Go version supporting them — confirm via `go.mod`'s `go` directive during implementation; if it predates 1.18, write four non-generic near-duplicates instead — a trivial fallback, not a blocker).

**Duplicate names:** if two items/augments/filigrees/sets share an exact name (should not happen given DDO's naming, but not structurally guaranteed by the XML), the index keeps whichever occurs **last** in parse order — document this as the tiebreak, don't treat it as an error. `GetItemDetails` today already has this same silent behavior (`app.go:247-254`'s linear scan returns the first match, not last — **note this is a minor behavior change**, first-match to last-match; acceptable since duplicate names are not expected to occur in practice, and no test should depend on which one wins).

### 4.3 `startup()` changes

- Wire `services.InitEnrichment` before any `EnrichItem`-derived field is populated. **New finding: `InitEnrichment` is never called anywhere in the current codebase** — it is itself dead/unwired code today, alongside its sibling `EnrichItem`. `internal/services/enrichment_test.go` exercises `EnrichItem` directly via `InitEnrichmentForTest`, but nothing in `app.go` calls the real `InitEnrichment`.
- `data/PackMappings.json` exists in the repo and can be wired immediately (`services.InitEnrichment("data/PackMappings.json", raidsPath)`).
- **`raidsPath` has no corresponding file anywhere in the repo.** `InitEnrichment` requires and unmarshals a JSON array of raid-name strings from this path, and no such file exists — grepping the repo confirms it. Building a raids list is a data-sourcing task outside this spec's scope (the natural source would be replicating Python's `parser.parse_quests`' `is_raid` detection in Go, which is real, separate work).
- **Resolution for this spec: call `InitEnrichment` with `packMappingsPath` wired to `data/PackMappings.json` and gate raid detection off entirely** — pass an empty/nonexistent raids source and treat a load failure for *that specific file* as non-fatal (log and continue with `raids = nil`, meaning `EnrichItem`'s raid loop simply never matches, `IsRaid` stays `false` for everything). This requires a small change to `InitEnrichment` itself: currently a raid-file load failure makes the whole function return an error, which would also block pack-mapping enrichment. Split it — pack-mapping load failure is still fatal (return error), raids-file load failure is not (log, set `raids = nil`, continue). Document this precisely as **"Raid detection in the item panel's Acquisition section is not available in this pass — every item shows `IsRaid: false`. Pack ID and Wiki URL are available."** This is an honest, decisive scoping of a real, pre-existing gap, not a hidden limitation.
- After `itemsCache` is populated (both at `startup()` and `UpdateExternalSources()`), loop once and call the enrichment logic (a small adaptation of `EnrichItem` that mutates `XMLItem` fields in place — `EnrichItem` currently builds a *separate* `models.Item`; add a thin `EnrichItemInPlace(item *models.XMLItem)` that sets `PackID`/`WikiURL`/`IsRaid`/`RaidName` directly on the `XMLItem`, sharing the same lookup logic, to avoid maintaining two divergent implementations of the same matching rules) — this is a one-time O(n) pass at cache-load time, not per-request.
- Also parse `setBonusCache` via `ParseSetBonuses`, build `setsByName`.
- Log skipped-file counts from every `Parse*` call (per §3.1's new return value) via `a.addLog(...)`, so a partially-failed parse is at least visible in `GetSystemLogs()` even though it no longer crashes the cache.

### 4.4 `UpdateExternalSources()` changes

Mirror the same changes as `startup()`: rebuild `setBonusCache`/`setsByName`, rebuild all four name indexes, re-run the enrichment pass, log skipped-file counts.

### 4.5 New RPCs

```go
// GetItemDetails — UNCHANGED signature, but now O(1) via itemsByName instead
// of an O(n) linear scan, and the returned XMLItem carries every field added
// in §2 (buffs, weapon/armor profile, embedded augment choices, pack/wiki/raid
// enrichment computed at cache-load time).
func (a *App) GetItemDetails(itemName string) models.XMLItem

// GetSetBonus — exact-match lookup, index-backed. Returns a zero-value
// XMLSetBonus (empty Type) when not found — see AC-9.
func (a *App) GetSetBonus(name string) models.XMLSetBonus

// GetAugmentByName — exact-match lookup for a socketed augment's full detail
// (used when SlotDetail is unavailable — see §6.2 path 2). Deliberately NOT
// filtered by MinLevel or slot color, unlike GetAvailableAugments, because a
// socketed augment must always be resolvable regardless of the current
// max_level setting or which color slot it happens to occupy.
func (a *App) GetAugmentByName(name string) models.XMLAugment

// GetFiligreeByName — same rationale as GetAugmentByName.
func (a *App) GetFiligreeByName(name string) models.XMLFiligree
```

`GetSetBonus`/`GetAugmentByName`/`GetFiligreeByName` all follow the same "index-backed, zero-value-on-miss" contract as each other, for frontend-side consistency (§9's `itemCatalog.ts` treats "empty `Name`/`Type`" as the not-found signal uniformly).

---

## 5. Frontend service layer (`frontend/src/lib/services/itemCatalog.ts`)

New file. Centralizes fetching + caching for everything `ItemDetail.svelte` and its future sibling call sites (Summary.svelte, an eventual alternatives picker once Phase 10's `GetSlotAlternatives` gets a frontend) need, so repeated opens of the same item/augment/filigree/set within a session are free.

```typescript
import { GetItemDetails, GetSetBonus, GetAugmentByName, GetFiligreeByName } from '../../../wailsjs/go/main/App';
import { models } from '../../../wailsjs/go/models';

const itemCache = new Map<string, models.XMLItem>();
const setBonusCache = new Map<string, models.XMLSetBonus>();
const augmentCache = new Map<string, models.XMLAugment>();
const filigreeCache = new Map<string, models.XMLFiligree>();

export async function fetchItem(name: string): Promise<models.XMLItem> {
    if (itemCache.has(name)) return itemCache.get(name)!;
    const item = await GetItemDetails(name);
    itemCache.set(name, item);
    return item;
}

export async function fetchSetBonus(name: string): Promise<models.XMLSetBonus | null> {
    if (setBonusCache.has(name)) return setBonusCache.get(name)!;
    const set = await GetSetBonus(name);
    if (!set?.Type) return null;   // not-found sentinel per §4.5
    setBonusCache.set(name, set);
    return set;
}

export async function fetchAugment(name: string): Promise<models.XMLAugment | null> {
    if (augmentCache.has(name)) return augmentCache.get(name)!;
    const aug = await GetAugmentByName(name);
    if (!aug?.Name) return null;
    augmentCache.set(name, aug);
    return aug;
}

export async function fetchFiligree(name: string): Promise<models.XMLFiligree | null> {
    if (filigreeCache.has(name)) return filigreeCache.get(name)!;
    const fil = await GetFiligreeByName(name);
    if (!fil?.Name) return null;
    filigreeCache.set(name, fil);
    return fil;
}

// Called by UpdateExternalSources' success path (JobConfigurationForm.svelte's
// handleUpdateData) so a data refresh doesn't leave the frontend serving stale
// cached items after the Go-side caches have already been rebuilt.
export function clearItemCatalogCache(): void {
    itemCache.clear();
    setBonusCache.clear();
    augmentCache.clear();
    filigreeCache.clear();
}
```

No TTL/invalidation beyond `clearItemCatalogCache()` — this is a desktop app with an explicit "Update External Sources" action as the only data-refresh trigger; there is no background staleness concern between refreshes.

---

## 6. Credited-marker logic

### 6.1 Purpose

When `ItemDetail` renders for a slot with an available `SlotDetail` (`resultStore.slots[slot]`, Phase 9.2), each displayed buff is annotated with whether it actually counted toward the last solve. This is how the spec resolves the "does the panel disagree with the solver" risk from INV-1/INV-5 — by **showing** the answer authoritatively (sourced from the real solve) rather than Go trying to recompute DDO's stacking rules itself.

### 6.2 Graceful degradation — mandatory

`SlotDetail.item` (`store.ts:65-78`) currently has **no `buffs` field** — only `augments[].buffs`, `filigrees[].buffs`, `set_bonus_contributions[].buffs`. A separate, still-in-flight Phase 10 amendment may add `item.buffs`; **this spec must not depend on that landing.** If `slotDetail.item?.buffs` is absent or `undefined`, the credited-marker badge for the item's own buffs simply does not render — no error, no placeholder, no broken state. Augment/filigree/set-bonus credited-marker badges are unaffected either way, since those three already have `buffs` in the current `SlotDetail` shape.

### 6.3 Exact matching rule (three states)

Given a displayed buff `{stat, bonus_type, value}` (from `XMLItem.Buffs`, converted at display time per INV-2) and, when available, the corresponding `SlotDetail` sub-array's `buffs: SlotBuff[]` (`{stat, bonus, value}`):

| State | Condition |
|---|---|
| **Counted** | An entry exists in the relevant `SlotDetail` buffs array with the same `stat` (case-insensitive exact match) **and** the same `value` (numeric equality after string→number conversion, tolerance `1e-6`) **and** the same bonus type (case-insensitive exact match against `bonus`/`bonus_type`). |
| **Superseded** | An entry exists in the relevant `SlotDetail` buffs array with the same `stat` but a **different** `value` and/or a note that a different bonus-type source won (i.e. the stat name matches but this specific buff's value doesn't appear — meaning some other same-stat, same-bonus-type-class source was credited instead, per DDO's "only the best non-stacking source counts" rule). Displayed as *"superseded by a higher [bonus type] source"*. |
| **Not a priority** | No entry for this `stat` exists anywhere in the relevant `SlotDetail` buffs array at all — this buff's stat was never in the user's priority list, so it was never tracked by the solver in the first place (this is also the state for every buff in the "not used by the optimizer" group, §7.2 — the two concepts overlap but are not identical, see §6.4). |

**Which `SlotDetail` sub-array to check against** depends on what's being labelled: an item's own buff checks `slotDetail.item?.buffs` (when present, per §6.2); an augment's buff checks the matching entry in `slotDetail.augments[].buffs` for the augment with that name; a filigree's buff checks `slotDetail.filigrees[].buffs`; a set-tier's buff checks `slotDetail.set_bonus_contributions[].buffs`.

### 6.4 Relationship to the "not used by the optimizer" grouping (§7.2)

These are two independent signals, not the same thing, and the component must not conflate them:

- **"Not used by the optimizer"** (§7.2) is a **static** fact about the buff itself: does it have both a `Value1` and a `BonusType`? If either is missing, it is structurally unparseable by `parse_items` regardless of what the user prioritized — Python's `parse_items` requires `b_val and b_bonus` (`optimizer.py:162`) to emit a buff tuple at all. This grouping applies **with or without** a `slotDetail` present.
- **"Not a priority"** (§6.3) is a **dynamic** fact about the last solve: this buff *could* have been matched (it has a value and bonus type) but the user's priority list didn't include this stat, so it wasn't tracked. This only applies **when a `slotDetail` is present** — without one, there's no "last solve" to compare against, and the component simply doesn't render a credited-marker badge at all (not even "not a priority").

A buff that is structurally unparseable (first bucket) is **always** shown in the "not used by the optimizer" group, with no credited-marker badge attempted (the badge logic doesn't apply — there's nothing for it to have matched or not matched). A buff that is structurally parseable but wasn't in the priority list gets the normal Stats & Buffs table row, with a "not a priority" badge when `slotDetail` is present, and no badge when it isn't.

---

## 7. `ItemDetail.svelte` — component contract and rendering rules

### 7.1 Props

```typescript
export let itemName: string;                          // required
export let slot: string | null = null;                 // optional
export let slotDetail: SlotDetail | null = null;        // optional — from store.ts, Phase 9.2 shape
export let mode: 'view' | 'edit' = 'view';               // 'edit' enables augment/filigree pickers
```

Self-fetches `itemName` via `itemCatalog.fetchItem` on mount and on `itemName` change (Svelte reactive `$:` block, guarded so an in-flight fetch for a stale `itemName` doesn't overwrite state after the user has already navigated to a different item — track a local `fetchToken` incremented per fetch, only apply the result if the token still matches the latest).

### 7.2 Section list and visibility rules

Each section is wrapped in the generic accordion component being specified separately (assumed contract: `{title: string, open?: boolean, summary?: string}` + default slot — this spec does not build the accordion itself, only consumes it). If the accordion component is not yet available at build time, `ItemDetail.svelte` may temporarily use a plain `<details>`/`<summary>` element as a placeholder with the same section boundaries, to avoid blocking this component on that dependency landing first — but the section list/order below is authoritative regardless of which wrapper renders it.

| Section | Default state | Rendered when |
|---|---|---|
| Header | always visible (not collapsible) | always |
| Stats & Buffs | open | `Buffs.length > 0`; otherwise render "No buffs on this item." as static text, no accordion |
| — sub-group: used by optimizer | (part of Stats & Buffs) | `Buffs` entries with non-empty `Value1` **and** non-empty `BonusType` |
| — sub-group: not used by optimizer | (part of Stats & Buffs, visually distinct — e.g. muted/greyed styling, own sub-heading) | `Buffs` entries missing `Value1` and/or `BonusType` |
| Weapon Profile | collapsed | `Weapon !== ""` |
| Armor Profile | collapsed | `Armor !== ""` |
| Augment Slots | collapsed | `ItemAugments.length > 0` |
| Set Bonuses | collapsed | `SetBonuses.length > 0` **or** any `ItemAugments[].Augments[].SetBonus !== ""` |
| Clickies & Effects | collapsed | `Effects.length > 0` |
| Acquisition | collapsed | always rendered when the item has at least one `DropLocations` entry or a `PackID`; shows "Unknown" gracefully otherwise |
| Raw Description | collapsed | `Description !== ""` |

Header always includes: `Name`, `MinLevel`, slot list (`EquipmentSlot.Slots`), the existing minor-artifact checkbox toggle (carried over unmodified from `GearsetEditor.svelte:450-458`'s logic — same handler, same behavior, just relocated), and the wiki link button. **Wiki URL uses the existing frontend-side construction** (`GearsetEditor.svelte:332-334`'s `https://ddowiki.com/page/Item:${name.replace(/ /g, '_')}`), **not** the new backend `WikiURL` field from §2.3/enrichment — those differ (direct page link vs. a search-page link) and this spec keeps the simpler, already-working frontend behavior rather than silently switching link targets. The backend `WikiURL` field exists for the Acquisition section's informational display only, labelled distinctly if shown at all (optional — not required by any acceptance criterion below).

### 7.3 Stats & Buffs table row rendering

Each row: `stat` label (from `Type`/`Item` per whichever is more specific — `Item` when non-empty, else `Type`), `Description1` (when present, as supplementary text), `Value1`/`Value2` (formatted; `Value2` shown only when non-empty), `BonusType`, and — only in the "used by optimizer" sub-group, only when `slotDetail` provides a comparison array per §6.2 — the credited-marker badge per §6.3.

### 7.4 Weapon Profile rendering

- `Weapon` (type name), `AttackModifier`/`DamageModifier` (ability score used)
- Base dice: if `BaseDice` is non-null, render as `"{Number}d{Sides}"` alongside its expected value `Number × (Sides+1)/2` (rounded to 1 decimal) — this expected-value framing is deliberately consistent with `docs/PHASE10_PLAN.md` §15.3's `base damage dice` stat definition, even though this component makes no solver call and does no priority-matching itself
- `WeaponDamage` shown as `"[W] {value}"`
- Critical profile rendered as the conventional DDO notation `"{20 - CriticalThreatRange}-20 ×{CriticalMultiplier}"` when both fields are present and parse as numbers; if either is missing or unparseable, fall back to showing whichever raw field(s) are available with plain labels, never blank
- `DRBypass` as a comma-joined list when non-empty
- `Material`

### 7.5 Armor Profile rendering

`Armor` (type), `ArmorBonus`, `ShieldBonus`, `MaximumDexterityBonus`, `ArcaneSpellFailure`, `ArmorCheckPenalty` — each rendered only if its string is non-empty; section itself only renders if `Armor !== ""` per §7.2.

### 7.6 Augment Slots rendering

Carries over the existing picker logic from `GearsetEditor.svelte:478-525` (search, select, clear) essentially unchanged, gated by `mode === 'edit'` (in `'view'` mode, show the currently-selected augment's name/effects only, no picker UI). New additions on top of the existing behavior:

- For each `ItemAugments[i]`, if `SelectedAugment !== ""`, show it as the pre-selected default, distinct from whatever the user has manually socketed via `pre_filled_augments` (existing store state always wins for display if both are present — `SelectedAugment` is informational "this is what the item ships with," not an override of user choice).
- If `Augments.length > 0` (embedded upgrade choices), render them as a sub-list under that slot: name, description, and — if `SetBonus !== ""` — the "conditional — requires the '…' upgrade" label per §2.7.
- Socketed-augment detail resolution follows the two-path priority order from §6.2/orchestrator plan: when `slotDetail?.augments` has a matching entry (by color/name), use its `buffs` directly (already solver-credited, zero extra fetch); otherwise, if `configStore.pre_filled_augments[slot]?.[color]` gives a name, resolve full detail via `itemCatalog.fetchAugment(name)`.

### 7.7 Set Bonuses rendering

For each set the item belongs to (both `SetBonuses` — unconditional — and any conditional ones found under `ItemAugments[].Augments[].SetBonus`), fetch full tier detail via `itemCatalog.fetchSetBonus(name)` and render:

- Set name, icon
- Each tier: `EquippedCount`, `Description` (the ready-made human text — no effect-interpretation needed, per the design decision in §2.6), and structured `Effects` when present
- A live "you have N/M pieces" count, computed client-side from `resultStore?.slots` by counting equipped items/filigrees whose own set membership includes this set name (mirrors the existing `set_bonus_contributions` shape already emitted per-slot — this is a read of existing data, not new computation logic)
- Conditional membership (from an embedded augment) labelled per §2.7, and **excluded** from the "N/M pieces" live count unless that specific augment choice is confirmed currently selected (a conservative choice — since the panel cannot know which augment was actually socketed on a raw catalog browse without slot context, only count it when `slotDetail`/`pre_filled_augments` confirms the specific augment is actually chosen)

### 7.8 Clickies & Effects rendering

Each `Effects[]` entry: `Types` (joined), `Bonus`, `Item`, `Amount`, and any `Requirements` (rendered as plain "Requires: {Type} {Item}" lines). This is new content — nothing today shows item-level `<Effect>` data anywhere in the UI.

### 7.9 Acquisition rendering

`DropLocations` (list), `PackID` (when non-empty and not the literal fallback value `"base"` — display "Base Game" for that case specifically, matching `enrichment.go:63`'s default), and a static note **"Raid detection is not available in this version — see docs/ITEM_DETAIL_SPEC.md §4.3"** in place of an `IsRaid` badge, since raid detection is out of scope per §4.3's resolution. Do not render a false "Not a raid item" claim — omit the raid line entirely rather than assert something unverified.

### 7.10 Raw Description rendering

Existing `{@html Description}` block, carried over unmodified, demoted to the last, collapsed-by-default section.

---

## 8. New TypeScript types

New file `frontend/src/lib/types/itemDetail.ts` (kept separate from `store.ts` since these types describe XML-mirrored data, not application/solver state — matching the existing convention that `store.ts` owns solver-facing shapes):

```typescript
// These mirror the Go structs 1:1 and will be superseded by wailsjs-generated
// equivalents once `wails generate module` is run after the Go changes land —
// this file exists so the frontend can be developed/type-checked against the
// target shape before that regeneration happens. On regeneration, replace
// these local interfaces with imports from wailsjs/go/models and delete this
// file's duplicated definitions (keep only anything wailsjs doesn't generate,
// if anything).

export interface XMLBuff {
    Type: string;
    Item: string;
    Description1: string;
    Value1: string;
    Value2: string;
    BonusType: string;
}

export interface XMLRequirement { Type: string; Item: string; }

export interface XMLEffect {
    Types: string[];
    Bonus: string;
    Item: string;
    AType: string;
    Amount: string;
    Requirements: XMLRequirement[];
}

export interface XMLEmbeddedAugment {
    Name: string;
    Description: string;
    MinLevel: string;
    Icon: string;
    GrantAugment: string;
    SetBonus: string;
    Effects: XMLEffect[];
}

export interface XMLBaseDice { Number: string; Sides: string; }

export interface XMLSetTier {
    EquippedCount: string;
    Description: string;
    Effects: XMLEffect[];
}

export interface XMLSetBonus {
    Type: string;
    Icon: string;
    Tiers: XMLSetTier[];
}
```

(`XMLItem`/`XMLItemAugment`/`XMLAugment`/`XMLFiligree` are not re-declared here — they already exist in `wailsjs/go/models.ts` and will simply gain fields on regeneration after the Go changes land; only the genuinely new nested types need this stopgap file.)

---

## 9. Success criteria / acceptance checks

### Go — parser fault tolerance and indexing

| ID | Check |
|---|---|
| **AC-1** | A fixture directory of 5 valid `.item` files plus 1 deliberately truncated/malformed `.item` file: `ParseItems` returns exactly 5 (or more, if any file contains multiple `<Item>`) parsed items, a `skipped` slice containing the malformed file's path, and a `nil` walk-level error. The cache is **not** empty. |
| **AC-2** | Same fixture pattern for `ParseAugments`, `ParseFiligrees`, `ParseSetBonuses` — each independently fault-tolerant. |
| **AC-3** | `itemsByName["Some Known Item"]` resolves in O(1) (test via a benchmark or simply asserting direct map access, not a loop) and returns the correct index. |
| **AC-4** | `GetItemDetails` on a name not present in the cache returns a zero-value `XMLItem` (empty `Name`), not a panic, not an error. |
| **AC-5** | After `UpdateExternalSources()`, all four name indexes and `setBonusCache`/`setsByName` are rebuilt to reflect the newly-parsed data (not stale from the previous load) — test by mutating the underlying fixture directory between two calls and asserting the second `GetItemDetails` reflects the change. |

### Go — new RPCs

| ID | Check |
|---|---|
| **AC-6** | `GetSetBonus("Epic Elemental Evil Set")` (or an equivalent fixture set) returns a populated `XMLSetBonus` with `Tiers` matching the fixture's `<Buff>` count. |
| **AC-7** | `GetSetBonus("Not A Real Set")` returns a zero-value `XMLSetBonus` (`Type == ""`), not an error. |
| **AC-8** | `GetAugmentByName`/`GetFiligreeByName` return full detail for a name present in the cache **regardless of that augment's `MinLevel`** relative to any `maxLevel` filter — confirms these do not reuse `GetAvailableAugments`'s filtering (§4.5's stated rationale). |
| **AC-9** | `GetAugmentByName`/`GetFiligreeByName` on an unknown name return a zero-value struct (empty `Name`), matching the same not-found contract as `GetSetBonus`. |

### Go — enrichment wiring

| ID | Check |
|---|---|
| **AC-10** | After `startup()`, `itemsCache` entries have `PackID` populated from `data/PackMappings.json` matching (non-`"base"` for at least one known fixture item whose `DropLocations` matches a configured keyword). |
| **AC-11** | Every `itemsCache` entry has `IsRaid == false` (raid detection intentionally unavailable per §4.3) — this is a regression guard against silently wiring in a raids file later without updating this spec/the UI's "not available" note. |
| **AC-12** | A pack-mappings load failure at `InitEnrichment` time is fatal (startup logs an error, `PackID` stays unpopulated for all items) — a missing/absent raids file is **not** fatal (startup succeeds, `IsRaid` stays `false` for all items, one log line noting raid detection is disabled). |

### Go — new model fields parse correctly

| ID | Check |
|---|---|
| **AC-13** | A fixture item with 3 `<Buff>` elements (mixed: one with full `Value1`+`BonusType`, one with only `Type`, one with `Type`+`Item`+`Description1` but no value) parses into `Buffs` with all 3 present verbatim as strings — none dropped, none coerced. |
| **AC-14** | A fixture weapon item with `<BaseDice><Number>2</Number><Sides>6</Sides></BaseDice>` parses `BaseDice` as non-nil with `Number == "2"`, `Sides == "6"` (strings, per INV-2). A fixture item with no `<BaseDice>` element parses `BaseDice` as `nil`. |
| **AC-15** | A fixture item with an `<ItemAugment>` containing a nested `<SelectedAugment>` and two `<Augment>` children parses `SelectedAugment` and both `Augments` entries, including a `SetBonus` value on one of them. |
| **AC-16** | A fixture filigree with one base `<Effect>` and one `<Rare/>`-tagged `<Effect>` parses **both** into `Effects` (unlike Python's `parse_filigrees`, which skips the Rare one — confirms Go's display parsing deliberately diverges from Python's solver-matching parsing here, per §2.5). |

### Frontend — component behavior

| ID | Check |
|---|---|
| **AC-17** | `<ItemDetail itemName="X" />` with no other props renders the Header and Stats & Buffs sections (assuming `X` has buffs) without throwing, with no credited-marker badges shown anywhere (no `slotDetail` provided). |
| **AC-18** | `<ItemDetail itemName="X" slotDetail={...} />` where `slotDetail.item` has no `buffs` field renders identically to AC-17 for the item's own buffs (graceful degradation per §6.2) but **does** show credited-marker badges on augment/filigree/set-bonus rows if those sub-arrays are present in the given `slotDetail`. |
| **AC-19** | Rapidly changing `itemName` (simulating fast slot-to-slot clicking) never renders stale data — the `fetchToken` guard (§7.1) discards a late-arriving response for an `itemName` that's no longer current. |
| **AC-20** | An item with zero `Buffs` renders "No buffs on this item." and no Stats & Buffs accordion/table. |
| **AC-21** | A non-weapon item (`Weapon === ""`) never renders a Weapon Profile section; a non-armor item never renders an Armor Profile section. |
| **AC-22** | The "not used by the optimizer" sub-group contains exactly the buffs missing `Value1` and/or `BonusType`, and only those — verified against a fixture with a known mix (matches the corpus-measured ~25% pattern from §2.1, but the test only needs a small deterministic fixture). |
| **AC-23** | Selecting `weapon base damage` and `weapon damage` (or `base damage dice`) together in the stat picker is blocked — **this specific check belongs to the separate Tiered Solver Frontend spec** (per `docs/PHASE10_PLAN.md` §15.3/EC-29), not to this component; listed here only as a cross-reference so it isn't lost between the two specs. |

---

## 10. Edge cases

| ID | Case | Required behavior |
|---|---|---|
| **EC-1** | Item with zero `Buffs`, zero `Effects`, not a weapon, not armor, no augment slots, no set membership | Only Header, Acquisition (however sparse), and Raw Description (if `Description` non-empty) sections render. No empty accordions for sections with nothing to show — they simply don't render at all (per §7.2's visibility table), rather than rendering an empty/collapsed shell. |
| **EC-2** | Item with only valueless/named buffs (e.g. `Litany of the Dead`'s `<Buff><Type>Litany of the Dead - Ability Bonus</Type></Buff>`) | Stats & Buffs section renders with only the "not used by the optimizer" sub-group populated; the "used by optimizer" sub-group shows "None" or is simply absent within the section. |
| **EC-3** | Weapon item legal in both `Weapon1` and `Weapon2` | Weapon Profile section renders once regardless of which slot(s) the item could occupy — this is a property of the item, not of a specific equip slot. (No interaction with `docs/PHASE10_PLAN.md` §15.4's Weapon1-only solver scoping — that's a solver behavior, this is a display behavior; the panel shows the item's true properties regardless of how the solver chooses to score them.) |
| **EC-4** | Item belonging to zero sets | Set Bonuses section does not render (per §7.2). |
| **EC-5** | Item belonging to one unconditional set and one conditional (augment-choice-gated) set simultaneously | Both render in the Set Bonuses section; the conditional one carries the "conditional — requires the '…' upgrade" label, the unconditional one does not. |
| **EC-6** | A set-bonus tier with no `<Effect>` children, `Description`-only | Renders `EquippedCount` + `Description` text with no structured effects list beneath it — not an empty bulleted list, just the description line. |
| **EC-7** | `ItemAugment` with `SelectedAugment` set, but the user has also manually socketed a *different* augment of that color via `pre_filled_augments` | The manually-socketed one displays as the actual current state (existing store behavior wins); `SelectedAugment` is shown only as supplementary "ships with" info, never overriding displayed state — per §7.6. |
| **EC-8** | `ItemAugment` with no `SelectedAugment` and nothing socketed in `pre_filled_augments` | Slot shows the existing "Empty (Click to add)" affordance (`mode === 'edit'`) or simply "Empty" (`mode === 'view'`) — carried over unmodified from current `GearsetEditor.svelte` behavior. |
| **EC-9** | `GetAugmentByName`/`GetFiligreeByName` called with a name that exists in the cache but whose `MinLevel` exceeds the current `max_level` config | Still returns full detail (§4.5's explicit design — these are exact-match lookups, not filtered browse endpoints; a socketed item's detail must always be resolvable). |
| **EC-10** | Malformed XML file present in the items/augments/filigrees/set-bonuses directory at parse time | Per AC-1/AC-2: that file is skipped, logged, and every other file in the directory still parses successfully — the cache is never empty because of one bad file. |
| **EC-11** | Two distinct XML entries (item, augment, filigree, or set) share the exact same `Name`/`Type` string | The name index keeps the last-parsed one; this is a documented, accepted tiebreak (§4.2), not an error condition, and is not expected to occur in practice given DDO's data. |
| **EC-12** | `slotDetail` provided, but for a **different** item than `itemName` (a stale prop combination, e.g. the caller forgot to clear `slotDetail` when switching to browsing an unequipped item) | The component does not attempt to detect or guard against this mismatch itself — it is the caller's responsibility to pass a `slotDetail` consistent with `itemName` (or `null`). Documented as a caller contract, not a runtime check, to avoid adding speculative validation for a misuse pattern that shouldn't occur given how `GearsetEditor.svelte` will call this component (always deriving `slotDetail` from `resultStore.slots[slot]` for the same `slot` being displayed). |

---

## 11. Out of scope for this pass (deferred, recorded for later)

1. **Raid detection** (§4.3) — no raids data source exists in the repo; `IsRaid` stays `false` for every item until a future pass builds one (likely by replicating Python's `parser.parse_quests` raid-detection logic in Go, or sourcing a static raids list).
2. **Conditional set-bonus solver divergence** (§2.7) — the solver's `.//SetBonus` recursive search credits conditional set bonuses unconditionally; this spec's panel displays them correctly (conditionally) and will visibly disagree with the solver on affected items. Not fixed here.
3. **Weapon Profile credited-marker treatment** — if `docs/PHASE10_PLAN.md` §15's weapon-base-stat solver work lands, a future pass should extend the credited-marker concept (§6) to Weapon Profile fields too. Not built now; this spec's data model (all-string fields, `origin`-free) does not preclude it later.
4. **Accordion component itself** — assumed as an external dependency with a minimal stated contract (§7.2); not designed or built as part of this spec.
5. **`data/bonus_types.json` shared source of truth** — replacing Python's duplicated `['stacking','mythic','reaper']` constant and giving Go a principled way to interpret bonus types if that's ever wanted, instead of the current "Go shows `BonusType` as a verbatim string, never interprets it" design (§2.1/INV-1). Named for the record, not built.
