# Schema — `catalog.db` and `app.db`

**Written:** 2026-08-10. Revised for the ETL pivot.
**Status:** proposal. Nothing implemented.
**Read first:** [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md) — the spec and
plan this schema serves. `catalog.db` is 0.5.0; `app.db` is 0.5.1.

> [!IMPORTANT]
> Two constraints from START_HERE §2 govern everything below and are easy to
> lose sight of while reading DDL:
>
> * **The ETL runs at build time on a dev machine only.** `catalog.db` ships as
>   a read-only resource. Nothing here is written at runtime.
> * **The catalog holds every item at every level.** No search restriction is
>   ever applied by the ETL — ML windows, armor and pack filters become `WHERE`
>   clauses in the solver's pool query.

---

## 1. The proposal

> A true ETL from the DDOBuilderV2 datasets into a normalized (3NF) SQLite
> database. **Normalization of names — including variants — happens in the
> Transform stage, before the database.** Load resolves the normalized name
> against the DB and upserts. **UUIDs as primary keys**, so all three layers
> refer to the same identity.
>
> The same store holds the request (the parameters and priorities the user
> selected), and separates what is **equipped** from what the solver
> **suggested**, so everything is a lookup.

---

## 2. What moves to Transform — a correction

An earlier draft of this document claimed stat naming could not move out of
Python at all. **That was too strong**, and the distinction it missed is the
whole point of doing a real Transform stage.

`normalize_stat_name` computes two very different kinds of thing:

### 2.1 Buff-side: pure functions of the catalog → **Transform**

```python
is_skill_buff    = 'skill' in typ or 'skill' in item
is_hireling_buff = 'hireling' in typ or 'hireling' in item
is_save_buff     = 'save' in typ or 'save' in item
combined         = f"{item} {typ} {desc}".lower()
```

No priorities appear in any of them. They are properties **of the stat**, and
four of the six guards the retrospective calls "a past bug each" are really
*modelling errors* that a dimension table makes structural:

| Guard | Origin | What it actually is |
|---|---|---|
| Hireling | 0.4.4 | `HirelingPRR` is a **different stat entity** from `PRR` |
| School save | 0.4.2 | `IllusionSave` (defensive) is a different entity from Illusion DC (offensive) |
| Skill group | 0.4.3 | `Intelligence Skills` is a different entity from `Intelligence` |
| Weapon base stats | §15.2 | A finite, known vocabulary — a flag, not a heuristic |

Once each distinct `(raw_type, raw_target)` pair is resolved to a canonical
`stat` row carrying those flags, the guards stop being code that can be
forgotten and become columns that cannot.

### 2.2 Priority-side: functions of user input → **runtime**

```python
required_bonus, p_clean = _split_bonus_type_prefix(p_base.lower())  # 'sacred spell focus mastery'
direct, implied         = match_terms(p_clean)                      # expansion
for use_implied in (False, True):                                   # resolution policy
    for p in priorities:                                            # ORDER matters
```

These take the user's own typed priority list, so no table can hold the answer.
The two-pass direct-before-implied rule is a *resolution policy over an ordered
user list* — inherently per-request.

**But the residue is small.** After Transform, runtime naming is: expand a dozen
priority strings once, then match them against a **few-thousand-row `stat`
dimension** — not 250 lines of heuristics run against 8779 files. It stays in
Python (`rules/naming.py`), and it gets much cheaper and much easier to test.

> The rule that survives unchanged: **one layer owns priority matching.** If Go
> matches priorities against the `stat` table itself, that is the failed 0.5.0
> approach with a database in the middle.

### 2.3 Entity-side: variants and upgrade chains → **Transform**

This is classic ETL entity resolution and it belongs entirely before the
database. The corpus already forces it:

