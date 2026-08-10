"""Transform — turns a walked Corpus into row lists ready for Load.

See docs/0.5.0/00_ETL_START_HERE.md §7 and
docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1 for what each table means. This
module does ALL interpretation: entity resolution, the stat dimension,
identity minting, and referential-integrity validation. Load (etl/load.py, not
yet written) does none — if a decision is being made there, it belongs here
instead.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .identity import NAMESPACES, Registry
from .stat_dimension import StatDimension
from .walk import Corpus

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "python"))
from rules.constants import PROC_BONUS_TYPE  # noqa: E402

# Mirrors rules.provenance.RAID_UPGRADE_TIER_PREFIXES — duplicated rather than
# imported so entity resolution here stays a pure function of strings, with no
# dependency surprise if that tuple's meaning ever drifts for the SEARCH side.
_TIER_PREFIXES = ("Epic ", "Legendary ", "Mythic ", "Perfected ", "Elite ")

# Effects are not registry-tracked identity: NS_EFFECT = source uuid + ordinal
# (schema doc §3.1). They regenerate identically on every rebuild by
# construction — a rebuild with the same source content always re-derives the
# same effect UUID — so there is nothing here for the registry to preserve.
_NS_EFFECT = NAMESPACES["item"]  # any fixed namespace works; this one is stable


def _mint_effect_uuid(source_uuid: str, ordinal: int) -> str:
    return str(_uuid.uuid5(_NS_EFFECT, f"{source_uuid}:{ordinal}"))


def _family_and_tier(name: str) -> Tuple[str, Optional[str]]:
    """('Bracers of Wind', 'Legendary') for 'Legendary Bracers of Wind';
    (name, None) for anything with no recognised tier prefix."""
    for prefix in _TIER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):], prefix.strip()
    return name, None


@dataclass
class TransformResult:
    # Rows, shaped to match the catalog.db columns in
    # docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1. Kept as plain dicts, not
    # tied to any DB library, so Load can be swapped without touching this.
    sources: List[dict] = field(default_factory=list)
    item_families: List[dict] = field(default_factory=list)
    items: List[dict] = field(default_factory=list)
    item_slots: List[dict] = field(default_factory=list)
    item_augment_slots: List[dict] = field(default_factory=list)
    item_sets: List[dict] = field(default_factory=list)
    augments: List[dict] = field(default_factory=list)
    gear_sets: List[dict] = field(default_factory=list)
    filigree_bases: List[dict] = field(default_factory=list)
    filigrees: List[dict] = field(default_factory=list)
    filigree_sets: List[dict] = field(default_factory=list)
    set_tiers: List[dict] = field(default_factory=list)
    stats: List[dict] = field(default_factory=list)
    effects: List[dict] = field(default_factory=list)
    effect_targets: List[dict] = field(default_factory=list)
    quests: List[dict] = field(default_factory=list)

    validation_errors: List[str] = field(default_factory=list)
    registry: Optional[Registry] = None


def transform(corpus: Corpus, registry: Registry, *, built_at: str,
             commit: str, aliases: Dict[str, Dict[str, Optional[str]]],
             strict: bool) -> TransformResult:
    """KNOWN GAP: `item_upgrade` (schema doc §5.1's from_uuid/to_uuid edges,
    derived from `_RAID_VERSION_OF_RE`) is not populated. `item_family`
    already groups an item with its tier siblings via `_family_and_tier`,
    which is what every 0.5.0/0.5.1 feature actually needs (family grouping,
    not directed upgrade chains). Load still creates the `item_upgrade`
    table, empty, for schema completeness — nothing reads it yet, and adding
    the edges later needs no migration."""
    r = TransformResult(registry=registry)
    aliases = aliases or {}

    dim = StatDimension()
    gear_set_uuid: Dict[str, str] = {}
    item_family_uuid: Dict[str, str] = {}

    def gear_set_id(name: str) -> str:
        if name not in gear_set_uuid:
            ent = registry.resolve("gear_set", name, built_at=built_at,
                                   commit=commit, strict=strict)
            gear_set_uuid[name] = ent.entity_uuid
            r.gear_sets.append({"uuid": ent.entity_uuid, "name": name})
        return gear_set_uuid[name]

    def stat_id(raw_type: str, raw_target: Optional[str]) -> str:
        key = dim.observe(raw_type, raw_target)
        ent = registry.resolve("stat", key.natural_key(), built_at=built_at,
                               commit=commit, strict=strict)
        return ent.entity_uuid

    def emit_effects(source_uuid: str, buffs: list) -> None:
        """`buffs` entries are 4-tuples from the extractors called with
        with_raw=True: (display_name, bonus_type, value, (raw_type, raw_target)).
        The display name is NOT stored — it exists only to drive the live
        solver's priority match and has no place in a priority-agnostic
        catalog. `effect` and `effect_target` are separate tables, matching the
        schema doc §5.1 exactly: `effect` is the (source, ordinal, bonus_type,
        value) tuple, `effect_target` is a distinct table of WHICH stat(s) it
        applies to, because a single `<Effect>` can legitimately grant one
        amount to several `<Item>` targets (Force/Physical/Untyped) or several
        `<Type>` stats.

        SCOPING NOTE (matches decision 8, out of scope for 0.5.0 — see
        docs/0.5.0/00_ETL_START_HERE.md §9.3): `_item_buffs_from_node` still
        calls `buff_node.findtext('Item')`, which reads only the FIRST <Item>
        of a repeating set — the extractor never sees the other targets, so
        this ETL cannot yet emit more than one `effect_target` row per effect.
        Every effect gets exactly one target row at position 0. The table
        exists so that changing first-wins to all-targets, if that
        investigation concludes it should, is a change to the extractor plus
        one new loop here — not a schema migration.
        """
        for ordinal, entry in enumerate(buffs):
            _display, bonus_type, value, raw_pair = entry
            raw_type, raw_target = raw_pair
            eff_uuid = _mint_effect_uuid(source_uuid, ordinal)
            r.effects.append({
                "uuid": eff_uuid,
                "source_uuid": source_uuid,
                "ordinal": ordinal,
                "bonus_type": bonus_type,
                "value": value,
                "is_proc": bonus_type == PROC_BONUS_TYPE,
            })
            r.effect_targets.append({
                "effect_uuid": eff_uuid,
                "position": 0,
                "stat_uuid": stat_id(raw_type, raw_target),
            })

    # --- items ---------------------------------------------------------
    seen_item_names = set()
    for it in corpus.items:
        seen_item_names.add(it.node_name)
        src = registry.resolve("item", it.node_name, built_at=built_at,
                               commit=commit, strict=strict)
        family_name, tier = _family_and_tier(it.node_name)
        if family_name not in item_family_uuid:
            fam_ent = registry.resolve("item_family", family_name,
                                       built_at=built_at, commit=commit, strict=strict)
            item_family_uuid[family_name] = fam_ent.entity_uuid
            r.item_families.append({"uuid": fam_ent.entity_uuid, "name": family_name})

        r.sources.append({"uuid": src.entity_uuid, "kind": "item", "name": it.node_name})
        r.items.append({
            "uuid": src.entity_uuid,
            "family_uuid": item_family_uuid[family_name],
            "tier": tier,
            "name": it.node_name,
            "source_file": it.file,
            "min_level": it.ml,
            "weapon_type": it.weapon_type,
            "damage_type": it.damage_type,
            "armor_type": it.armor_type,
            "is_minor_artifact": it.minor,
            "is_raid": it.is_raid,
            "craftable_family": it.craftable_family,
            "drop_location": it.drop_location,
            "adventure_pack": it.pack,
        })
        for slot in it.slots:
            r.item_slots.append({"item_uuid": src.entity_uuid, "slot": slot})
        for position, colour in enumerate(it.augment_slots):
            r.item_augment_slots.append({
                "item_uuid": src.entity_uuid, "position": position, "colour": colour})
        for set_name in it.sets:
            r.item_sets.append({
                "item_uuid": src.entity_uuid, "set_uuid": gear_set_id(set_name)})
        emit_effects(src.entity_uuid, it.buffs)

    registry.reconcile_disappeared("item", seen_item_names, aliases.get("item", {}))

    # --- augments --------------------------------------------------------
    # Name alone is NOT a valid natural key: measured on the real corpus,
    # "Deathblock" names two DIFFERENT augments in different colour slots
    # (Cannith Armor Suffix vs Accessory Devastation), and DDOBuilderV2 also
    # ships EXACTLY TWO "Twilight" / "Cannith Armor Prefix" augments that
    # share both name AND colour but differ in bonus type (Equipment vs
    # Enhancement) — no field distinguishes them. The key is `name + colour`;
    # a same-name-same-colour collision is a genuine data ambiguity and is
    # reported as a validation error rather than silently merged or dropped.
    seen_augment_keys = set()
    augment_key_seen_names: Dict[str, str] = {}
    for aug in corpus.augments:
        natural_key = f"{aug.name}\x1f{aug.type}"
        if natural_key in augment_key_seen_names:
            r.validation_errors.append(
                f"augment identity collision: '{aug.name}' ({aug.type}) appears "
                f"more than once with no field to disambiguate — not merged, "
                f"not loaded. Needs a human decision (docs/0.5.0/00_ETL_START_HERE.md §6).")
            continue
        augment_key_seen_names[natural_key] = aug.name
        seen_augment_keys.add(natural_key)

        src = registry.resolve("augment", natural_key, built_at=built_at,
                               commit=commit, strict=strict)
        r.sources.append({"uuid": src.entity_uuid, "kind": "augment", "name": aug.name})
        r.augments.append({
            "uuid": src.entity_uuid, "name": aug.name, "colour": aug.type,
            "min_level": aug.min_level})
        emit_effects(src.entity_uuid, aug.buffs)
    registry.reconcile_disappeared("augment", seen_augment_keys, aliases.get("augment", {}))

    # --- filigrees ---------------------------------------------------------
    seen_filigree_names = set()
    filigree_base_uuid: Dict[str, str] = {}
    for f in corpus.filigrees:
        seen_filigree_names.add(f.name)
        src = registry.resolve("filigree", f.name, built_at=built_at,
                               commit=commit, strict=strict)
        if f.base_name not in filigree_base_uuid:
            base_ent = registry.resolve("filigree_base", f.base_name,
                                        built_at=built_at, commit=commit, strict=strict)
            filigree_base_uuid[f.base_name] = base_ent.entity_uuid
            r.filigree_bases.append({"uuid": base_ent.entity_uuid, "name": f.base_name})

        r.sources.append({"uuid": src.entity_uuid, "kind": "filigree", "name": f.name})
        variant_label = f.name[len(f.base_name):].lstrip(': ').strip() or None
        r.filigrees.append({
            "uuid": src.entity_uuid, "name": f.name,
            "base_uuid": filigree_base_uuid[f.base_name],
            "variant_label": variant_label,
        })
        # THE dual-set fix (schema doc §2.3): walk.py already re-derives ALL
        # <SetBonus> memberships, not just findtext's first — this is where
        # each becomes its own row instead of a lost second membership.
        for position, set_name in enumerate(f.sets):
            r.filigree_sets.append({
                "filigree_uuid": src.entity_uuid,
                "set_uuid": gear_set_id(set_name),
                "position": position,
            })
        emit_effects(src.entity_uuid, f.buffs)
    registry.reconcile_disappeared("filigree", seen_filigree_names, aliases.get("filigree", {}))

    # --- set tiers ---------------------------------------------------------
    # DDOBuilderV2 genuinely repeats (set_name, piece_count): measured on the
    # real corpus, 212 of 965 <Buff EquippedCount=N> rows share their
    # (set, piece_count) with at least one sibling — e.g. "Legendary
    # Inevitable Balance" has FOUR separate 2-piece rows. These describe ONE
    # active tier with several effects, not several tiers — see START_HERE's
    # carried-forward finding (originally 0.5.0 docs §4.5): "emit the
    # (N-piece) label once or the UI shows it three times." So rows sharing a
    # (set_name, piece_count) are MERGED here, before minting — one set_tier
    # entity, one contiguous ordinal sequence, every buff from every row.
    # Processing them independently would resolve to the SAME uuid (the
    # natural key is exactly (set_name, piece_count)) while calling
    # emit_effects separately per row, which restarts `ordinal` at 0 each
    # time and collides effect UUIDs across rows — caught by this build's
    # validation the first time this was tried.
    tier_groups: Dict[Tuple[str, int], list] = {}
    for st in corpus.set_tiers:
        tier_groups.setdefault((st.set_name, st.piece_count), []).extend(st.buffs)

    for (set_name, piece_count), merged_buffs in tier_groups.items():
        set_uuid = gear_set_id(set_name)
        tier_key = f"{set_name}\x1f{piece_count}"
        src = registry.resolve("set_tier", tier_key, built_at=built_at,
                               commit=commit, strict=strict)
        r.sources.append({"uuid": src.entity_uuid, "kind": "set_tier",
                          "name": f"{set_name} ({piece_count}-piece)"})
        r.set_tiers.append({
            "uuid": src.entity_uuid, "set_uuid": set_uuid,
            "piece_count": piece_count})
        emit_effects(src.entity_uuid, merged_buffs)

    # --- quests --------------------------------------------------------
    seen_quest_names = set()
    for name, info in corpus.quests.items():
        seen_quest_names.add(name)
        quest_ent = registry.resolve("quest", name, built_at=built_at,
                                     commit=commit, strict=strict)
        r.quests.append({
            "uuid": quest_ent.entity_uuid,
            "name": name, "adventure_pack": info.get("AdventurePack"),
            "is_raid": bool(info.get("is_raid")),
        })
    registry.reconcile_disappeared("quest", seen_quest_names, aliases.get("quest", {}))

    # --- the stat dimension, now fully populated by every emit_effects() call
    for key, row in dim:
        stat_ent = registry.resolve("stat", key.natural_key(), built_at=built_at,
                                    commit=commit, strict=strict)
        r.stats.append({
            "uuid": stat_ent.entity_uuid,
            "raw_type": key.raw_type,
            "raw_target": key.raw_target,
            "match_text": row.match_text,
            "is_skill": row.is_skill,
            "is_hireling": row.is_hireling,
            "is_save": row.is_save,
            "is_weapon_base": row.is_weapon_base,
        })

    r.validation_errors.extend(_validate(r))
    return r


def _validate(r: TransformResult) -> List[str]:
    """Referential integrity, checked before Load ever sees this data. A
    Transform that cannot satisfy its own foreign keys fails loudly rather
    than loading a catalog with holes (docs/0.5.0/00_ETL_START_HERE.md §8
    Phase 2 gate)."""
    errors: List[str] = []

    source_uuids = {s["uuid"] for s in r.sources}
    stat_uuids = {s["uuid"] for s in r.stats}
    effect_uuids = {e["uuid"] for e in r.effects}
    for eff in r.effects:
        if eff["source_uuid"] not in source_uuids:
            errors.append(f"effect {eff['uuid']} references unknown source {eff['source_uuid']}")
    for tgt in r.effect_targets:
        if tgt["effect_uuid"] not in effect_uuids:
            errors.append(f"effect_target references unknown effect {tgt['effect_uuid']}")
        if tgt["stat_uuid"] not in stat_uuids:
            errors.append(f"effect_target references unknown stat {tgt['stat_uuid']}")
    # Every effect must have at least one target — an effect with none would
    # be a value with no meaning, and Load's FK on effect_target can't catch
    # an ABSENCE the way it catches a bad reference.
    targeted_effects = {tgt["effect_uuid"] for tgt in r.effect_targets}
    for eff in r.effects:
        if eff["uuid"] not in targeted_effects:
            errors.append(f"effect {eff['uuid']} has no effect_target row")

    set_uuids = {s["uuid"] for s in r.gear_sets}
    for row in r.item_sets:
        if row["set_uuid"] not in set_uuids:
            errors.append(f"item_set references unknown set {row['set_uuid']}")
    for row in r.filigree_sets:
        if row["set_uuid"] not in set_uuids:
            errors.append(f"filigree_set references unknown set {row['set_uuid']}")
    for row in r.set_tiers:
        if row["set_uuid"] not in set_uuids:
            errors.append(f"set_tier references unknown set {row['set_uuid']}")

    item_uuids = {i["uuid"] for i in r.items}
    for row in r.item_slots:
        if row["item_uuid"] not in item_uuids:
            errors.append(f"item_slot references unknown item {row['item_uuid']}")
    for row in r.item_augment_slots:
        if row["item_uuid"] not in item_uuids:
            errors.append(f"item_augment_slot references unknown item {row['item_uuid']}")
    for row in r.item_sets:
        if row["item_uuid"] not in item_uuids:
            errors.append(f"item_set references unknown item {row['item_uuid']}")

    filigree_base_uuids = {b["uuid"] for b in r.filigree_bases}
    for row in r.filigrees:
        if row["base_uuid"] not in filigree_base_uuids:
            errors.append(f"filigree {row['uuid']} references unknown base {row['base_uuid']}")

    family_uuids = {f["uuid"] for f in r.item_families}
    for row in r.items:
        if row["family_uuid"] not in family_uuids:
            errors.append(f"item {row['uuid']} references unknown family {row['family_uuid']}")

    # NOT a check on `sources.name`: two sources legitimately share a display
    # name (measured on real data — "Deathblock" names two different Cannith
    # armor augments in different colour slots). The identity guarantee that
    # actually matters is UUID uniqueness — every row in `sources` came from
    # exactly one `registry.resolve` call, so a repeated uuid means the same
    # entity was appended to the row lists more than once, a real bug.
    seen_uuids: Dict[str, int] = {}
    for s in r.sources:
        seen_uuids[s["uuid"]] = seen_uuids.get(s["uuid"], 0) + 1
    for uuid_, n in seen_uuids.items():
        if n > 1:
            errors.append(f"source {uuid_} appended to `sources` {n} times — "
                          f"the same entity was processed more than once")

    return errors
