"""Load — writes a TransformResult to an actual catalog.db.

See docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1 for the DDL this mirrors, and
docs/0.5.0/00_ETL_START_HERE.md §5.1.1/§5.1.2 for what `catalog_meta` records
and why. Load does no interpretation — every decision (identity, entity
resolution, the stat dimension, validation) already happened in Transform. If
this file is making a decision, that decision is in the wrong file.

Writes to a TEMP file and atomically renames over the target, so an
interrupted build never leaves a half-populated catalog.db in place — the
same discipline the (not-yet-built) update feature will need for a downloaded
catalog. See §4 of the schema doc.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from .transform import TransformResult

SCHEMA_VERSION = 1

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE catalog_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version          INTEGER NOT NULL,
    catalog_version         INTEGER NOT NULL,
    built_at                TEXT    NOT NULL,
    ddobuilder_commit       TEXT    NOT NULL,
    etl_version             TEXT    NOT NULL,
    source_file_count       INTEGER NOT NULL,
    min_app_version         TEXT    NOT NULL,
    content_hash            TEXT    NOT NULL,
    identity_registry_hash  TEXT    NOT NULL
);

CREATE TABLE source (
    uuid TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('item','augment','filigree','set_tier')),
    name TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX source_name_idx ON source(name);

CREATE TABLE item_family (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) WITHOUT ROWID;

CREATE TABLE item (
    uuid              TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    family_uuid       TEXT REFERENCES item_family(uuid),
    tier              TEXT,
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

-- Known gap: not populated in 0.5.0 (etl/transform.py's `transform()`
-- docstring). Created so a future ETL pass needs no migration to fill it.
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
    position  INTEGER NOT NULL,
    colour    TEXT NOT NULL,
    PRIMARY KEY (item_uuid, position)
) WITHOUT ROWID;

CREATE TABLE augment (
    uuid      TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    colour    TEXT NOT NULL,
    min_level INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE INDEX augment_name_idx ON augment(name);

CREATE TABLE filigree_base (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) WITHOUT ROWID;

CREATE TABLE filigree (
    uuid          TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    name          TEXT NOT NULL UNIQUE,
    base_uuid     TEXT REFERENCES filigree_base(uuid),
    variant_label TEXT
) WITHOUT ROWID;

CREATE TABLE gear_set (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) WITHOUT ROWID;

CREATE TABLE filigree_set (
    filigree_uuid TEXT NOT NULL REFERENCES filigree(uuid) ON DELETE CASCADE,
    set_uuid      TEXT NOT NULL REFERENCES gear_set(uuid) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    PRIMARY KEY (filigree_uuid, set_uuid)
) WITHOUT ROWID;

CREATE TABLE item_set (
    item_uuid TEXT NOT NULL REFERENCES item(uuid) ON DELETE CASCADE,
    set_uuid  TEXT NOT NULL REFERENCES gear_set(uuid) ON DELETE CASCADE,
    PRIMARY KEY (item_uuid, set_uuid)
) WITHOUT ROWID;

-- origin_hint is NOT meaningful game data (see etl/walk.py's RawSetTier
-- docstring) — purely which DDOBuilderV2 file a tier definition came from.
-- Kept because two historical code paths read the two files separately and
-- the Phase 1 differential snapshot still proves parity against each.
CREATE TABLE set_tier (
    uuid        TEXT PRIMARY KEY REFERENCES source(uuid) ON DELETE CASCADE,
    set_uuid    TEXT NOT NULL REFERENCES gear_set(uuid) ON DELETE CASCADE,
    piece_count INTEGER NOT NULL,
    origin_hint TEXT NOT NULL DEFAULT 'top_level'
) WITHOUT ROWID;
CREATE INDEX set_tier_set_idx ON set_tier(set_uuid, piece_count);

CREATE TABLE stat (
    uuid           TEXT PRIMARY KEY,
    raw_type       TEXT NOT NULL,
    raw_target     TEXT,
    match_text     TEXT NOT NULL,
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
    ordinal     INTEGER NOT NULL,
    bonus_type  TEXT,
    value       REAL,
    description TEXT,
    is_rare     INTEGER NOT NULL DEFAULT 0,
    is_proc     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_uuid, ordinal)
) WITHOUT ROWID;

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
"""


