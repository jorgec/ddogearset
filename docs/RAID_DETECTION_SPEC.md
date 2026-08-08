# Raid detection — research + spec

**Status:** Implemented, in both Go (`internal/services/enrichment.go`,
UI badge) and Python (`python/optimizer.py`, solver's `raid_item_limit`
enforcement).

**Decisions (confirmed):**
1. Both languages fixed, not just the UI badge — the Python solver's
   `raid_item_limit` blind spot (Finding 3) was a real correctness bug.
2. The DropLocation ingredient cross-reference (Signal A's looser variant)
   is scoped to DropLocation text containing a crafting/turn-in keyword
   (`"turn in"`, `"catalyst"`, `"crafting"`), not run unconditionally —
   bounds cost (~3s one-time for the full corpus in Python; Go's version is
   cheaper, no separate re-scan needed since `itemsCache` is already fully
   parsed and unfiltered) and false-positive surface.

Verified end-to-end against real DDOBuilderV2 data in both languages: the
full Torc of Prince Raiyum-de II and Dragon's Eye chains (base → Epic →
Legendary → Perfected) all resolve `is_raid = True`/`IsRaid = true` with the
correct originating raid name propagated, while a real non-raid
catalyst-crafted control item ("Perfected Longsword of the Weapon Master",
whose ingredient — "Drow Longsword of the Weapon Master" — is genuinely a
non-raid quest reward) correctly resolves `False`/`false`.

## Ask

1. Make raid detection work, using https://ddowiki.com/page/Raids as the
   definitive raid list, in a way that stays correct as new raids ship —
   "future proof... down the line."
2. Correctly classify items that are only reachable by *upgrading* a raid
   item (e.g. Legendary Torc of Prince Raiyum-de II ← Epic Torc of Prince
   Raiyum-de II ← Torc of Prince Raiyum-de II, a real Zawabi's Revenge raid
   item) — including cases where the upgrade's own drop text names an
   ingredient that itself isn't textually raid-flagged, but *its* ingredient
   chain traces back to a raid.

## Finding 1: the wiki's raid list already exists in the data we already fetch — no new static list needed

DDOBuilderV2 (already vendored into this repo and already kept current via
`ensureDDOBuilderData`/`UpdateExternalSources`) ships `Quests.xml`, where
each raid quest carries a bare `<IsRaid/>` marker. Extracted and compared
directly against the wiki's "Raids" page:

- Wiki: **41** raids listed.
- `Quests.xml`: **41** quests with `<IsRaid/>` set.
- Names match exactly (spot-checked the full list both ways — every wiki
  raid name is present, nothing extra).

`python/parser.py`'s `parse_quests` already reads this file and already
builds an `is_raid` flag per quest — it's just not currently wired into raid
*detection* comprehensively (see Finding 3). The Go side
(`internal/services/enrichment.go`) doesn't read it at all — `raidsPath = ""`
in `app.go`, so `InitEnrichment` never loads any raids and `IsRaid` stays
`false` for every item, exactly as `docs/ITEM_DETAIL_SPEC.md` §4.3/§11.1
already documented as a known, deliberate gap.

**This is the answer to "future proof":** don't hand-maintain a raids list
scraped from the wiki at all. Read `Quests.xml`'s `<IsRaid/>` flags directly,
the same way `parser.parse_quests` already does — DDOBuilderV2's own
maintainers keep this current as new raids ship (same reason `Quests.xml`
already agreed with the wiki 41/41 with zero manual work from this project),
and this app already re-fetches DDOBuilderV2 on the existing schedule. Zero
new data files, zero new update mechanism, zero drift risk versus a
separately-maintained list going stale.

## Finding 2: the upgrade-chain problem is real, verified, and has two distinct shapes in the data

Traced the exact example given, `Torc of Prince Raiyum-de II`, end to end:

