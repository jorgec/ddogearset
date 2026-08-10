"""Identity resolution against the checked-in registry.

See docs/0.5.0/00_ETL_START_HERE.md §6. The rule this module exists to enforce:
**once minted, a UUID never changes.** Deterministic v5 hashing alone cannot
promise that (a rename changes the natural key, and therefore the hash), so
identity is pinned in `etl/identity_registry.json` and hashing is only how a
*new* entity gets a UUID the first time it is ever seen.

This module never writes app-facing data. It answers one question per natural
key — "what UUID does this get, and why" — and returns a report the caller uses
to update the registry file and render the drift report.
"""

from __future__ import annotations

import difflib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Fixed namespace UUID for this application. Never changes — it seeds every
# per-kind namespace below via uuid5, so those are themselves deterministic
# and need not be hardcoded separately.
_APP_NAMESPACE = uuid.UUID("6f9c7f2e-6b8b-4e9b-8c1a-2f7b5e9d3a11")

NAMESPACES = {
    kind: uuid.uuid5(_APP_NAMESPACE, f"ddogearset:{kind}")
    for kind in ("item", "item_family", "augment", "filigree", "filigree_base",
                "gear_set", "set_tier", "stat", "quest")
}

# "Clean derivation" — the ONLY automatic rename resolutions. Anything else is
# a guess, and a wrong guess silently rewrites what a saved gearset means.
# Mirrors rules.provenance.RAID_UPGRADE_TIER_PREFIXES; not imported directly so
# this module has zero dependency on python/rules — identity resolution is
# infrastructure, not a domain rule.
_TIER_PREFIXES = ("Epic ", "Legendary ", "Mythic ", "Perfected ", "Elite ")
_VERSION_OF_RE = re.compile(r'(?:upgraded )?version of\s+(.+)', re.IGNORECASE)


def _normalize_whitespace(name: str) -> str:
    return re.sub(r'\s+', ' ', name).strip()


def _strip_tier_prefix(name: str) -> Optional[str]:
    for prefix in _TIER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return None


def _is_clean_derivation(old_key: str, new_key: str) -> Optional[str]:
    """Returns a short reason string if `new_key` is a clean derivation of
    `old_key`, else None. Order matters only for the reason text."""
    if _normalize_whitespace(old_key).lower() == _normalize_whitespace(new_key).lower():
        return "whitespace/case normalization"

    old_stripped = _strip_tier_prefix(old_key)
    new_stripped = _strip_tier_prefix(new_key)
    base_old = old_stripped if old_stripped is not None else old_key
    base_new = new_stripped if new_stripped is not None else new_key
    if (old_stripped is not None or new_stripped is not None) and \
            _normalize_whitespace(base_old).lower() == _normalize_whitespace(base_new).lower():
        return "upgrade-tier prefix changed"

    m = _VERSION_OF_RE.search(new_key)
    if m and _normalize_whitespace(m.group(1)).lower() == _normalize_whitespace(old_key).lower():
        return "explicit 'version of' relationship"

    return None


@dataclass
class ResolvedEntity:
    key: str
    kind: str
    entity_uuid: str
    is_new: bool = False
    auto_resolved_from: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class DriftEntry:
    kind: str
    disappeared: str
    candidates: List[str] = field(default_factory=list)


@dataclass
class AutoResolution:
    """One rename the ETL resolved on its own, per the narrow "clean
    derivation" rules — kept so the drift report can show what was auto-fixed,
    not just what needed a human. See §6.1's `AUTO` classification."""
    kind: str
    old_key: str
    new_key: str
    reason: str


