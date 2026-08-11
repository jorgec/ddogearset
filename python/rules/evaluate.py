"""Evaluate a fixed gearset — recalculation, with no solver anywhere in it.

0.5.1 Phase 4 (docs/0.5.1/00_APP_DB_START_HERE.md). This is the module the whole
ETL direction existed to reach: `_collect_contributions` + `_resolve_totals`
already evaluated a fixed gearset by direct arithmetic and always did, so
answering *"what does the gear I have equipped total to"* never needed an ILP.
Until now it borrowed one anyway — `mode: "calculate"` built the full candidate
pool, declared every piece pinned, and solved a model whose answer was already
determined.

What that cost was not only time. A search heuristic reaching into an
evaluation could REFUSE to answer: `optimizer.py:1817` limits one filigree per
base name per bucket, which is a statement about what the solver may PROPOSE,
and it made a gearset a real user actually has unevaluatable
(python/tests/fixtures/known_deltas.yaml, `unevaluatable_today`). Nothing here
can do that. There is no candidate pool to restrict, no constraint to violate,
and no way to express a restriction — see `solver.py`'s recalculate branch,
which rejects a payload that carries one.

Part of `python/rules/`: no `pulp`, no search restrictions, no knowledge of how
the gear was chosen.
"""

import collections

from .naming import normalize_stat_key
from .stacking import _collect_contributions, _is_stacking, _resolve_totals

# Reported when a gearset is self-inconsistent in a way that is worth telling
# the user about but must never stop the numbers coming back. See
# validate_physical_rules.
WARN_DUPLICATE_FILIGREE = "duplicate-filigree"
WARN_EMPTY_FILIGREE = "empty-filigree-entry"
WARN_UNKNOWN_NAME = "unknown-name"


def validate_physical_rules(equipped, fil_weapon, fil_artifact, unresolved=None):
    """Report what is odd about a gearset. **Warns, never refuses.**

    That policy is the point, carried from the deprecated recalculation spec.
    Every rule here describes something the game itself would not allow or that
    indicates corrupted saved data — but a user looking at their own gearset is
    owed the numbers plus a note, not a refusal. The one rule deliberately NOT
    checked is `<= 1 filigree per base name per bucket`: two filigrees sharing a
    base name are two pieces of the same named set, which set bonuses need, and
    treating it as an error is what made a real gearset unevaluatable.
    """
    warnings = []

    for bucket, entries in (("weapon", fil_weapon), ("artifact", fil_artifact)):
        names = [f.get('name') for f in entries]
        blanks = sum(1 for n in names if not (n or '').strip())
        if blanks:
            warnings.append({
                "kind": WARN_EMPTY_FILIGREE, "slot": bucket,
                "message": f"{blanks} empty filigree slot(s) in the {bucket} bucket.",
            })
        seen = collections.Counter(n for n in names if (n or '').strip())
        for name, times in sorted(seen.items()):
            if times > 1:
                warnings.append({
                    "kind": WARN_DUPLICATE_FILIGREE, "slot": bucket,
                    "message": f"'{name}' is slotted {times} times in the {bucket} "
                               "bucket; the game allows each filigree once.",
                })

    for entry in unresolved or []:
        warnings.append({
            "kind": WARN_UNKNOWN_NAME, "slot": entry.get("slot"),
            "message": f"'{entry.get('name')}' is not in the catalog and "
                       "contributed nothing.",
        })

    return warnings


def _buff_dicts(buffs):
    return [{"stat": st, "bonus": bt, "value": v} for st, bt, v in buffs]


def _active_set_tiers(equipped, fil_weapon, fil_artifact, sets):
    """(set_name, piece_count) pairs the gearset actually activates.

    Deduplicated by construction: a set with three separate 2-piece rows in the
    data is ONE active tier, and reporting it three times is the defect
    `run_active_set`'s primary key exists to prevent (schema §5.4).
    """
    piece_counts = collections.Counter()
    for _slot, item in equipped:
        for k in item.get('sets', []) or []:
            piece_counts[k] += 1
    for f in list(fil_weapon) + list(fil_artifact):
        if f.get('set'):
            piece_counts[f['set']] += 1

    active = []
    for name, tiers in sets.items():
        pieces = piece_counts.get(name, 0)
        for count in sorted(tiers):
            if pieces >= count:
                active.append((name, count))
    return active