| Item | `DropLocation` | Linkable how |
|---|---|---|
| `Torc of Prince Raiyum-de II` | `Zawabi's Revenge, warded chest` | Direct — quest name in DropLocation (already detectable today) |
| `Epic Torc of Prince Raiyum-de II` | `Epic version of Torc of Prince Raiyum-de II` | **Signal A** — DropLocation names the base item |
| `Legendary Torc of Prince Raiyum-de II` | `Legendary version of Epic Torc of Prince Raiyum-de II` | **Signal A** — chains one more hop |
| `Perfected Torc of Prince Raiyum-de II` | `Lahar, Turn in Nebula Fragment` | **Neither text signal exists** — "Nebula Fragment" is a generic catalyst material shared by ~10 unrelated Perfected-tier items; nothing in the DropLocation text names "Torc" at all |

The `Perfected` case is real and not an isolated one-off — verified the same
exact shape on `Dragon's Eye` (`Plane of Night, warded chest` → `Epic version
of Dragon's Eye` → `Legendary version of Epic Dragon's Eye` → `Perfected
Dragon's Eye`: `Lahar, Turn in Nebula Fragment`, same generic catalyst text)
and 8 more Perfected-tier items sharing that identical drop text.

So there are two independent signals, and **neither alone is sufficient**:

- **Signal A — DropLocation text reference.** `"<Tier> version of <Name>"`
  (605 real occurrences) and multi-ingredient combine text (`"Cauldron of
  Sora Katra, Upgraded version of Blade of Fury and Hooked Blade"`, `"...Turn
  in Drow Longsword of the Weapon Master, the Weapon Master Abyssal Catalyst
  and 50 Abyssal Gems..."`) both literally name one or more ingredient items
  by their exact in-game name, which can be cross-referenced against the
  full item-name index. Catches multi-item combines and cases where the
  *name itself changes* between tiers (no shared suffix).
- **Signal B — tier-prefix name stripping.** Strip a known tier-quality
  prefix word off the front of the item's own name and check whether the
  remainder is itself a real item name. Catches the `Perfected` case (no
  textual DropLocation link at all) and is *also* sufficient on its own for
  the ordinary `Epic`/`Legendary` cases (no DropLocation parsing needed for
  those specifically) — but **fails** the `Weapon Master` catalyst-crafted
  items above, because e.g. `Perfected Longsword of the Weapon Master`
  strips to `Longsword of the Weapon Master`, but the real ingredient item is
  named `Drow Longsword of the Weapon Master` — a different name, only
  catchable by Signal A reading the DropLocation text.

Verified prefix-stripping's real hit rate in the corpus (stripped remainder
resolves to a real item name):

| Prefix | Items with this prefix | Remainder resolves to a real item |
|---|---|---|
| `Legendary ` | 1796 | 1702 |
| `Epic ` | 648 | 524 |
| `Perfected ` | 28 | 14 (the other 14 need Signal A) |
| `Mythic ` | 8 | 7 |
| `Elite ` | 1 | 1 |

(`Ancient ` was tested and dropped — 12 items, 0 real matches; not a real
tier-upgrade prefix in this data, just coincidental naming.)

Neither signal alone would have caught the exact case in the ask
(`Torc`/`Dragon's Eye` Perfected tier needs Signal B; the `Weapon Master`
catalyst items need Signal A) — **both are required.**

## Finding 3: this is also a real optimizer correctness gap, not just a UI cosmetic one

`python/optimizer.py`'s `raid_item_limit` constraint (caps how many raid
items the *solver* is allowed to equip, enforced during search, not just
display) currently detects `is_raid` via the same "quest name in
DropLocation, else the substring `'raid'` anywhere in DropLocation" logic —
so `Legendary Torc of Prince Raiyum-de II` (DropLocation: `"Legendary version
of Epic Torc of Prince Raiyum-de II"` — no quest name, no literal "raid"
substring) is **not** counted against a user's raid item cap today, even
though it demonstrably is one. This means the fix needs to land in **both**
places that independently parse the same DDOBuilderV2 corpus:

- `internal/services/enrichment.go` (Go) — the `ItemDetail` panel's badge,
  originally scoped out in `docs/ITEM_DETAIL_SPEC.md` §4.3/§11.1.
- `python/optimizer.py`'s `parse_items` (Python) — the solver's own
  `raid_item_limit` enforcement, which has never worked on upgrade-chain
  items at all.

## Design

### 1. Raid list source (both languages)

