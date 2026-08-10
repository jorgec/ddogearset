#!/usr/bin/env python3
"""Canonical snapshot of every parser's output across the full corpus.

Phase 1 gate — docs/0.5.0/01_RECALC_SPEC_AND_PHASED_PLAN.md. Splitting
`parse_items` / `parse_augments` / `parse_filigrees` into a candidacy predicate
plus a per-node extractor is a PURE REFACTOR and carries the whole risk of the
project. It is validated by proving nothing changed: capture on the pre-refactor
commit, capture again after, compare.

    ./scripts/parser_snapshot.py capture     # writes digests + full output
    ./scripts/parser_snapshot.py verify      # re-runs and compares to digests

A diff here is a FAILURE, not a finding. If extraction changes output, the
extraction was not pure.

Two deliberate choices:

* The full corpus is parsed under every combination, never a sample. Phase 1's
  whole job is proving purity, and a sample cannot do that. It costs ~30 s.
* The checked-in artefact is `parser_snapshot.digests.json` (small, reviewable).
  The full canonical output is written to a gitignored directory so a failure can
  actually be diffed instead of just reported.

IMPORTANT (plan §2.4): every capture runs with `keep_unmatched=False`. The
recalculation path needs an extractor that keeps buffs `normalize_stat_name`
returns None for, and that legitimately changes output — so the purity proof is
only meaningful with the flag off. `verify` refuses to run if the extractors
have grown a different default.
"""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "python"))

BASE_DIR = REPO / "DDOBuilderV2" / "Output" / "DataFiles"
DIGESTS = REPO / "python" / "tests" / "fixtures" / "parser_snapshot.digests.json"
FULL_DIR = REPO / "python" / "tests" / "fixtures" / ".snapshot_full"

# Two real priority lists, lifted from the fixture corpus. Priorities are an
# input to extraction (normalize_stat_name runs inside the parse loop), so a
# single list would leave most of the naming guards untested by this snapshot.
CASTER_PRIORITIES = [
    "force spellpower", "force spellcriticaldamage", "force spelllore",
    "illusion spelldc", "Intelligence", "constitution", "prr", "mrr", "dodge",
    "spellcraft skill", "disable device skill", "Sneak attack dice",
]
MELEE_PRIORITIES = [
    "melee power", "doublestrike", "seeker", "critical threat range",
    "critical multiplier", "weapon base damage",
]

TWF = ["dagger", "kukri", "rapier", "scimitar", "longsword", "khopesh",
       "handwraps", "shortsword", "kama", "sickle", "battle axe", "hand axe"]
THF = ["great sword", "falchion", "great axe", "maul", "quarterstaff",
       "great club"]

# Each entry is a candidacy configuration. Names are stable identifiers -- they
# appear in the digest file, so renaming one is a visible diff.
ITEM_COMBINATIONS = [
    ("endgame-default", dict(max_ml=34, min_ml=29)),
    ("ml-unbounded", dict(max_ml=34, min_ml=0)),
    ("armor-light", dict(max_ml=34, min_ml=29, allowed_armor="Light")),
    ("weapon-twf", dict(max_ml=34, min_ml=29, allowed_w1_list=TWF,
                        allowed_w2_list=TWF)),
    ("weapon-thf", dict(max_ml=34, min_ml=29, allowed_w1_list=THF,
                        allowed_w2_list=["none"])),
    ("excluded-packs", dict(max_ml=34, min_ml=29,
                            excluded_packs=["Terror of Demogorgon",
                                            "The Isle of Dread"])),
    ("no-gomf", dict(max_ml=34, min_ml=29, allow_gomf=False)),
    ("dino-artifact", dict(max_ml=34, min_ml=29, art_slot_input="(dino)")),
    ("owned-restricted", dict(max_ml=34, min_ml=29, owned_names="FROM_FIXTURE")),
]

AUGMENT_COMBINATIONS = [
    ("endgame-default", dict(max_ml=34, min_ml=29)),
    ("ml-unbounded", dict(max_ml=34, min_ml=0)),
    ("owned-restricted", dict(max_ml=34, min_ml=29, owned_names="FROM_FIXTURE")),
]