| Variant shape | Example | Transform output |
|---|---|---|
| Upgrade tier prefixes | `Epic X` / `Legendary X` / `Mythic X` (`RAID_UPGRADE_TIER_PREFIXES`) | `item_family` + `item.family_uuid`, `item.tier` |
| "version of" chains | `_RAID_VERSION_OF_RE` | edges in `item_upgrade` |
| Filigree base/variant | `Melony's Melody: +1 Intelligence` | `filigree.base_uuid` + variant label |
| Dual-set filigrees | `Zarigan's Arcane Enlightenment/Voltaic Experiment +2 Intelligence` | **two** `filigree_set` rows |
| Repeating `<Item>` | Force / Physical / Untyped on one effect | **three** `effect_target` rows |

Every one of these is a place where the current code picks a winner and loses
information. Transform's job is to stop picking.

---

## 3. Identity: deterministic UUIDs

### 3.1 v5, not v4 — this is load-bearing

```
uuid = uuidv5(namespace_for_entity_kind, natural_key)
```

The catalog is **dropped and rebuilt** on every DDOBuilderV2 update (§4). With
random v4 keys, every rebuild would mint new identities and orphan every
reference in `app.db` — strictly worse than storing names. With **name-based
v5**, the same source row yields the same UUID on every machine and every
rebuild, with no coordination. That is what makes cross-database references
safe, and it is what lets all three layers name the same thing.

| Entity | Namespace | Natural key |
|---|---|---|
| `item` | `NS_ITEM` | canonical item name |
| `augment` | `NS_AUGMENT` | canonical augment name |
| `filigree` | `NS_FILIGREE` | canonical filigree name |
| `set` | `NS_SET` | set name |
| `stat` | `NS_STAT` | `raw_type` + `\x1f` + `raw_target` (normalized, lowercased) |
| `effect` | `NS_EFFECT` | source uuid + ordinal within source |

**v5 hashing alone is not enough, and the registry is what closes the gap.** A
UUID derived from a natural key is only as stable as that key: if DDOBuilderV2
*renames* an item, the key changes and so would the UUID, orphaning every
`app.db` reference. Hashing cannot fix that, because a rename is information
that exists only *between* two runs.

So the table above describes **minting only**. Identity is then **pinned in
`etl/identity_registry.json`** (START_HERE §6): once a UUID is minted it never
changes, and a later rename appends to that entity's `aka` list rather than
producing a new identity. A natural key is consulted only when nothing in the
registry already claims it.

What remains genuinely unfixable is **removal**: if an item leaves the game
data entirely, its UUID resolves to nothing. That is what §5.3's name tombstone
exists for — so the app can say *"Legendary Bracers of Wind is no longer in the
catalog"* rather than showing an empty slot.

### 3.2 Storage form

Store as `TEXT` (36 chars), tables declared `WITHOUT ROWID`.

`BLOB(16)` is less than half the size, but the catalog is ~9k items and on the
order of 10⁵ effect rows, so the difference is single-digit megabytes on a
desktop app. Being able to open the database and *read* an identifier is worth
more than that here: the recurring failure mode in this project is a wrong
number reaching the screen, and every debugging session starts with "which
entity is this row?".

### 3.3 One UUID space enables a proper supertype

An earlier draft had `effect(source_kind, source_id)` — a polymorphic pointer
that SQLite cannot constrain with a foreign key. A single UUID space replaces it
with a real supertype and a real FK:

```sql
CREATE TABLE source (
    uuid TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('item','augment','filigree','set_tier')),
    name TEXT NOT NULL
) WITHOUT ROWID;
```

`item`, `augment`, `filigree` and `set_tier` each key off `source.uuid`, and
`effect.source_uuid REFERENCES source(uuid)` is enforceable. Strictly more
normalized than the polymorphic version, and it exists only because identities
are global.

---

## 4. Two databases

| | `catalog.db` | `app.db` |
|---|---|---|
| Contents | Items, augments, filigrees, sets, **stats**, effects, quests | Builds, priorities, gearsets, runs |
| Produced by | The ETL | The user |
| On rebuild | **Dropped and recreated** | Never touched |
| If lost | Regenerate in seconds | **Unrecoverable** |
| Migrations | None — rebuild instead | Real, versioned, forward-only |