Read `Quests.xml`'s `<IsRaid/>` quests directly — Go gets a small new loader
mirroring Python's existing `parser.parse_quests` (`internal/services` reads
`ddoDataRoot + "/Quests.xml"`, already resolvable — `ddoDataRoot` is already
a package-visible constant path). `InitEnrichment`'s `raidsPath` JSON-file
parameter goes away entirely; `raids []string` gets populated straight from
this loader instead. No new file to fetch, stage, or keep in sync — reuses
the DDOBuilderV2 fetch this app already performs.

### 2. Upgrade-chain propagation (both languages, same algorithm)

For every item, in addition to the existing direct check (quest name found
in `DropLocation`), attempt both signals to find "ingredient" item name(s):

```
ingredients(item):
    found = []
    # Signal A — DropLocation text reference
    for phrase matching /(?:upgraded )?version of ([^,]+)/i in DropLocation:
        split phrase on " and "/" + " (multi-ingredient combines)
        for each candidate substring: if it exactly matches a real item name
            (or is contained as a real item name — longest match wins to
            avoid a short common name false-matching inside a longer one),
            add it to found
    for each known item name that appears as a substring of DropLocation
        (only for DropLocation text containing "Turn in"/"Catalyst"/
        "Crafting" — scope this narrowly, see Open Question 2 — to avoid
        pathological O(items²) scans and false positives from short names):
        add it to found

    # Signal B — tier-prefix name stripping
    for prefix in (Epic, Legendary, Mythic, Perfected, Elite, ...):
        if item.name starts with prefix:
            remainder = item.name[len(prefix):]
            if remainder is a real item name:
                add remainder to found

    return found (deduplicated)

is_raid(item, memo={}):
    if item.name in memo: return memo[item.name]
    memo[item.name] = False  # cycle guard
    direct = quest-name-in-DropLocation match against Quests.xml raids
    if direct:
        memo[item.name] = True
        return True
    for ingredient_name in ingredients(item):
        if ingredient_name in items_by_name and is_raid(items_by_name[ingredient_name], memo):
            memo[item.name] = True
            return True
    return False
```

Memoized so the O(chain depth) recursion is paid once per item name across
the whole cache-build pass, not per lookup. Chains observed are shallow (3-4
hops max in every example found), so no depth limit is needed, but the memo
dict doubles as a cycle guard regardless.

### 3. Where each language wires it in

- **Go** (`internal/services/enrichment.go`): `acquisitionFor` currently only
  substring-matches `raids` against `dropLocations`. Extend `EnrichItemInPlace`'s
  one-time O(n) pass (already documented as happening once at cache-load
  time, not per-request) to run the `is_raid` memoized graph walk instead of
  the flat substring check, using the already-built `itemsByName` index for
  ingredient lookups.
- **Python** (`optimizer.py`'s `parse_items`): same algorithm, same
  `Quests.xml`-sourced raid list (already available via `quests_lookup`),
  same memoized graph walk, replacing the current `item_is_raid` computation
  (§ "Finding 3"). Needs the full item-name index built up front (two-pass:
  parse all items' `Name`/`DropLocation` first, then resolve `is_raid` in a
  second pass) since an item's raid status can depend on another item parsed
  later in the same directory walk.

### 4. UI (optional, cheap addition)

`acquisitionFor` already returns `RaidName` alongside `IsRaid` for the direct
case. For an upgrade-chain match, `RaidName` would naturally resolve to
whichever raid the *root* of the chain came from (falls out of the recursion
for free — the base case's raid name propagates up). `ItemDetail.svelte`
already has a slot for this (`docs/ITEM_DETAIL_SPEC.md` §7) — no new UI work
required beyond removing the current "Raid detection is not available in
this version" placeholder note.

## Out of scope

- Building any new hand-maintained data file — the whole point of Finding 1
  is that one isn't needed.
- Retroactively re-tagging already-saved `.ddogearset` files' cached
  `is_raid` values — this only affects freshly-computed searches/lookups
  going forward.
- A UI element showing the *upgrade chain itself* (e.g. "raid item via: X ←
  Y ← Z") beyond the existing `RaidName` field — §4 covers the minimum to
  close the badge gap; a fuller chain-of-custody display would be new UI
  scope, not asked for here.
