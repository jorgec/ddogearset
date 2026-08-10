"""The stat dimension — buff classification, computed once per distinct
`(raw_type, raw_target)` pair rather than once per buff instance.

See docs/0.5.0/00_ETL_START_HERE.md §2.1 and
docs/0.5.0/01_CATALOG_AND_APP_SCHEMA.md §5.1's `stat` table. This module is
Transform's answer to "what IS this stat", mirroring the buff-side (not
priority-side) half of `rules.naming.normalize_stat_name`: the three
classification flags there are pure functions of `(typ, item)` with no
priority involved, so they belong here rather than at query time.

KNOWN SIMPLIFICATION, checked against the real corpus before being accepted:
`normalize_stat_name`'s `combined` match text also folds in `Description1`,
which is per-buff-instance. Measured on the full item corpus (32,381 buffs):
75 of 1,809 distinct (type, item) pairs have more than one observed
Description1 value, and in every sampled case the variance is between an empty
string and a value that duplicates the type/item text itself — never new match
surface. `match_text` here is built from `(raw_type, raw_target)` alone. If
Phase 4's differential ever disagrees with the live solver over a matched stat,
this is the first place to look.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "python"))

from rules.constants import WEAPON_BASE_STATS  # noqa: E402


@dataclass(frozen=True)
class StatKey:
    """The natural key of a stat entity: one buff SHAPE, not one buff instance.
    raw_target is None for stats with no <Item> (e.g. a bare skill bonus with
    no target — rare, but the corpus has them)."""
    raw_type: str
    raw_target: Optional[str]

    def natural_key(self) -> str:
        # \x1f (unit separator) as the join char, per schema doc §3.1 — never
        # appears in game text, so it cannot collide with a real name.
        return f"{self.raw_type}\x1f{self.raw_target or ''}"


@dataclass
class StatRow:
    key: StatKey
    match_text: str
    is_skill: bool
    is_hireling: bool
    is_save: bool
    is_weapon_base: bool


def classify(raw_type: str, raw_target: Optional[str]) -> StatRow:
    """Mirrors rules.naming.normalize_stat_name's buff-side classification
    exactly — same substring tests, same lowercasing — so a stat's flags here
    can never disagree with what the live matcher would compute for it."""
    typ = (raw_type or '').lower()
    item = (raw_target or '').lower()

    is_skill = 'skill' in typ or 'skill' in item
    is_hireling = 'hireling' in typ or 'hireling' in item
    is_save = 'save' in typ or 'save' in item
    is_weapon_base = typ in WEAPON_BASE_STATS or item in WEAPON_BASE_STATS

    return StatRow(
        key=StatKey(raw_type=raw_type, raw_target=raw_target),
        match_text=f"{item} {typ}".strip(),
        is_skill=is_skill,
        is_hireling=is_hireling,
        is_save=is_save,
        is_weapon_base=is_weapon_base,
    )


class StatDimension:
    """Accumulates distinct (raw_type, raw_target) pairs seen across the whole
    corpus and classifies each exactly once. Built incrementally as Extract
    walks items/augments/filigrees/sets, not as a separate pass — the pairs
    only exist inside buff nodes already being visited for other reasons.
    """

    def __init__(self) -> None:
        self._rows: Dict[StatKey, StatRow] = {}

    def observe(self, raw_type: str, raw_target: Optional[str]) -> StatKey:
        key = StatKey(raw_type=raw_type, raw_target=raw_target)
        if key not in self._rows:
            self._rows[key] = classify(raw_type, raw_target)
        return key

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterable[Tuple[StatKey, StatRow]]:
        return iter(self._rows.items())

    def rows(self) -> Dict[StatKey, StatRow]:
        return dict(self._rows)
