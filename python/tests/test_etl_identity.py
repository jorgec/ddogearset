"""The ETL's identity and drift workflow — docs/0.5.0/00_ETL_START_HERE.md §6.

These are the Phase 7 gate's first three clauses, made deterministic: a
synthetic rename produces a drift report, `--strict` refuses to build on it, and
resolving it through `aliases.yaml` unblocks the build **while preserving the
UUID**. The last clause is the one that matters — a rename workflow that keeps
building but silently reissues identities is worse than one that fails, because
0.5.1's saved gearsets reference those UUIDs.

Driven at the Registry level rather than through the real corpus: the full ETL
takes minutes and would make these untestable in practice, and every guarantee
under test lives in `identity.py` regardless of what walked the XML.
"""

import sys
from pathlib import Path

import pytest

# The ETL lives at the repo root, not under python/ — pytest's rootdir insertion
# stops at python/ because python/tests/ has an __init__.py. Same explicit
# insert etl/walk.py already uses to reach python/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from etl.aliases import AliasError, load_aliases, parse_aliases_text  # noqa: E402
from etl.drift import render_report  # noqa: E402
from etl.identity import NAMESPACES, Registry  # noqa: E402
from etl.load import DDL, TABLES, _content_hash  # noqa: E402
from etl.transform import TransformResult  # noqa: E402

BUILT_AT = "2026-08-11T00:00:00Z"


def _run(registry, kind, keys, aliases=None):
    """One ETL pass over `keys`, in the order transform() uses: reconcile the
    whole key set first, then resolve each key."""
    registry.reconcile_disappeared(kind, set(keys), aliases or {})
    return {
        key: registry.resolve(kind, key, built_at=BUILT_AT, commit="c",
                              strict=False).entity_uuid
        for key in keys
    }


def _fresh(tmp_path, name="identity_registry.json"):
    return Registry.load(tmp_path / name)


# ── the gate: rename -> drift -> alias -> same UUID ────────────────────────

def test_unexplained_rename_is_reported_as_unresolved_drift(tmp_path):
    reg = _fresh(tmp_path)
    _run(reg, "item", ["Bracers of Wind"])
    reg.save()

    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["Gauntlets of Thunder"])

    assert reg2.auto_resolved_count == 0
    assert [(d.kind, d.disappeared) for d in reg2.unresolved] == [
        ("item", "Bracers of Wind")]


def test_alias_resolves_the_rename_and_preserves_the_uuid(tmp_path):
    reg = _fresh(tmp_path)
    original = _run(reg, "item", ["Bracers of Wind"])["Bracers of Wind"]
    reg.save()

    reg2 = Registry.load(reg.path)
    resolved = _run(reg2, "item", ["Gauntlets of Thunder"],
                    aliases={"Bracers of Wind": "Gauntlets of Thunder"})

    assert reg2.unresolved == []
    assert reg2.alias_conflicts == []
    # THE promise: the new name answers with the old UUID.
    assert resolved["Gauntlets of Thunder"] == original
    assert reg2.new_count == 0
    entry = reg2.entities[original]
    assert entry["canonical"] == "Bracers of Wind"
    assert entry["aka"] == ["Gauntlets of Thunder"]


def test_alias_survives_a_further_rename_from_the_new_name(tmp_path):
    """Two renames in a row must not resurrect the original name in the drift
    report — the operator is asked about the name that actually vanished."""
    reg = _fresh(tmp_path)
    original = _run(reg, "item", ["A"])["A"]
    reg.save()

    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["B"], aliases={"A": "B"})
    reg2.save()

    reg3 = Registry.load(reg2.path)
    _run(reg3, "item", ["C"])
    assert [d.disappeared for d in reg3.unresolved] == ["B"]

    reg4 = Registry.load(reg2.path)
    assert _run(reg4, "item", ["C"], aliases={"B": "C"})["C"] == original


def test_confirmed_removal_is_not_drift(tmp_path):
    reg = _fresh(tmp_path)
    _run(reg, "item", ["Gem of Many Facets"])
    reg.save()

    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["Something Else"], aliases={"Gem of Many Facets": None})
    assert reg2.unresolved == []
    assert reg2.alias_conflicts == []


# ── clean derivations, and the line where guessing stops ──────────────────