def _content_hash(result: TransformResult) -> str:
    """Hash of the LOGICAL content, not the file — SQLite files are not
    byte-reproducible (page ordering, freelist), so a file hash cannot answer
    "did the data change?" (schema doc §5.1.1). Every row list is sorted
    canonically before hashing so row ORDER — an artefact of dict/set
    iteration, not a property of the data — can never affect the hash."""
    h = hashlib.sha256()
    for name in sorted(vars(result).keys()):
        val = getattr(result, name)
        if not isinstance(val, list):
            continue
        rows = [json.dumps(row, sort_keys=True, default=str) for row in val]
        rows.sort()
        h.update(name.encode())
        for row in rows:
            h.update(row.encode())
    return h.hexdigest()


def _registry_hash(registry_path: Path) -> str:
    if not registry_path.exists():
        return "absent"
    return hashlib.sha256(registry_path.read_bytes()).hexdigest()


def _insert_many(conn: sqlite3.Connection, table: str, rows: list, columns: list) -> None:
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)
    conn.executemany(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
        [tuple(row.get(c) for c in columns) for row in rows],
    )


def build_catalog(result: TransformResult, out_path: Path, *, registry_path: Path,
                  ddobuilder_commit: str, etl_version: str, source_file_count: int,
                  min_app_version: str, catalog_version: int, built_at: str) -> None:
    """Writes `result` to `out_path`. Raises if `result.validation_errors` is
    non-empty — Load refuses to write a catalog Transform itself flagged as
    broken, regardless of --strict (that flag governs identity DRIFT, a
    separate concern; a referential-integrity failure is never buildable)."""
    if result.validation_errors:
        raise ValueError(
            f"refusing to load a catalog with {len(result.validation_errors)} "
            f"validation error(s): {result.validation_errors[:5]}"
            + (" ..." if len(result.validation_errors) > 5 else "")
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(out_path.parent), suffix=".db.tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    tmp_path.unlink()  # sqlite3.connect must create it fresh

    try:
        conn = sqlite3.connect(str(tmp_path))
        try:
            conn.executescript(DDL)

            _insert_many(conn, "source", result.sources, ["uuid", "kind", "name"])
            _insert_many(conn, "item_family", result.item_families, ["uuid", "name"])
            _insert_many(conn, "item", result.items, [
                "uuid", "family_uuid", "tier", "name", "source_file", "min_level",
                "weapon_type", "damage_type", "armor_type", "is_minor_artifact",
                "is_raid", "craftable_family", "drop_location", "adventure_pack"])
            _insert_many(conn, "item_slot", result.item_slots, ["item_uuid", "slot"])
            _insert_many(conn, "item_augment_slot", result.item_augment_slots,
                        ["item_uuid", "position", "colour"])
            _insert_many(conn, "augment", result.augments,
                        ["uuid", "name", "colour", "min_level"])
            _insert_many(conn, "gear_set", result.gear_sets, ["uuid", "name"])
            _insert_many(conn, "item_set", result.item_sets, ["item_uuid", "set_uuid"])
            _insert_many(conn, "filigree_base", result.filigree_bases, ["uuid", "name"])
            _insert_many(conn, "filigree", result.filigrees,
                        ["uuid", "name", "base_uuid", "variant_label"])
            _insert_many(conn, "filigree_set", result.filigree_sets,
                        ["filigree_uuid", "set_uuid", "position"])
            _insert_many(conn, "set_tier", result.set_tiers,
                        ["uuid", "set_uuid", "piece_count", "origin_hint"])
            _insert_many(conn, "stat", result.stats, [
                "uuid", "raw_type", "raw_target", "match_text", "is_skill",
                "is_hireling", "is_save", "is_weapon_base"])
            _insert_many(conn, "effect", result.effects, [
                "uuid", "source_uuid", "ordinal", "bonus_type", "value",
                "is_proc"])
            _insert_many(conn, "effect_target", result.effect_targets,
                        ["effect_uuid", "position", "stat_uuid"])
            _insert_many(conn, "quest", result.quests,
                        ["uuid", "name", "adventure_pack", "is_raid"])

            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                raise ValueError(f"foreign_key_check failed: {fk_violations[:10]}")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if integrity[0] != "ok":
                raise ValueError(f"integrity_check failed: {integrity[0]}")

            conn.execute(
                "INSERT INTO catalog_meta (id, schema_version, catalog_version, "
                "built_at, ddobuilder_commit, etl_version, source_file_count, "
                "min_app_version, content_hash, identity_registry_hash) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (SCHEMA_VERSION, catalog_version, built_at, ddobuilder_commit,
                 etl_version, source_file_count, min_app_version,
                 _content_hash(result), _registry_hash(registry_path)),
            )
            conn.commit()
        finally:
            conn.close()

        # Atomic on POSIX and on Windows for os.replace specifically (unlike
        # os.rename, which is NOT atomic-over-existing-file on Windows).
        os.replace(str(tmp_path), str(out_path))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