@dataclass
class Registry:
    """In-memory view of identity_registry.json, plus the running diff a
    Transform run produces against it. `entities` is keyed by UUID (string);
    `_by_name` is a derived reverse index built once at load time."""

    version: int
    entities: Dict[str, dict]
    path: Path

    _by_name: Dict[str, str] = field(default_factory=dict, repr=False)
    _seen_this_run: Dict[str, set] = field(default_factory=dict, repr=False)
    new_count: int = 0
    auto_resolved_count: int = 0
    auto_resolutions: List[AutoResolution] = field(default_factory=list)
    unresolved: List[DriftEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Registry":
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {"version": 1, "entities": {}}
        reg = cls(version=data.get("version", 1), entities=data.get("entities", {}), path=path)
        for eid, info in reg.entities.items():
            reg._by_name[(info["kind"], info["canonical"])] = eid
            for aka in info.get("aka", []):
                reg._by_name[(info["kind"], aka)] = eid
        return reg

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.version, "entities": self.entities}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def resolve(self, kind: str, key: str, *, built_at: str, commit: str,
               strict: bool) -> ResolvedEntity:
        """Resolve one natural key to a UUID. Mints on first sight; reuses
        forever after. Does NOT detect renames by itself — see
        `reconcile_disappeared`, which runs once all keys for a kind are known.
        """
        self._seen_this_run.setdefault(kind, set()).add(key)

        existing = self._by_name.get((kind, key))
        if existing is not None:
            self.entities[existing]["last_seen_commit"] = commit
            return ResolvedEntity(key=key, kind=kind, entity_uuid=existing)

        new_uuid = str(uuid.uuid5(NAMESPACES[kind], key))
        self.entities[new_uuid] = {
            "kind": kind,
            "canonical": key,
            "aka": [],
            "first_seen": built_at,
            "last_seen_commit": commit,
        }
        self._by_name[(kind, key)] = new_uuid
        self.new_count += 1
        return ResolvedEntity(key=key, kind=kind, entity_uuid=new_uuid, is_new=True)

    def reconcile_disappeared(self, kind: str, all_current_keys: set,
                              aliases: Dict[str, Optional[str]]) -> None:
        """After every current-corpus key of `kind` has been through
        `resolve`, find registry entries that were NOT seen this run and try to
        explain them: an operator-confirmed alias, or a clean derivation onto a
        key that WAS newly minted this run (i.e. looks like its replacement).
        Anything left over is unresolved drift for a human.
        """
        seen = self._seen_this_run.get(kind, set())
        newly_minted = {
            info["canonical"] for eid, info in self.entities.items()
            if info["kind"] == kind and info["canonical"] in seen
            and info["first_seen"] == self.entities[eid]["first_seen"]
            and len(info.get("aka", [])) == 0
        }

        for eid, info in list(self.entities.items()):
            if info["kind"] != kind:
                continue
            all_names = {info["canonical"], *info.get("aka", [])}
            if all_names & all_current_keys:
                continue  # still present under some known name

            # Report the MOST RECENTLY seen name, not necessarily the original
            # canonical — that is the key that actually vanished from this
            # run's corpus, and the one an operator resolving drift needs to
            # recognise. An item through two renames should not keep surfacing
            # its very first name.
            old_key = info.get("aka", [info["canonical"]])[-1] if info.get("aka") else info["canonical"]

            if old_key in aliases:
                new_key = aliases[old_key]
                if new_key is None:
                    # Operator confirmed: genuinely removed. Not drift.
                    continue
                if new_key in all_current_keys:
                    self._merge_alias(eid, new_key, kind)
                    continue

            candidates = [k for k in all_current_keys if k not in seen or k in newly_minted]
            auto_target = None
            reason = None
            for cand in sorted(candidates):
                r = _is_clean_derivation(old_key, cand)
                if r:
                    auto_target, reason = cand, r
                    break

            if auto_target:
                self._merge_alias(eid, auto_target, kind)
                self.auto_resolved_count += 1
                self.auto_resolutions.append(AutoResolution(
                    kind=kind, old_key=old_key, new_key=auto_target, reason=reason))
                continue

            ranked = difflib.get_close_matches(old_key, all_current_keys, n=5, cutoff=0.4)
            self.unresolved.append(DriftEntry(kind=kind, disappeared=old_key, candidates=ranked))

    def _merge_alias(self, eid: str, new_key: str, kind: str) -> None:
        """Fold a renamed key into an EXISTING uuid rather than the fresh one
        `resolve` minted for it moments ago — the fresh mint is discarded."""
        fresh_uuid = self._by_name.pop((kind, new_key), None)
        if fresh_uuid and fresh_uuid in self.entities and fresh_uuid != eid:
            del self.entities[fresh_uuid]
            self.new_count -= 1
        info = self.entities[eid]
        if new_key not in info.get("aka", []) and new_key != info["canonical"]:
            info.setdefault("aka", []).append(new_key)
        self._by_name[(kind, new_key)] = eid