Keeping the catalog disposable is what lets Load be a clean rebuild rather than
a diffing migration, and means a corrupt catalog is never a data-loss event.
`ATTACH DATABASE` makes cross-database joins work; deterministic UUIDs (§3.1)
make cross-database *references* safe.

**The ETL runs in-app, not at build time.** `ensureDDOBuilderData` /
`updateDDOBuilderDataIfStale` fetch DDOBuilderV2 at runtime, so the catalog must
rebuild whenever `.ddobuilderv2_commit` moves. Build into a temp file, verify
`catalog_meta`, then atomically rename — an interrupted rebuild must never leave
a half-populated catalog in place.

---

## 5. Schema

### 5.1 `catalog.db`

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Exactly one row. See §5.1.1 for why each field exists and why none of them
-- can be added later to a catalog that has already shipped.
CREATE TABLE catalog_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),

    -- SHAPE — which tables and columns exist. Bumped by hand when the DDL
    -- changes. The app refuses a catalog outside the range it understands.
    schema_version          INTEGER NOT NULL,

    -- ARTEFACT IDENTITY — monotonic and orderable. This is the number an
    -- "update catalog" check compares, and it is NOT derivable from either
    -- field below: a Git SHA has no order, and the same DDOBuilderV2 commit
    -- can legitimately be rebuilt after an ETL fix.
    catalog_version         INTEGER NOT NULL,
    built_at                TEXT    NOT NULL,   -- RFC3339, informational

    -- PROVENANCE — what produced it.
    ddobuilder_commit       TEXT    NOT NULL,
    etl_version             TEXT    NOT NULL,
    source_file_count       INTEGER NOT NULL,

    -- COMPATIBILITY — the other direction: a new catalog telling an old app
    -- not to open it, with something a human can read in the refusal.
    min_app_version         TEXT    NOT NULL,

    -- INTEGRITY of the logical content (sorted rows), NOT of the file.
    -- SQLite files are not byte-reproducible — page ordering and the freelist
    -- differ between runs — so a file hash cannot answer "did the data
    -- change?". A download's *bytes* are verified separately (§5.1.2).
    content_hash            TEXT    NOT NULL,

    -- IDENTITY CONTINUITY — see the warning in §5.1.1. A catalog built from a
    -- divergent identity registry would silently re-mint UUIDs and orphan
    -- every reference in app.db.
    identity_registry_hash  TEXT    NOT NULL
);

-- (§5.1.1 explains the versioning fields; the rest of the schema follows.)

-- Supertype: every effect-bearing thing has an identity here (§3.3).
CREATE TABLE source (
    uuid TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('item','augment','filigree','set_tier')),
    name TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX source_name_idx ON source(name);

-- --- entity resolution output (§2.3) ---------------------------------------
CREATE TABLE item_family (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE          -- the tier-stripped base name
) WITHOUT ROWID;

CREATE TABLE item (
    uuid              TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    family_uuid       TEXT REFERENCES item_family(uuid),
    tier              TEXT,            -- Epic | Legendary | Mythic | ... | NULL
    name              TEXT NOT NULL UNIQUE,
    source_file       TEXT NOT NULL,
    min_level         INTEGER NOT NULL DEFAULT 0,
    weapon_type       TEXT,
    damage_type       TEXT,
    armor_type        TEXT,
    is_minor_artifact INTEGER NOT NULL DEFAULT 0,
    is_raid           INTEGER NOT NULL DEFAULT 0,
    craftable_family  INTEGER NOT NULL DEFAULT 0,
    drop_location     TEXT,
    adventure_pack    TEXT
) WITHOUT ROWID;