@pytest.mark.parametrize("old,new", [
    ("Bracers of Wind", "Legendary Bracers of Wind"),   # tier prefix added
    ("Epic Bracers of Wind", "Legendary Bracers of Wind"),  # tier prefix swapped
    ("Bracers  of Wind", "Bracers of Wind"),            # whitespace only
])
def test_clean_derivations_auto_resolve_and_keep_the_uuid(tmp_path, old, new):
    reg = _fresh(tmp_path)
    original = _run(reg, "item", [old])[old]
    reg.save()

    reg2 = Registry.load(reg.path)
    resolved = _run(reg2, "item", [new])

    assert reg2.unresolved == []
    assert reg2.auto_resolved_count == 1
    assert resolved[new] == original


def test_a_different_item_is_never_a_clean_derivation(tmp_path):
    """The narrowness IS the feature (§6.1): a plausible-looking but unrelated
    name must reach a human, not get absorbed."""
    reg = _fresh(tmp_path)
    _run(reg, "item", ["Bracers of Wind"])
    reg.save()

    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["Bracers of Winds"])  # one letter apart, still a guess
    assert reg2.auto_resolved_count == 0
    assert [d.disappeared for d in reg2.unresolved] == ["Bracers of Wind"]


def test_an_established_name_is_never_stolen_by_an_auto_resolution(tmp_path):
    """`Epic X` disappearing must not fold into a `Legendary X` that already
    has its own identity — that would hand one entity's UUID to another's data."""
    reg = _fresh(tmp_path)
    first = _run(reg, "item", ["Epic Bracers", "Legendary Bracers"])
    reg.save()

    reg2 = Registry.load(reg.path)
    resolved = _run(reg2, "item", ["Legendary Bracers"])

    assert reg2.auto_resolved_count == 0
    assert [d.disappeared for d in reg2.unresolved] == ["Epic Bracers"]
    assert resolved["Legendary Bracers"] == first["Legendary Bracers"]


def test_alias_onto_an_occupied_name_is_a_conflict_not_a_merge(tmp_path):
    reg = _fresh(tmp_path)
    first = _run(reg, "item", ["Old Thing", "Other Thing"])
    reg.save()

    reg2 = Registry.load(reg.path)
    resolved = _run(reg2, "item", ["Other Thing"],
                    aliases={"Old Thing": "Other Thing"})

    assert len(reg2.alias_conflicts) == 1
    assert "already an established" in reg2.alias_conflicts[0]
    assert resolved["Other Thing"] == first["Other Thing"]


def test_alias_onto_a_name_that_is_not_in_the_corpus_is_a_conflict(tmp_path):
    reg = _fresh(tmp_path)
    _run(reg, "item", ["Old Thing"])
    reg.save()

    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["New Thing"], aliases={"Old Thing": "Nwe Thing"})
    assert len(reg2.alias_conflicts) == 1
    assert "not in the current corpus" in reg2.alias_conflicts[0]


def test_reconciling_after_resolving_is_refused(tmp_path):
    """The ordering that makes a resolved rename keep its UUID is an invariant,
    not a convention — Transform emits rows the moment resolve() answers."""
    reg = _fresh(tmp_path)
    reg.resolve("item", "Anything", built_at=BUILT_AT, commit="c", strict=False)
    with pytest.raises(RuntimeError, match="already resolved"):
        reg.reconcile_disappeared("item", {"Anything"}, {})


def test_kinds_do_not_interfere(tmp_path):
    """Every entity kind has its own namespace and its own drift; an item named
    X vanishing says nothing about an augment named X."""
    reg = _fresh(tmp_path)
    _run(reg, "item", ["Shared Name"])
    _run(reg, "augment", ["Shared Name"])
    reg.save()

    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["Shared Name"])
    _run(reg2, "augment", ["Renamed"])
    assert [(d.kind, d.disappeared) for d in reg2.unresolved] == [
        ("augment", "Shared Name")]


def test_uuids_are_stable_across_rebuilds(tmp_path):
    reg = _fresh(tmp_path)
    first = _run(reg, "item", ["A", "B", "C"])
    reg.save()

    reg2 = Registry.load(reg.path)
    assert _run(reg2, "item", ["A", "B", "C"]) == first
    assert reg2.new_count == 0


# ── aliases.yaml parsing ───────────────────────────────────────────────────

def test_parses_the_documented_shape():
    entries = parse_aliases_text('''
# Reviewed 2026-08-12.
- was: "Bracers of the Sun Soul"
  now: "Legendary Bracers of the Sun Soul"

- was: "Gem of Many Facets"
  now: null        # genuinely removed from the game
''')
    assert [(e.was, e.now, e.kind) for e in entries] == [
        ("Bracers of the Sun Soul", "Legendary Bracers of the Sun Soul", None),
        ("Gem of Many Facets", None, None),
    ]


