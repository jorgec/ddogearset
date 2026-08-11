"""What `rules.evaluate` guarantees — the behavioural half of the retired
calculate-mode tests.

0.5.1 Phase 5. Three properties used to be asserted by building an ILP,
declaring every piece pinned, and checking the model did not go infeasible. Two
of them were about the SEARCH constraints being suppressed — "calculate mode
ignores the raid-item limit", "calculate mode allows the same augment twice" —
which is a strange thing to have to test, and was only necessary because an
evaluation was borrowing a search.

They are properties of the evaluator now, and there is nothing to suppress:
`rules.evaluate` has no candidate pool, no constraints and no way to express a
restriction. The tests are kept because the BEHAVIOUR still matters to a user
with a real gearset — they just no longer need a solver to state it.

The third (`test_ec12_calculate_mode_skips_every_tier_stage`) was purely about
ILP staging and is gone: a recalculation runs no stages by construction, which
is asserted here directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimizer import PriorityEntry  # noqa: E402
from rules import evaluate  # noqa: E402


def item(name, buffs, sets=None, minor=False):
    return {"name": name, "file": f"{name}.item", "ml": 34, "buffs": buffs,
            "sets": sets or [], "augments": [], "minor": minor,
            "is_raid": False, "pack": None}


def augment(name, colour, buffs):
    return {"name": name, "type": colour, "buffs": buffs, "ml": 34}


def filigree(name, buffs, set_name=None, base_name=None):
    return {"name": name, "buffs": buffs, "set": set_name,
            "base_name": base_name or name}


def evaluate_one(equipped, entries, augments_by_slot=None, fil_weapon=None,
                 fil_artifact=None, sets=None):
    return evaluate.evaluate_gearset(
        equipped, augments_by_slot or {}, fil_weapon or [], fil_artifact or [],
        sets or {}, entries)


def test_the_same_augment_may_be_slotted_twice():
    """Solar/Lunar Gems are craftable in multiple copies — no bind-unique
    restriction — so a real gearset can carry the same augment name in two
    slots. The search caps it at one to stop the solver filling every colour
    with one augment; an evaluation has no reason to.

    Stacking on purpose: a non-stacking bonus would collapse to the max of the
    two and prove nothing.
    """
    entries = [PriorityEntry("Charisma", 1, None, 0)]
    result = evaluate_one(
        [("Armor", item("Plate", [])), ("Cloak", item("Cape", []))],
        entries,
        augments_by_slot={
            "Armor": [augment("Solar Gem of Charisma", "Sun", [("Charisma", "Stacking", 4.0)])],
            "Cloak": [augment("Solar Gem of Charisma", "Sun", [("Charisma", "Stacking", 4.0)])],
        })
    assert result["success"]
    assert result["realizedStats"]["Charisma"] == 8.0


def test_a_raid_item_limit_cannot_reach_an_evaluation():
    """The cap is a search preference — how many raid items the solver may
    PROPOSE. A gearset saved under a looser limit used to become permanently
    uncalculatable because the constraint was applied while evaluating it.

    There is no argument for it here, which is the strongest form of the fix:
    `evaluate_gearset`'s signature cannot carry one.
    """
    import inspect
    signature = inspect.signature(evaluate.evaluate_gearset)
    for forbidden in ("raid_item_limit", "excluded_packs", "armor_restriction",
                      "owned_names", "max_ml", "min_ml"):
        assert forbidden not in signature.parameters, (
            f"evaluate_gearset grew a {forbidden!r} parameter — a search "
            "restriction has reached the evaluator")

    raid_trinket = item("Raid Trinket", [("Charisma", "Stacking", 5.0)])
    raid_trinket["is_raid"] = True
    raid_belt = item("Raid Belt", [("Charisma", "Stacking", 5.0)])
    raid_belt["is_raid"] = True

    result = evaluate_one([("Trinket", raid_trinket), ("Belt", raid_belt)],
                          [PriorityEntry("Charisma", 1, None, 0)])
    assert result["realizedStats"]["Charisma"] == 10.0


def test_two_filigrees_sharing_a_base_name_are_both_credited():
    """The headline defect. `optimizer.py:1817` caps filigrees at one per base
    name per bucket — a heuristic about what to propose — and it made a real
    saved gearset unevaluatable (known_deltas.yaml `unevaluatable_today`).

    Two filigrees sharing a base name are two pieces of the same named set,
    which is precisely what set bonuses need.
    """
    entries = [PriorityEntry("Charisma", 1, None, 0)]
    result = evaluate_one(
        [("Weapon1", item("Sword", []))], entries,
        fil_weapon=[
            filigree("Lunar Magic: +2 Charisma", [("Charisma", "Stacking", 2.0)],
                     base_name="Lunar Magic"),
            filigree("Lunar Magic: +3 Charisma", [("Charisma", "Stacking", 3.0)],
                     base_name="Lunar Magic"),
        ])
    assert result["success"]
    assert result["realizedStats"]["Charisma"] == 5.0


def test_a_recalculation_runs_no_tier_stages():
    """What test_ec12 used to assert about the ILP, stated directly: there are
    no stages because there is no solve."""
    result = evaluate_one([("Helmet", item("Hat", [("A", "Enhancement", 10.0)]))],
                          [PriorityEntry("A", 1, None, 0)])
    assert result["tierReport"]["stages"] == []
    assert result["tierScores"] == {}
    assert result["gearSet"] == {"Helmet": "Hat"}
    assert result["realizedStats"]["A"] == 10.0


def test_warnings_never_stop_the_numbers():
    """`validate_physical_rules` warns, never refuses — the policy carried from
    the deprecated spec. A gearset with corrupted saved data still totals up."""
    entries = [PriorityEntry("Charisma", 1, None, 0)]
    result = evaluate_one(
        [("Weapon1", item("Sword", []))], entries,
        fil_weapon=[
            filigree("Lunar Magic", [("Charisma", "Stacking", 2.0)]),
            filigree("Lunar Magic", [("Charisma", "Stacking", 2.0)]),
            {"name": "", "buffs": [], "set": None, "base_name": ""},
        ])
    kinds = {w["kind"] for w in result["warnings"]}
    assert evaluate.WARN_DUPLICATE_FILIGREE in kinds
    assert evaluate.WARN_EMPTY_FILIGREE in kinds
    # ...and the numbers came back anyway.
    assert result["success"]
    assert result["realizedStats"]["Charisma"] == 4.0


def test_the_base_name_rule_is_not_reported_as_a_problem():
    """Two filigrees sharing a base name must not even WARN. Whether the search
    heuristic is right is a separate, open question (known_deltas.yaml
    `out_of_scope_question`); what is settled is that it says nothing about what
    a user may equip."""
    result = evaluate_one(
        [("Weapon1", item("Sword", []))], [PriorityEntry("Charisma", 1, None, 0)],
        fil_weapon=[
            filigree("Lunar Magic: +2 Charisma", [("Charisma", "Stacking", 2.0)],
                     base_name="Lunar Magic"),
            filigree("Lunar Magic: +3 Charisma", [("Charisma", "Stacking", 3.0)],
                     base_name="Lunar Magic"),
        ])
    assert result["warnings"] == []


def test_other_stats_carries_what_was_not_asked_for():
    """realizedStats holds what the user asked for, spelled their way;
    otherStats holds the rest. Conflating them is why a priority that matched
    nothing used to look identical to one the gear did not provide."""
    result = evaluate_one(
        [("Helmet", item("Hat", [("Charisma", "Enhancement", 4.0),
                                 ("Dodge", "Enhancement", 3.0)]))],
        [PriorityEntry("Charisma", 1, None, 0)])
    assert result["realizedStats"] == {"Charisma": 4.0}
    assert result["otherStats"] == {"Dodge": 3.0}


def test_effects_are_reported_structurally_as_well_as_for_display():
    """`allEffectsDetail` carries the value, bonus type and source the display
    string encodes, so nothing downstream has to parse it back out."""
    result = evaluate_one(
        [("Helmet", item("Hat", [("Charisma", "Enhancement", 4.0)]))],
        [PriorityEntry("Charisma", 1, None, 0)])
    assert result["allEffects"]["Charisma"] == ["4.0 Enhancement (Hat)"]
    assert result["allEffectsDetail"]["Charisma"] == [
        {"value": 4.0, "bonusType": "Enhancement", "sourceName": "Hat", "sourceKind": "item"}]