-- Upgrade edges, from _RAID_VERSION_OF_RE and the tier prefixes.
CREATE TABLE item_upgrade (
    from_uuid TEXT NOT NULL REFERENCES item(uuid) ON DELETE CASCADE,
    to_uuid   TEXT NOT NULL REFERENCES item(uuid) ON DELETE CASCADE,
    PRIMARY KEY (from_uuid, to_uuid)
) WITHOUT ROWID;

CREATE TABLE item_slot (
    item_uuid TEXT NOT NULL REFERENCES item(uuid) ON DELETE CASCADE,
    slot      TEXT NOT NULL,
    PRIMARY KEY (item_uuid, slot)
) WITHOUT ROWID;

CREATE TABLE item_augment_slot (
    item_uuid TEXT NOT NULL REFERENCES item(uuid) ON DELETE CASCADE,
    position  INTEGER NOT NULL,        -- XML order; greedy assignment walks it
    colour    TEXT NOT NULL,
    PRIMARY KEY (item_uuid, position)
) WITHOUT ROWID;

-- CORRECTED against real data (Phase 2 implementation): `name` is NOT unique.
-- "Deathblock" names two DIFFERENT augments in different colour slots
-- (Cannith Armor Suffix vs Accessory Devastation) — the natural key is
-- name+colour, not name alone. DDOBuilderV2 also ships exactly one pair
-- ("Twilight" / Cannith Armor Prefix) sharing BOTH name and colour with
-- different bonus types — no field distinguishes them. That case has no
-- automatic resolution; the ETL reports it as a validation error and refuses
-- to load either row until a human decides (etl/transform.py).
CREATE TABLE augment (
    uuid      TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    colour    TEXT NOT NULL,
    min_level INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE INDEX augment_name_idx ON augment(name);

CREATE TABLE filigree (
    uuid          TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    name          TEXT NOT NULL UNIQUE,
    base_uuid     TEXT REFERENCES filigree_base(uuid),
    variant_label TEXT                 -- '+1 Intelligence'
) WITHOUT ROWID;

CREATE TABLE filigree_base (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) WITHOUT ROWID;

-- THE dual-set fix: two memberships are two rows.
CREATE TABLE filigree_set (
    filigree_uuid TEXT NOT NULL REFERENCES filigree(uuid) ON DELETE CASCADE,
    set_uuid      TEXT NOT NULL REFERENCES gear_set(uuid) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    PRIMARY KEY (filigree_uuid, set_uuid)
) WITHOUT ROWID;

CREATE TABLE gear_set (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) WITHOUT ROWID;

CREATE TABLE item_set (
    item_uuid TEXT NOT NULL REFERENCES item(uuid) ON DELETE CASCADE,
    set_uuid  TEXT NOT NULL REFERENCES gear_set(uuid) ON DELETE CASCADE,
    PRIMARY KEY (item_uuid, set_uuid)
) WITHOUT ROWID;

CREATE TABLE set_tier (
    uuid        TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    set_uuid    TEXT NOT NULL REFERENCES gear_set(uuid) ON DELETE CASCADE,
    piece_count INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX set_tier_set_idx ON set_tier(set_uuid, piece_count);

-- --- the stat dimension: §2.1's guards, as data ----------------------------
CREATE TABLE stat (
    uuid           TEXT PRIMARY KEY,
    raw_type       TEXT NOT NULL,      -- 'SpellPower', 'HirelingPRR', 'SkillBonus'
    raw_target     TEXT,               -- <Item>: 'Force', 'Spellcraft', NULL
    match_text     TEXT NOT NULL,      -- normalized `combined` blob
    is_skill       INTEGER NOT NULL DEFAULT 0,
    is_hireling    INTEGER NOT NULL DEFAULT 0,
    is_save        INTEGER NOT NULL DEFAULT 0,
    is_weapon_base INTEGER NOT NULL DEFAULT 0,
    UNIQUE (raw_type, raw_target)
) WITHOUT ROWID;
CREATE INDEX stat_match_idx ON stat(match_text);

CREATE TABLE effect (
    uuid        TEXT PRIMARY KEY,
    source_uuid TEXT NOT NULL REFERENCES source(uuid) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,      -- position within its source
    bonus_type  TEXT,                  -- NULL for proc presence flags
    value       REAL,
    description TEXT,
    is_rare     INTEGER NOT NULL DEFAULT 0,   -- alternate variant, not additive
    is_proc     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_uuid, ordinal)
) WITHOUT ROWID;

-- THE multi-<Item> fix. position keeps XML order, so first-wins is
-- `position = 0` and all-targets is dropping the predicate (decision 8).
--
-- IMPLEMENTATION STATUS (Phase 2): the extractors (`rules.extract`) still
-- call `buff_node.findtext('Item')` — first-<Item>-only — so they never SEE
-- the other targets to emit. Every effect currently gets exactly one
-- effect_target row at position 0. The table exists so that resolving
-- decision 8 is a change to the extractor plus one new loop in
-- etl/transform.py's emit_effects — not a schema migration.
CREATE TABLE effect_target (
    effect_uuid TEXT NOT NULL REFERENCES effect(uuid) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    stat_uuid   TEXT NOT NULL REFERENCES stat(uuid),
    PRIMARY KEY (effect_uuid, position)
) WITHOUT ROWID;

CREATE TABLE quest (
    uuid           TEXT PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    adventure_pack TEXT,
    is_raid        INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
```

Note that `effect_target` points at `stat`, not at a raw string: the `<Type>` ×
`<Item>` cross-product is resolved to canonical stat identities **in Transform**,
which is the whole "normalize before the database" requirement. `effect` carries
the amount and bonus type; `stat` carries the identity and its classification.

### 5.1.1 Versioning, and why it is recorded now

0.5.0 does not build an "update catalog" feature. It records what such a feature
would need, because **none of it can be added retroactively to a catalog that has
already shipped.** A catalog in the wild without a `catalog_version` cannot be
compared against anything; one without a `min_app_version` cannot refuse an app
that would misread it. The fields cost nothing today.

**Three versions, deliberately separate.** Collapsing any two of them is the
mistake this table exists to prevent:

| Field | Answers | Changes when |
|---|---|---|
| `schema_version` | *Can this app read this file at all?* | The DDL changes |
| `catalog_version` | *Is there a newer catalog than mine?* | Every published build, monotonically |
| `ddobuilder_commit` | *Which game data is this?* | Upstream data moves |

`ddobuilder_commit` cannot do `catalog_version`'s job: a Git SHA has no
ordering, so "is `abc123` newer than `def456`?" is unanswerable without the
upstream history — which the shipped app deliberately does not have (§2 of
START_HERE). And the same commit is legitimately rebuilt whenever an ETL bug is
fixed, which is a new catalog with identical provenance.

**Compatibility is checked in both directions:**

- the app knows the `schema_version` range it supports and refuses anything
  outside it;
- the catalog carries `min_app_version` so a *newer* catalog can refuse an older
  app with a message a human can act on, rather than being half-understood.

> [!WARNING]
> **`identity_registry_hash` is the field that protects user data.**
>
> `app.db` references catalog UUIDs. Those UUIDs are stable only because
> `etl/identity_registry.json` pins them (§6 of START_HERE) — mint-on-first-sight,
> never re-mint. A catalog built from a **divergent or missing** registry would
> silently issue different UUIDs for the same items, and every saved gearset
> would resolve to nothing.
>
> Two mitigations, both required:
> 1. The ETL **fails** if the registry is absent. It never silently mints a
>    fresh identity space.
> 2. Every catalog records the registry hash it was built from, so an update
>    that would break identity continuity is **detectable before it is
>    installed**, not after a user reports empty gearsets.

### 5.1.2 What an update feature will need beyond this table

Sketched only far enough to keep the fields above aligned with it.

- **A manifest** — a small JSON listing published catalogs with
  `catalog_version`, `schema_version`, `min_app_version`, `identity_registry_hash`,
  a download URL, byte size, and a **file checksum**. The file checksum lives in
  the manifest, not in `catalog_meta`: a file cannot contain its own hash, and
  SQLite files are not byte-reproducible anyway (`content_hash` covers the
  logical data instead).
- **A writable install location.** A downloaded catalog cannot go in the app
  bundle — signed and read-only on macOS. It belongs in the user data
  directory, alongside `app.db`.
- **A resolution rule.** With a shipped catalog and possibly a downloaded one,
  open the **highest `catalog_version` whose `schema_version` the app supports
  and whose `identity_registry_hash` matches the chain the local `app.db`
  already references**; fall back to the shipped one on any failure. The shipped
  catalog is never deleted, so a bad download is always recoverable by ignoring
  it.
- **Atomic install**, exactly as the build-time Load does: download to a temp
  file, verify checksum and `catalog_meta`, then rename.

None of this is 0.5.0 work. It is written down so that the four `catalog_meta`
fields it depends on are present in the very first catalog that ships.

### 5.2 `app.db`

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE app_meta (schema_version INTEGER NOT NULL);

CREATE TABLE build (
    uuid        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    app_version TEXT NOT NULL,

    max_level                     INTEGER NOT NULL DEFAULT 34,
    build_type                    TEXT    NOT NULL,
    weapon_style                  TEXT,
    offhand_style                 TEXT,
    weapon_damage_type            TEXT,
    swashbuckling                 INTEGER NOT NULL DEFAULT 0,
    runearm_use                   INTEGER NOT NULL DEFAULT 0,
    armor_restriction             TEXT,
    reserved_minor_artifact_slot  TEXT,
    minor_artifact_filigree_slots INTEGER NOT NULL DEFAULT 4,
    is_dino_artifact              INTEGER NOT NULL DEFAULT 0,
    exclude_gem_of_many_facets    INTEGER NOT NULL DEFAULT 0,
    raid_item_limit               INTEGER NOT NULL DEFAULT -1,
    caster_restrict_weapon_families INTEGER NOT NULL DEFAULT 1,
    max_search_time               INTEGER
) WITHOUT ROWID;

-- Ordered: intra-tier rank is array position (PriorityEntry.order).
CREATE TABLE build_priority (
    build_uuid TEXT    NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    raw_text   TEXT    NOT NULL,   -- exactly what the user typed
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    cap        REAL,
    PRIMARY KEY (build_uuid, position)
) WITHOUT ROWID;

CREATE TABLE build_excluded_pack (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    pack       TEXT NOT NULL,
    PRIMARY KEY (build_uuid, pack)
) WITHOUT ROWID;

CREATE TABLE build_caster_option (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('spellpower','school')),
    value      TEXT NOT NULL,
    PRIMARY KEY (build_uuid, kind, value)
) WITHOUT ROWID;

-- Owned inventory belongs to the PLAYER, not to one build.
CREATE TABLE owned_item (
    item_uuid   TEXT PRIMARY KEY,   -- catalog uuid; name kept for orphan reporting
    item_name   TEXT NOT NULL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

-- --- the two-node model, as a schema constraint ----------------------------
CREATE TABLE gearset_slot (
    build_uuid TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    origin     TEXT NOT NULL CHECK (origin IN ('equipped','suggested')),
    slot       TEXT NOT NULL,
    item_uuid  TEXT NOT NULL,
    item_name  TEXT NOT NULL,       -- denormalized on purpose: see §5.3
    PRIMARY KEY (build_uuid, origin, slot)
) WITHOUT ROWID;

CREATE TABLE gearset_augment (
    build_uuid  TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    origin      TEXT NOT NULL CHECK (origin IN ('equipped','suggested')),
    slot        TEXT NOT NULL,
    colour      TEXT NOT NULL,
    augment_uuid TEXT NOT NULL,
    augment_name TEXT NOT NULL,
    PRIMARY KEY (build_uuid, origin, slot, colour)
) WITHOUT ROWID;

CREATE TABLE gearset_filigree (
    build_uuid    TEXT    NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    origin        TEXT    NOT NULL CHECK (origin IN ('equipped','suggested')),
    bucket        TEXT    NOT NULL CHECK (bucket IN ('weapon','artifact')),
    position      INTEGER NOT NULL,
    filigree_uuid TEXT    NOT NULL,
    filigree_name TEXT    NOT NULL,
    PRIMARY KEY (build_uuid, origin, bucket, position)
) WITHOUT ROWID;

-- --- runs ------------------------------------------------------------------
CREATE TABLE run (
    uuid           TEXT PRIMARY KEY,
    build_uuid     TEXT NOT NULL REFERENCES build(uuid) ON DELETE CASCADE,
    mode           TEXT NOT NULL CHECK (mode IN ('optimize','recalculate','alternatives')),
    ran_at         TEXT NOT NULL,
    app_version    TEXT NOT NULL,
    catalog_commit TEXT,             -- which catalog produced these numbers
    seconds        REAL,
    succeeded      INTEGER NOT NULL,
    error_message  TEXT
) WITHOUT ROWID;

CREATE TABLE run_stat (
    run_uuid     TEXT NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    display_name TEXT NOT NULL,      -- priority spelling, or catalog name
    stat_uuid    TEXT,               -- NULL when the priority matched nothing
    value        REAL NOT NULL,
    is_priority  INTEGER NOT NULL DEFAULT 0,   -- decision 2: realized vs other
    PRIMARY KEY (run_uuid, display_name)
) WITHOUT ROWID;

CREATE TABLE run_effect (
    run_uuid    TEXT NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    stat_uuid   TEXT NOT NULL,
    bonus_type  TEXT NOT NULL,
    value       REAL NOT NULL,
    source_uuid TEXT,
    PRIMARY KEY (run_uuid, stat_uuid, bonus_type, source_uuid)
) WITHOUT ROWID;

CREATE TABLE run_active_set (
    run_uuid    TEXT NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    set_uuid    TEXT NOT NULL,
    piece_count INTEGER NOT NULL,
    PRIMARY KEY (run_uuid, set_uuid)  -- dedup is a constraint, not a habit
) WITHOUT ROWID;

CREATE TABLE run_warning (
    run_uuid TEXT    NOT NULL REFERENCES run(uuid) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    slot     TEXT,
    message  TEXT NOT NULL,
    PRIMARY KEY (run_uuid, position)
) WITHOUT ROWID;
```

### 5.3 The one deliberate denormalization

`gearset_slot` stores both `item_uuid` **and** `item_name`. That is not 3NF, and
it is on purpose: `app.db` cannot hold a foreign key into `catalog.db`, so a
UUID that no longer resolves fails silently rather than at write time.

The registry (§3.1) means a **rename** no longer causes this — the UUID
survives. Two cases still do:

- an item is **removed** from the game data outright;
- the user installs a catalog built from a divergent identity registry, which
  `catalog_meta.identity_registry_hash` is there to detect (§5.1.1).

In both, the name lets the app say *"Legendary Bracers of Wind is no longer in
the catalog"* instead of showing an empty slot. It is a **tombstone for
reporting**, never a join key — every lookup goes through `item_uuid`.

Same reasoning for `augment_name`, `filigree_name` and `owned_item.item_name`.

### 5.4 What the schema buys

Accept All becomes one statement, and the two-node invariant becomes impossible
to violate rather than merely discouraged:

```sql
INSERT OR REPLACE INTO gearset_slot (build_uuid, origin, slot, item_uuid, item_name)
SELECT build_uuid, 'equipped', slot, item_uuid, item_name
  FROM gearset_slot
 WHERE build_uuid = ? AND origin = 'suggested';
```

*"Optimize → Save wrote an empty gearset"* cannot recur: Save reads
`origin='equipped'`, and suggestions are different rows. `activeSets`
deduplication — the set with three tier rows at two pieces — is a primary key.

---

## 6. The ETL stages

**Extract** — walk the XML, emit raw records. No interpretation. This is the
only stage that knows the file layout, and it is essentially
`rules/extract.py`'s per-node extractors called with `keep_unmatched=True`.

**Transform** — where all normalization happens, in memory, before any SQL:

1. Canonicalize entity names; resolve tier prefixes and "version of" chains into
   families and upgrade edges (§2.3).
2. Split filigree base/variant; expand `A/B` dual-set names into two memberships.
3. Build the **`stat` dimension**: dedupe every `(raw_type, raw_target)` pair,
   compute `match_text` and the `is_skill` / `is_hireling` / `is_save` /
   `is_weapon_base` flags (§2.1).
4. Expand repeating `<Item>` and `<Type>` into `effect_target` rows with
   positions.
5. Mint deterministic v5 UUIDs (§3.1).
6. **Validate before loading**: every `effect_target.stat_uuid` resolves, every
   `filigree_set.set_uuid` resolves, no duplicate natural keys. A Transform that
   cannot satisfy its own referential integrity must fail loudly rather than
   load a catalog with holes.

**Load** — resolve normalized names against the DB and upsert
(`INSERT … ON CONFLICT DO UPDATE`), inside one transaction, into a temp file;
then atomically rename over `catalog.db` (§4).

> Load does no interpretation whatsoever. If a decision is being made during
> Load, it belongs in Transform. That is the property that makes the ETL
> testable: Transform's output is a pure function of the XML, so it can be
> snapshotted exactly the way `scripts/parser_snapshot.py` already snapshots the
> parsers today.

---

## 7. What this does not replace

- **Priority matching stays in Python** (§2.2) — reduced to matching a dozen
  user strings against the `stat` dimension, but still one owner.
- **The recalculation cut stays as specified.** `resolve_equipped_items` becomes
  a SQL lookup instead of a text-prescan: one function's body, not a redesign.
  Payload and response contracts unchanged.
- **0.5.0 Phases 1–2 are the prerequisite.** The per-node extractors are the
  ETL's Extract stage, and `python/rules/` is where Transform belongs. This is
  materially cheaper *because* that refactor happened.

---

## 8. Open questions

1. **Where does stacking live?** With `run_effect` populated, sum-or-max-then-sum
   is a plain SQL aggregate. Against moving it: naming and stacking are applied
   together, and splitting them across languages invites the exact drift this
   project exists to stop. Inclination: keep it in `rules/stacking.py` and treat
   SQL expressibility as a property, not a reason.
2. **`filigree_base` is modelled but must not be constrained.** 0.5.0 Phase 0
   found `optimizer.py:1817` limiting one filigree per base name per bucket,
   which made a real gearset unevaluatable — and two filigrees sharing a base are
   two pieces of the same set, which sets *need*. Model it; build nothing on it
   until that is settled.
3. **Sharing.** A file can be sent to someone; a database cannot. Recommend
   keeping `.ddogearset` as an **export/import** format while SQLite becomes the
   storage, so the 0.5.0 compatibility break stays a one-time cost rather than a
   permanent loss of a feature.
4. **Does `catalog.db` ship prebuilt?** It can, making first run instant, but it
   must be invalidated when the fetched DDOBuilderV2 commit differs from
   `catalog_meta.ddobuilder_commit`.

---

## 9. Sequencing

Superseded by [`00_ETL_START_HERE.md`](00_ETL_START_HERE.md) §8. In short:
`catalog.db` is **0.5.0**; `app.db` **and recalculation** are **0.5.1**; UI
implications are **0.5.2**.

`mode: "calculate"` survives 0.5.0 unchanged — it captures the oracle and stays
the Calculate button — and is replaced by `mode: "recalculate"` in 0.5.1. See
START_HERE §9.
