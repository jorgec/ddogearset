# Identity drift report — `content-8991bb1fb264`

- **Source:** `/Users/jorgecosgayon/dev/ddo/goGearset/DDOBuilderV2/Output/DataFiles`
- **Built at:** 2026-08-10T00:00:00Z
- **Mode:** `--strict` (unresolved drift fails the build)

| | Count |
|---|---:|
| New entities minted | 0 |
| Auto-resolved renames | 0 |
| **Unresolved — needs a decision** | **0** |
| Source-data ambiguities | 1 |

## Source-data ambiguities

Two things in DDOBuilderV2 want the same identity and no field tells them apart. Transform picked deterministically and says which; `aliases.yaml` cannot fix these, because the problem is upstream, not a rename. They are listed on every run so a *new* one is noticeable among the known ones.

- augment identity collision: 'Twilight' (Cannith Armor Prefix) appears more than once with no field to disambiguate. The FIRST occurrence in sorted file order is kept and this one is DROPPED — it is not merged into the first, because their bonus types differ and merging would invent an augment that does not exist. Known and expected on the real corpus for exactly one pair (docs/0.5.0/00_ETL_START_HERE.md §6).