def test_hash_inside_a_quoted_value_is_not_a_comment():
    entries = parse_aliases_text('- was: "Ring #1"\n  now: "Ring #2"  # renamed\n')
    assert (entries[0].was, entries[0].now) == ("Ring #1", "Ring #2")


def test_apostrophes_and_colons_survive():
    entries = parse_aliases_text(
        '- was: "Van Richten\'s Cane: Tier 2"\n  now: "Van Richten\'s Cane"\n')
    assert entries[0].was == "Van Richten's Cane: Tier 2"


def test_escaped_quotes_and_backslashes():
    entries = parse_aliases_text('- was: "A \\"quoted\\" name"\n  now: "C:\\\\path"\n')
    assert entries[0].was == 'A "quoted" name'
    assert entries[0].now == "C:\\path"


@pytest.mark.parametrize("text,fragment", [
    ('- was: Bracers of Wind\n  now: null\n', "must be quoted"),
    ('- was: "A"\n', "missing 'now'"),
    ('- now: "B"\n', "missing 'was'"),
    ('- was: "A"\n  now: "B"\n  colour: "red"\n', "unknown key"),
    ('- was: "A"\n  was: "B"\n  now: "C"\n', "duplicate key"),
    ('- was: "A\n  now: "B"\n', "unterminated"),
    ('- was: "A" trailing\n  now: "B"\n', "after the closing quote"),
    ('was: "A"\n', "expected a '- ' entry"),
    ('  was: "A"\n', "before any '- ' entry"),
    ('- was: "A"\n  now:\n', "missing value"),
])
def test_malformed_entries_are_rejected_with_a_line_number(text, fragment):
    with pytest.raises(AliasError) as exc:
        parse_aliases_text(text)
    assert fragment in str(exc.value)
    assert "line " in str(exc.value)


