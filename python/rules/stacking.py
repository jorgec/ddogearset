"""Bonus-type stacking and gearset aggregation — the DDO arithmetic.

Part of `python/rules/`: no pulp, no search restrictions. This is the module the
whole ETL/recalculation direction exists to reach without building an ILP —
`_collect_contributions` + `_resolve_totals` already evaluate a fixed gearset by
direct arithmetic, and always did (they were written for the alternatives path).

`_resolve_totals` is the single owner of the sum-vs-max rule. Stays in Python
per explicit instruction — sum-vs-max is business logic, not a storage problem,
and SQL expressibility is not a reason to move it (docs/0.5.0/00_ETL_START_HERE.md §2).
"""

import collections

from .constants import WEAPON_BASE_BONUS_TYPE, WEAPON_BASE_SLOT


# Bonus types whose sources genuinely add together. Everything else routes down
# the d_var (max-of-sources) path.
STACKING_TYPES = ('stacking', 'mythic', 'reaper')


def _is_stacking(b_type):
    return (b_type or '').lower().strip() in STACKING_TYPES


def _collect_contributions(equipped, aug_list, fil_weapon, fil_artifact, sets):
    """Direct arithmetic against a fixed gearset — the same computation
    calculate_only mode performs.

    Returns `{(stat, b_type): [(val, origin, source_name)]}`.

    The source NAME is carried alongside the value because recalculation has to
    report provenance ("23.0 Enhancement (Melancholic Force Spell Critical
    Damage)"), and the ILP path only had it because it kept a parallel
    `sources_tracking` structure beside the model. Recording it here instead
    means one collector answers both "what does this gearset total" and "where
    did each part of that come from" — a second walk over the same gear to
    recover names is exactly how two answers drift apart.

    Callers that only want values ignore the third element.
    """
    contrib = collections.defaultdict(list)

    for slot, item in equipped:
        for stat, b_type, val in item['buffs']:
            if b_type == WEAPON_BASE_BONUS_TYPE and slot != WEAPON_BASE_SLOT:
                continue
            contrib[(stat, b_type)].append((val, 'item', item['name']))

    for aug in aug_list:
        for stat, b_type, val in aug['buffs']:
            contrib[(stat, b_type)].append((val, 'augment', aug['name']))

    for f in list(fil_weapon) + list(fil_artifact):
        for stat, b_type, val in f['buffs']:
            contrib[(stat, b_type)].append((val, 'filigree', f['name']))

    # Set bonuses recomputed with the candidate substituted.
    piece_counts = collections.Counter()
    for _slot, item in equipped:
        for k in item.get('sets', []) or []:
            piece_counts[k] += 1
    for f in list(fil_weapon) + list(fil_artifact):
        if f.get('set'):
            piece_counts[f['set']] += 1

    for k, tiers in sets.items():
        pieces = piece_counts.get(k, 0)
        for m, buffs in tiers.items():
            if pieces >= m:
                for stat, b_type, val in buffs:
                    contrib[(stat, b_type)].append((val, 'set', f'{k} ({m} Piece)'))

    return contrib


def _resolve_totals(contrib, exclude_filigrees=False):
    """Sum for stacking bonus types, max for non-stacking — the DDO rule."""
    totals = collections.defaultdict(float)
    for (stat, b_type), entries in contrib.items():
        vals = [v for v, o, _name in entries if not (exclude_filigrees and o == 'filigree')]
        if not vals:
            continue
        totals[stat] += sum(vals) if _is_stacking(b_type) else max(vals)
    return dict(totals)