def owned_fixture_names():
    """Real, fixed owned-name sets: (item_names, augment_names).

    Taken from the oracle fixtures rather than invented. `parse_items` and
    `parse_augments` filter against DIFFERENT namespaces, so they need different
    sets — feeding item names to `parse_augments` matches nothing and produces a
    zero-entry snapshot, which proves nothing about the refactor.
    """
    fixtures = REPO / "python" / "tests" / "fixtures" / "oracle"
    items, augments = set(), set()
    for path in sorted(fixtures.glob("*.oracle.json")):
        payload = json.loads(path.read_text()).get("payload") or {}
        items.update((payload.get("pre_equipped") or {}).values())
        for by_color in (payload.get("pre_filled_augments") or {}).values():
            if isinstance(by_color, dict):
                augments.update(v for v in by_color.values() if v)
            elif isinstance(by_color, list):
                augments.update(v for v in by_color if v)
    return items, augments


def canonical(obj):
    """Order-independent, type-stable rendering. Tuples become lists so a
    round trip through JSON cannot itself be the difference."""
    if isinstance(obj, dict):
        return {str(k): canonical(obj[k]) for k in sorted(obj, key=str)}
    if isinstance(obj, (list, tuple)):
        rendered = [canonical(v) for v in obj]
        # Parser output order depends on glob() order, which is filesystem
        # order and not a behavioural property. Sort so a reordering is not
        # mistaken for a change.
        return sorted(rendered, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    return obj


def digest(obj):
    blob = json.dumps(canonical(obj), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest(), blob


def run_all(backend: str = "xml", catalog_path: str = None):
    """backend='xml' walks DDOBuilderV2 via optimizer.parse_*, exactly as
    before. backend='catalog' calls the SAME 9 restriction combinations
    through python/catalog_source.py against a built catalog.db — this is
    Phase 4's correctness gate (docs/0.5.0/00_ETL_START_HERE.md): if every
    digest still matches, the catalog changed no numbers.

    Deliberately NOT parameterised any further than the backend switch — both
    paths must exercise identical restriction combinations for the comparison
    to mean anything.
    """
    if backend == "xml":
        import optimizer
        import parser as ddo_parser
        if not BASE_DIR.exists():
            sys.exit(f"DDOBuilderV2 data not found at {BASE_DIR}")
        quests = ddo_parser.parse_quests(str(BASE_DIR))

        def do_items(priorities, o):
            return optimizer.parse_items(
                str(BASE_DIR), o.get("max_ml", 34), priorities,
                o.get("allowed_armor", ""), o.get("allowed_w1_list"),
                o.get("allowed_w2_list"), o.get("allow_gomf", True),
                o.get("art_slot_input", ""), o.get("excluded_packs"), quests,
                o.get("pre_equipped_names"), min_ml=o.get("min_ml", 29),
                owned_names=o.get("owned_names"))

        def do_augments(priorities, o):
            return optimizer.parse_augments(
                str(BASE_DIR), o.get("max_ml", 34), priorities,
                o.get("pre_filled_augment_names"), min_ml=o.get("min_ml", 29),
                owned_names=o.get("owned_names"))

        def do_filigrees(priorities):
            return optimizer.parse_filigrees(str(BASE_DIR), priorities)

        def do_sets(priorities):
            return optimizer.parse_sets(str(BASE_DIR), priorities)

    elif backend == "catalog":
        import catalog_source
        if not catalog_path or not Path(catalog_path).exists():
            sys.exit(f"catalog not found at {catalog_path!r}")
        conn = catalog_source.connect(catalog_path)

        def do_items(priorities, o):
            return catalog_source.parse_items(
                conn, o.get("max_ml", 34), priorities,
                o.get("allowed_armor", ""), o.get("allowed_w1_list"),
                o.get("allowed_w2_list"), o.get("allow_gomf", True),
                o.get("art_slot_input", ""), o.get("excluded_packs"),
                o.get("pre_equipped_names"), min_ml=o.get("min_ml", 29),
                owned_names=o.get("owned_names"))

        def do_augments(priorities, o):
            return catalog_source.parse_augments(
                conn, o.get("max_ml", 34), priorities,
                o.get("pre_filled_augment_names"), min_ml=o.get("min_ml", 29),
                owned_names=o.get("owned_names"))

        def do_filigrees(priorities):
            return catalog_source.parse_filigrees(conn, priorities)

        def do_sets(priorities):
            return catalog_source.parse_sets(conn, priorities)
    else:
        sys.exit(f"unknown backend {backend!r}")

    owned_items, owned_augments = owned_fixture_names()
    out = {}

    for plabel, priorities in (("caster", CASTER_PRIORITIES),
                               ("melee", MELEE_PRIORITIES)):
        for label, opts in ITEM_COMBINATIONS:
            o = dict(opts)
            if o.get("owned_names") == "FROM_FIXTURE":
                o["owned_names"] = owned_items
            out[f"items/{plabel}/{label}"] = do_items(priorities, o)

        for label, opts in AUGMENT_COMBINATIONS:
            o = dict(opts)
            if o.get("owned_names") == "FROM_FIXTURE":
                o["owned_names"] = owned_augments
            out[f"augments/{plabel}/{label}"] = do_augments(priorities, o)

        fils, fil_sets = do_filigrees(priorities)
        out[f"filigrees/{plabel}/all"] = fils
        out[f"filigree_sets/{plabel}/all"] = fil_sets
        out[f"sets/{plabel}/all"] = do_sets(priorities)

    if backend == "catalog":
        conn.close()

    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if mode not in ("capture", "verify", "verify-catalog"):
        sys.exit(f"usage: {sys.argv[0]} [capture|verify|verify-catalog <catalog.db>]")

    if mode == "verify-catalog":
        if len(sys.argv) < 3:
            sys.exit(f"usage: {sys.argv[0]} verify-catalog <path-to-catalog.db>")
        catalog_path = sys.argv[2]
        print(f"parser snapshot — verify-catalog against {catalog_path} "
              f"(Phase 4 correctness gate)\n")
        results = run_all(backend="catalog", catalog_path=catalog_path)
    else:
        print(f"parser snapshot — {mode} (full corpus, this takes ~30 s)\n")
        results = run_all(backend="xml")

    digests, sizes = {}, {}
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    for key in sorted(results):
        d, blob = digest(results[key])
        digests[key] = d
        sizes[key] = len(results[key])
        (FULL_DIR / (key.replace("/", "__") + ".json")).write_text(blob)

    record = {
        "_comment": "Phase 1 purity proof. keep_unmatched=False throughout "
                    "(plan §2.4). A diff is a failure, not a finding.",
        "corpus_counts": sizes,
        "digests": digests,
    }

    if mode == "capture":
        DIGESTS.parent.mkdir(parents=True, exist_ok=True)
        DIGESTS.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        for key in sorted(digests):
            print(f"  {key:44s} {sizes[key]:6d} entries  {digests[key][:16]}")
        print(f"\ncaptured {len(digests)} snapshots -> {DIGESTS}")
        print(f"full output (gitignored, for diffing) -> {FULL_DIR}")
        return 0

    if not DIGESTS.exists():
        sys.exit(f"no baseline at {DIGESTS} — run `capture` first")
    baseline = json.loads(DIGESTS.read_text())

    drift = []
    for key in sorted(set(digests) | set(baseline["digests"])):
        was, now = baseline["digests"].get(key), digests.get(key)
        if was is None:
            drift.append(f"{key}: NEW snapshot not in baseline")
        elif now is None:
            drift.append(f"{key}: MISSING from this run")
        elif was != now:
            drift.append(f"{key}: CHANGED "
                         f"({baseline['corpus_counts'].get(key)} -> {sizes[key]} entries)")
        else:
            print(f"  identical  {key}")

    print()
    if drift:
        print(f"SNAPSHOT DRIFT — {len(drift)} snapshot(s) differ:")
        for d in drift:
            print(f"  {d}")
        print(f"\nDiff the full output under {FULL_DIR} against the pre-refactor "
              f"copy to see what moved.")
        return 1
    print(f"IDENTICAL — all {len(digests)} snapshots match the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