def evaluate_gearset(equipped, augments_by_slot, fil_weapon, fil_artifact, sets,
                     entries, unresolved=None):
    """Total up a gearset and describe where every number came from.

    Arguments mirror what the gearset IS, not how it was found:
      equipped          [(slot, item)] — the items, in slot order
      augments_by_slot  {slot: [augment]}
      fil_weapon        [filigree] in the weapon bucket
      fil_artifact      [filigree] in the minor-artifact bucket
      sets              {set_name: {piece_count: [(stat, bonus, value)]}}
      entries           the user's parsed priorities (for realizedStats/tiers)
      unresolved        names that matched nothing, reported as warnings

    Returns the same result shape a solve does, so nothing downstream — the Go
    app, the frontend, the oracle differential — needs to know which produced
    it.
    """
    aug_list = [a for slot_augs in augments_by_slot.values() for a in slot_augs]
    contrib = _collect_contributions(equipped, aug_list, fil_weapon, fil_artifact, sets)
    totals = _resolve_totals(contrib)

    # --- realizedStats / otherStats -------------------------------------
    #
    # Split per the deprecated spec's decision 2, carried into 0.5.1:
    # realizedStats holds the stats the user ASKED for, spelled the way they
    # spelled them; otherStats holds everything else the gear happens to grant.
    # One dictionary conflating the two is why a priority that matched nothing
    # used to be indistinguishable from one the gear simply did not provide.
    realized = {}
    claimed_keys = set()
    for entry in entries:
        base = entry.stat
        if base in realized:
            continue
        total = 0.0
        for stat, value in totals.items():
            if stat.lower() == base.lower():
                total += value
                claimed_keys.add(stat)
        if total > 0:
            realized[base] = total

    other = {stat: value for stat, value in totals.items()
             if stat not in claimed_keys and value}

    # --- allEffects: the contributions that actually reach the total ------
    #
    # Filtered the same way `_resolve_totals` aggregates: stacking bonus types
    # add, so every source of one counts; every other type takes the MAX, so a
    # smaller source of that type contributes exactly nothing.
    #
    # Listing the losers would read as additive and inflate what the user
    # believes their gear is doing — "Legendary Inevitable Balance (2 Piece)"
    # grants both a Stacking and an Artifact bonus to Doublestrike, and the
    # Artifact one is entirely overridden by a larger Artifact source. The solve
    # path reported it this way too (its `sources_tracking` only surfaced the
    # source whose variable won), so this is the established meaning of the
    # field, not a new one.
    all_effects = {}
    all_effects_detail = {}
    for (stat, b_type), rows in contrib.items():
        if _is_stacking(b_type):
            reaching = rows
        else:
            best = max(value for value, _o, _n in rows)
            reaching = [r for r in rows if r[0] == best]
        for value, origin, source_name in reaching:
            all_effects.setdefault(stat, []).append(
                f"{value} {b_type} ({source_name})")
            # The same information, already parsed. The frontend used to pull
            # the value, bonus type and source back OUT of the string above with
            # a regex (`parseEffectSource`), which is a parser for a format this
            # side had in structured form all along and flattened on the way
            # out. `allEffects` stays exactly as it was so the oracle
            # differential keeps comparing it.
            all_effects_detail.setdefault(stat, []).append({
                "value": value, "bonusType": b_type,
                "sourceName": source_name, "sourceKind": origin,
            })

    # --- active sets ------------------------------------------------------
    active_tiers = _active_set_tiers(equipped, fil_weapon, fil_artifact, sets)
    active_sets = [f"{name} ({count}-piece)" for name, count in active_tiers]

    # --- per-slot detail --------------------------------------------------
    equipped_simple = {slot: item['name'] for slot, item in equipped}
    active_lookup = collections.defaultdict(list)
    for name, count in active_tiers:
        active_lookup[name].append(count)

    slots_out = {}
    for slot, item in equipped:
        slot_sets = []
        for name in item.get('sets', []) or []:
            for count in active_lookup.get(name, []):
                slot_sets.append({
                    "set": name, "pieces": count,
                    "buffs": _buff_dicts(sets.get(name, {}).get(count, [])),
                })

        # Filigrees do not belong to a literal slot — they belong to the
        # Sentient Weapon as a whole, or to the Minor Artifact item (see
        # docs/USAGE.md). Attached to whichever slots carry that concept, which
        # is what the solve path does too.
        slot_filigrees = []
        if slot in ('Weapon1', 'Weapon2'):
            slot_filigrees = [{"name": f['name'], "buffs": _buff_dicts(f['buffs'])}
                              for f in fil_weapon]
        elif item.get('minor'):
            slot_filigrees = [{"name": f['name'], "buffs": _buff_dicts(f['buffs'])}
                              for f in fil_artifact]

        slots_out[slot] = {
            "location": slot,
            "item": {
                "name": item['name'],
                "file": item.get('file'),
                "ml": item.get('ml', 0),
                "is_raid": item.get('is_raid', False),
                "pack": item.get('pack'),
                "minor": item.get('minor', False),
            },
            "augments": [
                {"color": a.get('type'), "name": a['name'], "buffs": _buff_dicts(a['buffs'])}
                for a in augments_by_slot.get(slot, [])
            ],
            "filigrees": slot_filigrees,
            "set_bonus_contributions": slot_sets,
        }

    # --- priorities that this gearset does not satisfy --------------------
    #
    # unmetTier4 is "tier-4 priorities the gearset grants nothing toward".
    # Computed from the totals rather than from solver state, which is the same
    # question asked directly instead of inferred from a model variable.
    unmet_tier4 = sorted({
        entry.stat for entry in entries
        if entry.tier == 4 and entry.stat not in realized
    })

    return {
        "success": True,
        "gearSet": equipped_simple,
        "realizedStats": realized,
        "otherStats": other,
        "activeSets": active_sets,
        "filigrees": {
            "weapon": [f['name'] for f in fil_weapon],
            "artifact": [f['name'] for f in fil_artifact],
        },
        "allEffects": all_effects,
        "allEffectsDetail": all_effects_detail,
        "slots": slots_out,
        "priorityTiers": {e.stat: e.tier for e in entries},
        "unmetTier4": unmet_tier4,
        "warnings": validate_physical_rules(equipped, fil_weapon, fil_artifact, unresolved),
        # A recalculation runs no tier stages and no ILP, so there is nothing
        # to report. Present and empty rather than absent: the frontend reads
        # these unconditionally, and calculate mode emitted exactly this too.
        "tierReport": {
            "stages": [], "consolidation": None, "reconciliation": {"status": "optimal"},
            "degraded": False, "notes": [],
        },
        "tierScores": {},
    }


def normalized_priority_names(entries):
    """The priority stats, normalized — for callers that need to ask the
    catalog whether a stat exists at all."""
    return {normalize_stat_key(e.stat) for e in entries}