def test_load_aliases_fans_unqualified_entries_across_every_kind(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text('- was: "A"\n  now: "B"\n')
    loaded = load_aliases(path, NAMESPACES.keys())
    assert set(loaded) == set(NAMESPACES)
    assert all(kind_map["A"] == "B" for kind_map in loaded.values())


def test_an_explicit_kind_overrides_the_unqualified_entry_only_there(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text('- was: "A"\n  now: "B"\n- kind: augment\n  was: "A"\n  now: "C"\n')
    loaded = load_aliases(path, NAMESPACES.keys())
    assert loaded["augment"]["A"] == "C"
    assert loaded["item"]["A"] == "B"


def test_duplicate_answers_for_the_same_key_are_rejected(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text('- was: "A"\n  now: "B"\n- was: "A"\n  now: "C"\n')
    with pytest.raises(AliasError, match="already has an answer"):
        load_aliases(path, NAMESPACES.keys())


def test_unknown_kind_is_rejected(tmp_path):
    path = tmp_path / "aliases.yaml"
    path.write_text('- kind: wombat\n  was: "A"\n  now: "B"\n')
    with pytest.raises(AliasError, match="unknown kind"):
        load_aliases(path, NAMESPACES.keys())


def test_a_missing_aliases_file_is_not_an_error(tmp_path):
    loaded = load_aliases(tmp_path / "nope.yaml", NAMESPACES.keys())
    assert loaded == {kind: {} for kind in NAMESPACES}


def test_the_shipped_aliases_file_parses():
    """It is all comments today, but a syntax error in it would fail every
    build — including a release — and it is edited by hand under time pressure."""
    shipped = Path(__file__).resolve().parents[2] / "etl" / "aliases.yaml"
    assert load_aliases(shipped, NAMESPACES.keys()) == {k: {} for k in NAMESPACES}


# ── the drift report ───────────────────────────────────────────────────────

def _report_for(tmp_path, *, strict=False):
    reg = _fresh(tmp_path)
    _run(reg, "item", ["Bracers of Wind", "Epic Helm"])
    reg.save()
    reg2 = Registry.load(reg.path)
    _run(reg2, "item", ["Gauntlets of Thunder", "Legendary Helm"])
    return reg2, render_report(reg2, commit="abc123", built_at=BUILT_AT,
                               source_dir="/tmp/src", strict=strict)


def test_report_names_the_unresolved_key_and_offers_a_paste_block(tmp_path):
    _, report = _report_for(tmp_path)
    assert "Bracers of Wind" in report
    assert "- kind: item" in report
    assert 'was: "Bracers of Wind"' in report
    # The answer is never pre-filled — a guess that arrives pre-typed is one
    # nobody re-checks (§6.1).
    assert 'now: # "New Name" or null' in report


def test_the_paste_block_round_trips_through_the_alias_parser(tmp_path):
    """The report's whole purpose is that its output can be pasted into
    aliases.yaml — so the two formats have to actually agree."""
    _, report = _report_for(tmp_path)
    block = report.split("```yaml", 1)[1].split("```", 1)[0]
    filled = block.replace('now: # "New Name" or null', 'now: "Gauntlets of Thunder"')
    entries = parse_aliases_text(filled)
    assert [(e.kind, e.was, e.now) for e in entries] == [
        ("item", "Bracers of Wind", "Gauntlets of Thunder")]


def test_report_lists_auto_resolutions_separately(tmp_path):
    _, report = _report_for(tmp_path)
    assert "## Auto-resolved" in report
    assert "Epic Helm" in report and "Legendary Helm" in report
    assert "upgrade-tier prefix changed" in report


def test_report_says_so_when_there_is_nothing_to_decide(tmp_path):
    reg = _fresh(tmp_path)
    _run(reg, "item", ["A"])
    report = render_report(reg, commit="abc", built_at=BUILT_AT,
                           source_dir="/tmp/src", strict=True)
    assert "Nothing to decide" in report


def test_report_escapes_pipes_and_the_augment_key_separator(tmp_path):
    reg = _fresh(tmp_path)
    _run(reg, "augment", ["Twilight\x1fBlue", "Pipe|Name"])
    reg.save()
    reg2 = Registry.load(reg.path)
    _run(reg2, "augment", ["Something Unrelated"])
    report = render_report(reg2, commit="abc", built_at=BUILT_AT,
                           source_dir="/tmp/src", strict=False)
    assert "Twilight ␟ Blue" in report       # \x1f would render as nothing
    assert "Pipe\\|Name" in report            # a bare | breaks the table
    # ...but the paste block is YAML, where neither needs escaping and both
    # must come back byte-identical.
    assert '"Twilight\x1fBlue"' in report


def test_report_lists_source_data_ambiguities(tmp_path):
    reg = _fresh(tmp_path)
    _run(reg, "item", ["A"])
    report = render_report(reg, commit="abc", built_at=BUILT_AT,
                           source_dir="/tmp/src", strict=True,
                           data_ambiguities=["two Twilights, no tiebreaker"])
    assert "## Source-data ambiguities" in report
    assert "two Twilights, no tiebreaker" in report
    assert "Nothing to decide" not in report


# ── Load's table list ──────────────────────────────────────────────────────

def test_tables_list_covers_every_table_the_ddl_creates():
    """`TABLES` drives both the INSERTs and the content hash. A table added to
    the DDL but not to it would be created empty in every catalog, and nothing
    else would notice."""
    import re
    created = set(re.findall(r"CREATE TABLE (\w+)", DDL))
    covered = {table for table, _attr, _cols in TABLES}
    # catalog_meta is written separately (it carries the content hash);
    # item_upgrade is created-but-unpopulated on purpose — see load.TABLES.
    assert created - covered == {"catalog_meta", "item_upgrade"}
    assert covered - created == set()


def test_tables_list_matches_the_result_attributes():
    result = TransformResult()
    for _table, attr, _cols in TABLES:
        assert isinstance(getattr(result, attr), list), attr


def test_content_hash_ignores_diagnostics():
    """catalog_version bumps when the hash moves, so the hash must track the
    DATA — not warning text that never reaches the database."""
    clean = TransformResult()
    noisy = TransformResult()
    noisy.data_ambiguities.append("a wording change nobody should notice")
    noisy.validation_errors.append("...nor this")
    assert _content_hash(clean) == _content_hash(noisy)


def test_content_hash_tracks_row_content_but_not_row_order():
    a, b = TransformResult(), TransformResult()
    a.items.extend([{"uuid": "1", "name": "X"}, {"uuid": "2", "name": "Y"}])
    b.items.extend([{"uuid": "2", "name": "Y"}, {"uuid": "1", "name": "X"}])
    assert _content_hash(a) == _content_hash(b)
    b.items.append({"uuid": "3", "name": "Z"})
    assert _content_hash(a) != _content_hash(b)
