"""Phase 10 — tiered priority solver.

Covers the acceptance criteria in docs/PHASE10_PLAN.md §10 / §14.5 / §15.9 that
are exercisable from Python alone (the Go-side AC-40..AC-43 and AC-45 belong to
Phase 10b).
"""

import io
import os
import types
import xml.etree.ElementTree as ET

import pulp
import pytest

import optimizer
import solver
from optimizer import PriorityEntry


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def make_item(name, slots, buffs, sets=None, augments=None, minor=False, ml=34):
    return {
        'name': name,
        'file': f'{name}.item',
        'slots': list(slots),
        'buffs': list(buffs),
        'sets': list(sets or []),
        'augments': list(augments or []),
        'minor': minor,
        'is_raid': False,
        'pack': None,
        'ml': ml,
    }


def make_filigree(name, buffs, set_name=None, base_name=None):
    return {
        'name': name,
        'base_name': base_name or name,
        'set': set_name,
        'buffs': list(buffs),
    }


def solve(items, entries, sets=None, augments=None, filigrees=None, **kwargs):
    out = io.StringIO()
    result = optimizer.run_optimization(
        items, sets or {}, augments or [], filigrees or [], entries,
        out, 34, 4, max_search_time=kwargs.pop('max_search_time', 30), **kwargs)
    return result, out.getvalue()


# ---------------------------------------------------------------------------
# Unit — payload parsing and validation (AC-1 .. AC-9)
# ---------------------------------------------------------------------------

def test_ac1_shape_c_parses_with_intra_tier_order_and_caps():
    entries, err = solver.parse_stat_priorities([
        {"stat": "Ranged Power", "tier": 1},
        {"stat": "Doubleshot", "tier": 1},
        {"stat": "Melee Power", "tier": 3, "cap": 50},
    ])
    assert err is None
    assert [e.stat for e in entries] == ["Ranged Power", "Doubleshot", "Melee Power"]
    assert [e.tier for e in entries] == [1, 1, 3]
    assert [e.order for e in entries] == [0, 1, 0]
    assert [e.cap for e in entries] == [None, None, 50.0]


def test_ac2_shape_b_value_migrates_to_tiers():
    entries, err = solver.parse_stat_priorities([
        {"stat": "Ranged Power", "value": 100},
        {"stat": "Doubleshot", "value": 100},
        {"stat": "Melee Power[50]", "value": 60},
    ])
    assert err is None
    assert [e.tier for e in entries] == [1, 1, 3]
    assert [e.order for e in entries] == [0, 1, 0]
    assert entries[2].stat == "Melee Power"
    assert entries[2].cap == 50.0


def test_ac3_shape_a_legacy_dict_migrates():
    entries, err = solver.parse_stat_priorities({
        "Constitution": 100,
        "Charisma": 90,
        "Melee Power[50]": 85,
        "Doublestrike": 70,
    })
    assert err is None
    # NOTE: docs/PHASE10_PLAN.md §2.4's Shape-A *example* shows Doublestrike
    # (value 70) migrating to tier 2, which contradicts both the migration table
    # in the same section and AC-4's explicit boundary list (50-74 -> 3). The
    # table wins; the example is a typo.
    assert [e.tier for e in entries] == [1, 2, 2, 3]
    assert [e.order for e in entries] == [0, 0, 1, 0]
    caps = {e.stat: e.cap for e in entries}
    assert caps["Melee Power"] == 50.0
    assert caps["Constitution"] is None


@pytest.mark.parametrize("value,tier", [
    (100, 1), (99, 2), (75, 2), (74, 3), (50, 3), (49, 4), (25, 4), (24, 5), (0, 5),
])
def test_ac4_legacy_boundary_values(value, tier):
    entries, err = solver.parse_stat_priorities([{"stat": "X", "value": value}])
    assert err is None
    assert entries[0].tier == tier


def test_ac5_same_stat_in_two_tiers_is_an_error_not_an_exception():
    entries, err = solver.parse_stat_priorities([
        {"stat": "Melee Power", "tier": 1},
        {"stat": "melee power[50]", "tier": 3},
    ])
    assert entries == []
    assert err is not None
    assert "appears in more than one tier" in err
    assert err.startswith(solver.VALIDATION_PREFIX)


def test_ac6_same_stat_twice_in_one_tier():
    _entries, err = solver.parse_stat_priorities([
        {"stat": "Melee Power", "tier": 3},
        {"stat": " melee power ", "tier": 3},
    ])
    assert "is listed more than once" in err


def test_ac7_invalid_tier_cap_and_empty_list():
    _e, err = solver.parse_stat_priorities([{"stat": "X", "tier": 7}])
    assert "must be 1-5" in err

    _e, err = solver.parse_stat_priorities([{"stat": "X", "tier": 1, "cap": 0}])
    assert "must be a positive integer" in err

    _e, err = solver.parse_stat_priorities([])
    assert "no stat priorities" in err

    _e, err = solver.parse_stat_priorities([{"stat": "X", "tier": 1}, {"stat": "Y"}])
    assert "missing a tier" in err


def test_ac8_priority_names_contain_every_tier():
    """INV-2 regression guard — dropping tier-5 stats would make matching XML
    data invisible to normalize_stat_name and therefore to the whole model."""
    raw = [{"stat": f"S{t}", "tier": t} for t in range(1, 6)]
    entries, err = solver.parse_stat_priorities(raw)
    assert err is None
    names = [e.stat for e in entries]
    assert names == ["S1", "S2", "S3", "S4", "S5"]


def test_ac9_mode_normalization():
    assert solver.normalize_mode({"calculate_only": True}) == ("calculate", None)
    assert solver.normalize_mode({"mode": "alternatives"}) == ("alternatives", None)
    assert solver.normalize_mode({}) == ("optimize", None)
    mode, err = solver.normalize_mode({"mode": "foo"})
    assert mode is None and "mode 'foo'" in err


def test_ec22_cap_field_wins_over_suffix_and_warns():
    warnings = []
    entries, err = solver.parse_stat_priorities(
        [{"stat": "Melee Power[30]", "tier": 2, "cap": 50}], warnings)
    assert err is None
    assert entries[0].cap == 50.0
    assert warnings and "cap field" in warnings[0]


# ---------------------------------------------------------------------------
# Unit — weights (AC-10, AC-11)
# ---------------------------------------------------------------------------

def test_ac10_tier_weights_three_stats():
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 1, None, 1),
               PriorityEntry("C", 1, None, 2)]
    w = optimizer.compute_tier_weights(entries)[1]
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["A"] > w["B"] > w["C"]
    assert abs(w["A"] - 0.641) < 1e-3
    assert abs(w["B"] - 0.2564) < 1e-3
    assert abs(w["C"] - 0.1026) < 1e-3


def test_ac11_twenty_stat_tier_keeps_every_weight_positive():
    entries = [PriorityEntry(f"S{i}", 2, None, i) for i in range(20)]
    w = optimizer.compute_tier_weights(entries)[2]
    assert len(w) == 20
    assert all(v > 0 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_weights_normalize_per_tier_independently():
    entries = [PriorityEntry("A", 1, None, 0),
               PriorityEntry("B", 3, None, 0), PriorityEntry("C", 3, None, 1)]
    w = optimizer.compute_tier_weights(entries)
    assert abs(sum(w[1].values()) - 1.0) < 1e-9
    assert abs(sum(w[3].values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Unit — upper bounds (AC-12 .. AC-15)
# ---------------------------------------------------------------------------

def _ub_fixture(b_type, vals_by_slot, origin='item'):
    sources = {}
    entries = []
    for slot, val in vals_by_slot:
        entries.append((val, optimizer._UBVar(ddo_slot=slot), f"src_{slot}", origin))
    sources[("S", b_type)] = entries
    return sources


def test_ac12_non_stacking_bound_is_the_max_not_the_sum():
    sources = _ub_fixture("Enhancement", [("Helmet", 10.0), ("Cloak", 15.0)])
    ub = optimizer.compute_stat_upper_bounds(
        sources, [], ["Helmet", "Cloak"], {}, True)
    assert ub["S"] == 15.0


def test_ac13_stacking_bound_sums_across_slots():
    sources = _ub_fixture("Stacking", [("Helmet", 10.0), ("Cloak", 15.0), ("Belt", 5.0)])
    ub = optimizer.compute_stat_upper_bounds(
        sources, [], ["Helmet", "Cloak", "Belt"], {}, True)
    assert ub["S"] == 30.0


def test_ac14_cap_clamps_the_upper_bound():
    sources = _ub_fixture("Stacking", [("Helmet", 30.0), ("Cloak", 30.0)])
    ub = optimizer.compute_stat_upper_bounds(
        sources, [], ["Helmet", "Cloak"], {"S": 20.0}, True)
    assert ub["S"] == 20.0


def test_ac15_nofil_variant_excludes_filigrees_and_floors_at_1e6():
    sources = {("S", "Enhancement"): [
        (12.0, optimizer._UBVar(ddo_fil_base="Fil"), "Fil", 'filigree'),
    ]}
    ub_all = optimizer.compute_stat_upper_bounds(sources, [], ["Helmet"], {}, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(sources, [], ["Helmet"], {}, False)
    assert ub_all["S"] == 12.0
    assert ub_nofil["S"] == optimizer.UB_FLOOR


def test_ec4_stat_with_zero_sources_is_omitted_entirely():
    ub = optimizer.compute_stat_upper_bounds({}, [], ["Helmet"], {}, True)
    assert ub == {}


def test_ec19_stat_under_two_bonus_types_sums_the_per_type_bounds():
    sources = {
        ("S", "Enhancement"): [(10.0, optimizer._UBVar(ddo_slot="Helmet"), "a", 'item')],
        ("S", "Stacking"): [(4.0, optimizer._UBVar(ddo_slot="Cloak"), "b", 'item')],
    }
    ub = optimizer.compute_stat_upper_bounds(sources, [], ["Helmet", "Cloak"], {}, True)
    assert ub["S"] == 14.0


def test_augment_slot_budget_is_structural():
    items = [make_item("A", ["Helmet"], [], augments=["Red", "Blue"]),
             make_item("B", ["Helmet"], [], augments=["Red"]),
             make_item("C", ["Cloak"], [], augments=["Green", "Green", "Green"])]
    assert optimizer._augment_slot_budget(items, ["Helmet", "Cloak"]) == 5


# ---------------------------------------------------------------------------
# Unit — model structure (AC-16 .. AC-20, AC-48)
# ---------------------------------------------------------------------------

def _basic_model():
    items = [
        make_item("Dense", ["Helmet"], [("A", "Enhancement", 10.0), ("B", "Enhancement", 10.0)]),
        make_item("SoloA", ["Cloak"], [("A", "Enhancement", 10.0)]),
        make_item("SoloB", ["Belt"], [("B", "Enhancement", 10.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 1, None, 1)]
    model = optimizer.create_model(items, {}, [], [], entries, 4,
                                   ["Helmet", "Cloak", "Belt"])
    return items, entries, model


def test_ac16_no_capped_total_variables_remain():
    _i, _e, model = _basic_model()
    assert not [v for v in model.prob.variables() if v.name.startswith("capped_total_")]


def test_ac17_filigree_bias_mechanism_is_gone():
    assert not hasattr(optimizer, "compute_priority_bias")
    assert not hasattr(optimizer, "FILIGREE_BIAS_SCALE")
    assert not hasattr(optimizer, "solve_for_alternatives")


def test_ac18_z_nofil_aliases_z_unless_tier2plus_and_filigree_backed():
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0),
                                           ("C", "Enhancement", 3.0)])]
    filigrees = [make_filigree("Fil", [("A", "Enhancement", 5.0),
                                       ("C", "Enhancement", 4.0)])]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("C", 3, None, 0)]
    model = optimizer.create_model(items, {}, [], filigrees, entries, 4, ["Helmet"])

    # tier-1 stat: always aliased, even though it has filigree sources
    assert model.z_nofil[("A", "Enhancement")] is model.z[("A", "Enhancement")]
    # tier-3 stat with a filigree source: a genuinely distinct variable
    assert model.z_nofil[("C", "Enhancement")] is not model.z[("C", "Enhancement")]


def test_z_nofil_aliases_when_no_filigree_source_exists():
    items = [make_item("Hat", ["Helmet"], [("C", "Enhancement", 3.0)])]
    entries = [PriorityEntry("C", 3, None, 0)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Helmet"])
    assert model.z_nofil[("C", "Enhancement")] is model.z[("C", "Enhancement")]


def test_ac19_tier4_goal_uses_breadth_coefficient_two():
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)]),
             make_item("Cape", ["Cloak"], [("B", "Enhancement", 4.0)])]
    entries = [PriorityEntry("A", 4, None, 0), PriorityEntry("B", 4, None, 1)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Helmet", "Cloak"])

    goal = model.goals[4]
    for stat, var in model.present.items():
        assert abs(goal[var] - 2.0) < 1e-9
    # exactly one <=-direction linking constraint per present_s.
    # NB: `var in constraint` cannot be used — LpVariable.__eq__ is overloaded
    # to build constraints, so `in` matches the first element of anything.
    for stat, var in model.present.items():
        linking = [c for c in model.prob.constraints.values()
                   if any(v.name == var.name for v in c.keys())]
        assert len(linking) == 1
        assert linking[0].sense == pulp.LpConstraintLE


def test_ac20_penalty_dup_excludes_sets_and_stacking_types():
    sets = {"Legendary": {2: [("A", "Enhancement", 5.0)]}}
    items = [
        make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0),
                                      ("A", "Stacking", 2.0)], sets=["Legendary"]),
        make_item("Cape", ["Cloak"], [("A", "Enhancement", 8.0)], sets=["Legendary"]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    model = optimizer.create_model(items, sets, [], [], entries, 4, ["Helmet", "Cloak"])

    dup_vars = set(model.penalty_dup.keys())
    # no set-bonus w_var participates
    for w_var in model.w_vars.values():
        assert w_var not in dup_vars
    # the stacking source's x var contributes to penalty_item but never to
    # penalty_dup as a (var - d) pair, because stacking types build no d vars
    assert ("A", "Stacking") not in model.d_vars
    # only non-stacking origins item/augment/filigree are represented
    for (stat, b_type) in model.d_vars:
        assert not optimizer._is_stacking(b_type)


def test_ac48_slot_occupancy_constraints_are_inequalities():
    """INV-7 static guard — catches a 'fix' of `<= 1` into `== 1` immediately."""
    items, _e, model = _basic_model()
    x_vars = set(model.x.values())
    for name, c in model.prob.constraints.items():
        if c.sense != pulp.LpConstraintEQ:
            continue
        touched = [v for v in c.keys() if v in x_vars]
        # the only permitted equalities over x are the minor-artifact rule and
        # pre_equipped pins; this fixture has neither
        assert not touched, f"unexpected equality over x variables: {name}"


def test_create_model_sets_no_objective():
    """INV-5 — each stage installs its own objective."""
    _i, _e, model = _basic_model()
    assert model.prob.objective is None


def test_unmatched_priorities_are_reported_and_dropped_from_weights():
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)])]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("Typoed Stat", 1, None, 1)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Helmet"])
    assert model.unmatched == ["Typoed Stat"]
    assert set(model.weights[1]) == {"A"}
    assert abs(sum(model.weights[1].values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Integration — solve behavior
# ---------------------------------------------------------------------------

def test_ac46_empty_slot_preference_consolidation_drops_redundant_items():
    items = [
        make_item("Dense", ["Helmet"], [("A", "Enhancement", 10.0), ("B", "Enhancement", 10.0)]),
        make_item("SoloA", ["Cloak"], [("A", "Enhancement", 10.0)]),
        make_item("SoloB", ["Belt"], [("B", "Enhancement", 10.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 1, None, 1)]
    result, _log = solve(items, entries)

    assert result["gearSet"] == {"Helmet": "Dense"}
    assert "Cloak" not in result["slots"] and "Belt" not in result["slots"]
    assert len(result["gearSet"]) == 1


def test_ac47_load_bearing_items_are_retained():
    items = [
        make_item("Dense", ["Helmet"], [("A", "Enhancement", 10.0)]),
        make_item("SoloB", ["Belt"], [("B", "Enhancement", 10.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 1, None, 1)]
    result, _log = solve(items, entries)

    assert set(result["gearSet"].values()) == {"Dense", "SoloB"}
    assert len(result["gearSet"]) == 2
    assert result["realizedStats"]["A"] == 10.0
    assert result["realizedStats"]["B"] == 10.0


def test_ac21_all_tier1_produces_one_stage_and_no_stat_regresses_to_zero():
    items = [
        make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)]),
        make_item("Cape", ["Cloak"], [("B", "Enhancement", 6.0)]),
        make_item("Belt", ["Belt"], [("C", "Enhancement", 4.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 1, None, 1),
               PriorityEntry("C", 1, None, 2)]
    result, _log = solve(items, entries)
    assert [s["tier"] for s in result["tierReport"]["stages"]] == [1]
    for stat in ("A", "B", "C"):
        assert result["realizedStats"][stat] > 0


def test_ac31_no_eager_weapon_alternatives_search():
    wb = optimizer.WEAPON_BASE_BONUS_TYPE
    items = [make_item("Dagger", ["Weapon1"], [("critical multiplier", wb, 3.0)]),
             make_item("Other Dagger", ["Weapon1"], [("critical multiplier", wb, 2.0)])]
    entries = [PriorityEntry("critical multiplier", 1, None, 0)]
    _result, log = solve(items, entries)
    assert "Alternatives" not in log


def test_ac28_tiny_budget_still_returns_a_gearset():
    items = [make_item(f"Hat{i}", ["Helmet"], [("A", "Enhancement", float(i))])
             for i in range(1, 30)]
    items += [make_item(f"Cape{i}", ["Cloak"], [("B", "Enhancement", float(i))])
              for i in range(1, 30)]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 3, None, 0)]
    result, _log = solve(items, entries, max_search_time=10)
    assert result.get("success") is not False
    assert result["gearSet"]


def test_ac22_lock_monotonicity_tier1_survives_tier3():
    """Tier 3 must not be able to buy its value with tier-1 value."""
    items = [
        # Helmet choice: high A (tier 1) OR high C (tier 3), never both.
        make_item("HatA", ["Helmet"], [("A", "Enhancement", 10.0)]),
        make_item("HatC", ["Helmet"], [("C", "Enhancement", 10.0)]),
        make_item("Cape", ["Cloak"], [("C", "Enhancement", 4.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("C", 3, None, 0)]
    result, _log = solve(items, entries)

    stages = result["tierReport"]["stages"]
    assert [s["tier"] for s in stages] == [1, 3]
    v1 = stages[0]["goalValue"]
    assert float(result["tierScores"]["1"]) >= v1 - 1e-5
    assert result["gearSet"]["Helmet"] == "HatA"
    # tier 3 still picks up what it can without touching tier 1
    assert result["realizedStats"]["C"] == 4.0


# --- regression: spurious "lock_violation" on every stage -------------------
#
# The tier_lock_t constraint is `G_t >= V_t - _lock_tolerance(V_t)`, and every
# later stage maximizes a different goal, so the solver spends that whole slack
# and parks G_t exactly ON the bound. The self-check used to compare against the
# same _lock_tolerance(), i.e. it tested `G_t < RHS` on a value the solver had
# set equal to RHS. Whether that fired was decided purely by how the 12-digit
# round trip through GLPK's solution file rounded the last digit, so stages
# reported "lock_violation", threw away good incumbents and returned degraded
# gearsets on ordinary, perfectly solvable inputs.

def test_lock_check_tolerance_is_strictly_looser_than_the_constraint():
    for v in (0.0, 1e-9, 0.4216264732280803, 1.0, 2.972222222222222, 1e6):
        assert optimizer._lock_check_tolerance(v) > optimizer._lock_tolerance(v)


def test_solution_parked_exactly_on_the_lock_bound_is_not_a_violation():
    """Real numbers from the reproducing run: tier 4 locked at V, and the next
    stage returned G_4 == V - tol as written back at 12 significant digits."""
    v = 2.972222222222222
    on_the_bound = v - optimizer._lock_tolerance(v)
    round_tripped = float(f"{on_the_bound:.12g}")

    # The old check (constraint tolerance reused as the check tolerance) fires.
    assert round_tripped < v - optimizer._lock_tolerance(v)

    model = types.SimpleNamespace(goals={4: round_tripped})
    assert optimizer._first_lock_violation(model, {4: v}) is None


def test_a_real_regression_below_the_lock_is_still_caught():
    v = 2.972222222222222
    model = types.SimpleNamespace(goals={4: v - 0.01})
    assert optimizer._first_lock_violation(model, {4: v}) == 4


def test_five_tier_solve_locks_every_tier_without_degrading():
    """End-to-end guard: a config with no tier conflicts must lock all five
    tiers, report no lock_violation, and come back undegraded."""
    stats = ["A", "B", "C", "D", "E", "F"]
    # Values chosen so every G_t is a non-terminating binary fraction — the
    # round-trip rounding that triggered the bug needs inexact goal values.
    items = []
    for si, slot in enumerate(["Helmet", "Cloak", "Belt", "Boots", "Gloves",
                               "Goggles", "Necklace", "Bracers", "Trinket"]):
        for k in range(3):
            stat = stats[(si + k) % len(stats)]
            items.append(make_item(f"{slot}{k}", [slot],
                                   [(stat, "Enhancement", 3.0 + si * 7 + k)]))
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("B", 1, None, 1),
               PriorityEntry("C", 2, None, 0), PriorityEntry("D", 3, None, 0),
               PriorityEntry("E", 4, None, 0), PriorityEntry("F", 5, None, 0)]

    result, _log = solve(items, entries, max_search_time=30)
    report = result["tierReport"]

    assert [s["tier"] for s in report["stages"]] == [1, 2, 3, 4, 5]
    assert [s["status"] for s in report["stages"]].count("lock_violation") == 0
    for stage in report["stages"]:
        assert stage["goalValue"] is not None
    assert report["degraded"] is False

    # Every lock must still hold in the final, post-consolidation solution.
    for stage in report["stages"]:
        tier = str(stage["tier"])
        assert float(result["tierScores"][tier]) >= stage["goalValue"] - 1e-4


def test_ac23_tier4_breadth_when_free():
    items = [
        make_item("HatA", ["Helmet"], [("A", "Enhancement", 10.0)]),
        make_item("Cape", ["Cloak"], [("D", "Enhancement", 3.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("D", 4, None, 0)]
    result, _log = solve(items, entries)

    assert result["realizedStats"]["D"] > 0
    assert "D" not in result["unmetTier4"]


def test_ac24_tier4_is_subordinate_to_tier1():
    items = [
        make_item("HatA", ["Helmet"], [("A", "Enhancement", 10.0)]),
        # The only source of D would have to take the Helmet slot from HatA.
        make_item("HatD", ["Helmet"], [("D", "Enhancement", 10.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("D", 4, None, 0)]
    result, _log = solve(items, entries)

    assert result["gearSet"]["Helmet"] == "HatA"
    assert "D" in result["unmetTier4"]
    assert abs(float(result["tierScores"]["1"]) - 1.0) < 1e-6


def test_ac25_reconciliation_reports_every_live_priority_stat():
    """Direct regression guard for the zero-weight display corruption bug."""
    items = [
        make_item("Dense", ["Helmet"], [("A", "Enhancement", 10.0), ("E", "Enhancement", 7.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("E", 5, None, 0)]
    result, _log = solve(items, entries)

    for stat in result["priorityTiers"]:
        if stat in result["allEffects"]:
            assert result["realizedStats"].get(stat, 0) > 0
    assert result["realizedStats"]["E"] == 7.0


def test_reconciliation_lp_fills_in_stats_a_stage_objective_ignored():
    """Isolate §6: solve with ONLY tier 1 in the objective, verify the tier-5
    stat's z is left at 0, then verify reconciliation repairs it."""
    items = [make_item("Dense", ["Helmet"],
                       [("A", "Enhancement", 10.0), ("E", "Enhancement", 7.0)])]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("E", 5, None, 0)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Helmet"])

    model.prob.setObjective(model.goals[1])
    optimizer._solve(model.prob, 10)
    assert optimizer._val(model.z[("A", "Enhancement")]) == 10.0
    corrupted = optimizer._val(model.z[("E", "Enhancement")])

    assert optimizer.reconcile_solution(model) is True
    assert optimizer._val(model.z[("E", "Enhancement")]) == 7.0
    assert corrupted == 0.0 or corrupted == 7.0  # GLPK may or may not have set it


def test_ac26_set_bonuses_survive_consolidation():
    sets = {"Legendary": {2: [("A", "Stacking", 5.0)]}}
    items = [
        make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)], sets=["Legendary"]),
        make_item("Cape", ["Cloak"], [("A", "Enhancement", 1.0)], sets=["Legendary"]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    result, _log = solve(items, entries, sets=sets)

    assert result["activeSets"] == ["Legendary (2-piece)"]
    assert any("Stacking" in e for e in result["allEffects"]["A"])


def test_ec12_calculate_mode_skips_every_tier_stage():
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)]),
             make_item("Cape", ["Cloak"], [("A", "Enhancement", 12.0)])]
    entries = [PriorityEntry("A", 1, None, 0)]
    result, _log = solve(items, entries, mode="calculate",
                         pre_equipped={"Helmet": "Hat"})

    assert result["tierReport"]["stages"] == []
    assert result["gearSet"] == {"Helmet": "Hat"}
    # display truth comes from the reconciliation LP even with no goal in the
    # objective at any point
    assert result["realizedStats"]["A"] == 10.0


def test_ec2_single_priority_in_tier3_produces_one_stage():
    items = [make_item("Hat", ["Helmet"], [("C", "Enhancement", 10.0)])]
    entries = [PriorityEntry("C", 3, None, 0)]
    result, _log = solve(items, entries)
    assert [s["tier"] for s in result["tierReport"]["stages"]] == [3]
    assert abs(float(result["tierScores"]["3"]) - 1.0) < 1e-6


def test_ec4_all_priorities_unmatched_fails_with_a_clear_message():
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)])]
    entries = [PriorityEntry("Typo", 1, None, 0)]
    result, _log = solve(items, entries)
    assert result["success"] is False
    assert "None of the listed stat priorities matched" in result["errorMessage"]


def test_ec1_sparse_tiers_produce_one_stage_each():
    budgets, cons, total = optimizer._stage_budgets([1, 4], 100)
    assert len(budgets) == 2
    ratio = budgets[0] / (budgets[0] + budgets[1])
    assert abs(ratio - 0.35 / 0.47) < 1e-6


def test_ec20_budget_defaults_and_clamps():
    _b, _c, total = optimizer._stage_budgets([1], None)
    assert total == 60.0
    _b, _c, total = optimizer._stage_budgets([1], -5)
    assert total == 60.0
    _b, _c, total = optimizer._stage_budgets([1], 5)
    assert total == optimizer.MIN_TOTAL_BUDGET
    _b, _c, total = optimizer._stage_budgets([1], 99999)
    assert total == optimizer.MAX_TOTAL_BUDGET


def test_ec8_degenerate_low_budget_splits_evenly():
    budgets, cons, total = optimizer._stage_budgets([1, 2, 3, 4, 5], 10)
    assert cons == 5.0
    assert budgets == [1.0] * 5


def test_ec17_no_filigrees_means_z_nofil_is_z_everywhere():
    items = [make_item("Hat", ["Helmet"], [("C", "Enhancement", 3.0)])]
    entries = [PriorityEntry("C", 2, None, 0)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Helmet"])
    for key, var in model.z.items():
        assert model.z_nofil[key] is var
    assert pulp.value(model.filigree_tiebreak) == 0


def test_ec18_filigree_only_tier2_stat_is_noted_and_scores_zero():
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 10.0)])]
    filigrees = [make_filigree("Fil", [("C", "Enhancement", 8.0)])]
    entries = [PriorityEntry("A", 1, None, 0), PriorityEntry("C", 2, None, 0)]
    model = optimizer.create_model(items, {}, [], filigrees, entries, 4, ["Helmet"])
    assert any("only obtainable from filigrees" in n for n in model.notes)
    assert model.upper_bounds["C"] == optimizer.UB_FLOOR


def test_filigrees_are_ordinary_tier1_sources():
    """§3.8 — no separate bias term; a filigree's tier-1 value flows through z."""
    items = [make_item("Hat", ["Helmet"], [("A", "Enhancement", 4.0)])]
    filigrees = [make_filigree("Fil", [("A", "Stacking", 6.0)])]
    entries = [PriorityEntry("A", 1, None, 0)]
    result, _log = solve(items, entries, filigrees=filigrees)
    assert result["filigrees"]["weapon"] == ["Fil"] or result["filigrees"]["artifact"] == ["Fil"]
    assert result["realizedStats"]["A"] == 10.0


def test_cap_saturates_the_goal_without_capping_display_truth():
    items = [make_item("Hat", ["Helmet"], [("A", "Stacking", 30.0)]),
             make_item("Cape", ["Cloak"], [("A", "Stacking", 30.0)])]
    entries = [PriorityEntry("A", 1, 20.0, 0)]
    result, _log = solve(items, entries)
    # UB is clamped to the cap so n_s saturates, but z keeps reporting reality
    assert result["realizedStats"]["A"] >= 30.0
    assert abs(float(result["tierScores"]["1"]) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# §15 — weapon combat properties (AC-49 .. AC-53)
# ---------------------------------------------------------------------------

def _weapon_xml(weapon_damage=None, number=None, sides=None, crit_mult=None, crit_range=None):
    parts = ["<Item>"]
    if weapon_damage is not None:
        parts.append(f"<WeaponDamage>{weapon_damage}</WeaponDamage>")
    if number is not None and sides is not None:
        parts.append(f"<BaseDice><Number>{number}</Number><Sides>{sides}</Sides></BaseDice>")
    if crit_mult is not None:
        parts.append(f"<CriticalMultiplier>{crit_mult}</CriticalMultiplier>")
    if crit_range is not None:
        parts.append(f"<CriticalThreatRange>{crit_range}</CriticalThreatRange>")
    parts.append("</Item>")
    return ET.fromstring("".join(parts))


def test_ac51_base_damage_dice_is_expected_value():
    node = _weapon_xml(number=2, sides=6)
    buffs = optimizer._weapon_base_buffs(node, {"base damage dice": "base damage dice"})
    assert buffs == [("base damage dice", optimizer.WEAPON_BASE_BONUS_TYPE, 7.0)]


def test_ac52_weapon_base_damage_is_the_product():
    node = _weapon_xml(weapon_damage=1.5, number=2, sides=6)
    buffs = optimizer._weapon_base_buffs(node, {"weapon base damage": "weapon base damage"})
    assert buffs == [("weapon base damage", optimizer.WEAPON_BASE_BONUS_TYPE, 10.5)]


def test_ac50_rune_arm_emits_no_weapon_base_stats():
    node = _weapon_xml()  # no weapon elements at all
    wanted = {name: name for name in optimizer.WEAPON_BASE_STATS}
    assert optimizer._weapon_base_buffs(node, wanted) == []


def test_weapon_base_stats_only_emitted_when_requested():
    node = _weapon_xml(weapon_damage=2.0, number=1, sides=8, crit_mult=3, crit_range=2)
    assert optimizer._weapon_base_buffs(node, {}) == []
    only_mult = optimizer._weapon_base_buffs(node, {"critical multiplier": "critical multiplier"})
    assert [b[0] for b in only_mult] == ["critical multiplier"]


def test_weapon_base_stats_bypass_the_substring_matcher():
    assert optimizer.normalize_stat_name(
        "CriticalMultiplier", "critical multiplier", "", ["critical multiplier"]) is None


def test_ac49_weapon_base_sources_are_weapon1_only():
    wb = optimizer.WEAPON_BASE_BONUS_TYPE
    items = [
        make_item("Sharp Dagger", ["Weapon1", "Weapon2"],
                  [("critical multiplier", wb, 3.0)]),
        make_item("Dull Dagger", ["Weapon1", "Weapon2"],
                  [("critical multiplier", wb, 2.0)]),
    ]
    entries = [PriorityEntry("critical multiplier", 1, None, 0)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Weapon1", "Weapon2"])

    # every source var for the weapon-base bucket is a Weapon1 x var
    srcs = model.sources[("critical multiplier", wb)]
    assert srcs, "expected weapon-base sources"
    assert all(getattr(var, 'ddo_slot', None) == "Weapon1" for _v, var, _s, _o in srcs)

    result, _log = solve(items, entries)
    # no summing, no cross-hand max-collapse: exactly the Weapon1 item's value
    assert result["realizedStats"]["critical multiplier"] == 3.0
    assert result["gearSet"]["Weapon1"] == "Sharp Dagger"


def test_ac53_tier4_weapon_baseline_is_the_corpus_bar_not_bare_presence():
    wb = optimizer.WEAPON_BASE_BONUS_TYPE
    items = [
        make_item("Plain Dagger", ["Weapon1"], [("critical multiplier", wb, 2.0)]),
        make_item("Other Dagger", ["Weapon1"], [("critical multiplier", wb, 2.0)]),
    ]
    entries = [PriorityEntry("critical multiplier", 4, None, 0)]
    result, _log = solve(items, entries)

    assert "critical multiplier" in result["unmetTier4"]
    # the weapon is still equipped and still displayed — just not "present"
    assert result["realizedStats"]["critical multiplier"] == 2.0


def test_weapon_tier4_baseline_met_clears_unmet_tier4():
    wb = optimizer.WEAPON_BASE_BONUS_TYPE
    items = [make_item("Keen Dagger", ["Weapon1"], [("critical multiplier", wb, 3.0)])]
    entries = [PriorityEntry("critical multiplier", 4, None, 0)]
    result, _log = solve(items, entries)
    assert result["unmetTier4"] == []


def test_ec29_composite_and_component_together_produce_a_note_not_a_rejection():
    wb = optimizer.WEAPON_BASE_BONUS_TYPE
    items = [make_item("Dagger", ["Weapon1"],
                       [("weapon base damage", wb, 10.5), ("weapon damage", wb, 1.5)])]
    entries = [PriorityEntry("weapon base damage", 1, None, 0),
               PriorityEntry("weapon damage", 1, None, 1)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Weapon1"])
    assert any("weapon base damage" in n and "component" in n for n in model.notes)


# ---------------------------------------------------------------------------
# docs/HARD_REQUIRED_SLOTS_SPEC.md — hard-required Weapon1/Weapon2
# ---------------------------------------------------------------------------

def make_weapon_item(name, slots, buffs, weapon_type, damage_type=None,
                      craftable_family=False, **kw):
    item = make_item(name, slots, buffs, **kw)
    item['weapon_type'] = weapon_type
    item['damage_type'] = damage_type
    item['craftable_family'] = craftable_family
    return item


def test_weapon_damage_types_matches_authoritative_source():
    # Spot-check against WeaponGroupings.xml's Slashing/Bludgeoning/Piercing
    # groups (taken verbatim, not derived from DRBypass or Description text).
    assert optimizer.WEAPON_DAMAGE_TYPES['longsword'] == 'Slashing'
    assert optimizer.WEAPON_DAMAGE_TYPES['warhammer'] == 'Bludgeoning'
    assert optimizer.WEAPON_DAMAGE_TYPES['rapier'] == 'Piercing'
    # Throwing Axe/Dagger/Hammer are real melee-usable weapon types but are in
    # none of the three WeaponGroupings.xml groups — deliberately unclassified.
    assert 'throwing axe' not in optimizer.WEAPON_DAMAGE_TYPES
    assert 'throwing dagger' not in optimizer.WEAPON_DAMAGE_TYPES
    assert 'throwing hammer' not in optimizer.WEAPON_DAMAGE_TYPES


def test_craftable_family_weapon_identification():
    # Name-substring families.
    assert optimizer._is_craftable_family_weapon("Dinosaur Bone Battle Axe", "") is True
    assert optimizer._is_craftable_family_weapon("Quarterstaff of the Undying Age", "") is True
    assert optimizer._is_craftable_family_weapon("Legendary Green Steel Quarterstaff", "") is True
    # DropLocation-substring families (no reliable name pattern).
    assert optimizer._is_craftable_family_weapon(
        "Legendary Calamitous Warhammer",
        "Viktranium Experiment crafting, Turn in 25 Legendary Bleak Alternators...") is True
    assert optimizer._is_craftable_family_weapon(
        "Some Weapon", "Den of Vipers, end reward") is True
    # An ordinary weapon from neither name nor drop location.
    assert optimizer._is_craftable_family_weapon("Ordinary Longsword", "Some Random Quest") is False


def test_weapon1_always_required_even_with_no_priority_benefit():
    # Two Weapon1 candidates, tied on the only priority — with nothing extra
    # to gain by picking one over the other, a solver with no hard
    # requirement could just as easily leave Weapon1 empty. It must not.
    items = [
        make_item("Plain Dagger", ["Weapon1"], [("melee power", "Enhancement", 1.0)]),
        make_item("Other Dagger", ["Weapon1"], [("melee power", "Enhancement", 1.0)]),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries)
    assert result["gearSet"].get("Weapon1"), "Weapon1 must never come back empty"


def test_weapon1_restricted_to_eligible_types_and_craftable_family():
    # The non-craftable Longsword scores far better on the priority — if the
    # hard filter weren't zeroing out its x-variable, the solver would equip
    # it every time. It must be excluded outright, forcing the far weaker
    # craftable-family weapon into Weapon1 instead.
    items = [
        make_weapon_item("Ordinary Longsword", ["Weapon1"], [("melee power", "Enhancement", 50.0)],
                         weapon_type="Longsword", damage_type="Slashing", craftable_family=False),
        make_weapon_item("Dinosaur Bone Battle Axe", ["Weapon1"], [("melee power", "Enhancement", 1.0)],
                         weapon_type="Battle Axe", damage_type="Slashing", craftable_family=True),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, weapon1_eligible_types={"longsword", "battle axe"})
    assert result["gearSet"]["Weapon1"] == "Dinosaur Bone Battle Axe"


def test_weapon1_eligible_types_excludes_types_not_listed_even_in_family():
    # A craftable-family weapon of a type NOT in weapon1_eligible_types must
    # still be excluded — the type filter and the family filter both apply.
    items = [
        make_weapon_item("Dinosaur Bone Warhammer", ["Weapon1"], [("melee power", "Enhancement", 50.0)],
                         weapon_type="Warhammer", damage_type="Bludgeoning", craftable_family=True),
        make_weapon_item("Dinosaur Bone Battle Axe", ["Weapon1"], [("melee power", "Enhancement", 1.0)],
                         weapon_type="Battle Axe", damage_type="Slashing", craftable_family=True),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, weapon1_eligible_types={"battle axe"})
    assert result["gearSet"]["Weapon1"] == "Dinosaur Bone Battle Axe"


def test_weapon1_fallback_when_no_craftable_family_candidate_exists():
    # Only a non-craftable Longsword is available — the family filter must
    # fall back to "any weapon of an eligible type" rather than making the
    # model infeasible, and must leave a note explaining it.
    items = [
        make_weapon_item("Ordinary Longsword", ["Weapon1"], [("melee power", "Enhancement", 50.0)],
                         weapon_type="Longsword", damage_type="Slashing", craftable_family=False),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, weapon1_eligible_types={"longsword"})
    assert result["gearSet"]["Weapon1"] == "Ordinary Longsword"
    notes = result["tierReport"]["notes"]
    assert any("fell back to any Longsword weapon" in n for n in notes), notes


def test_weapon1_fallback_not_triggered_when_family_candidate_exists():
    items = [
        make_weapon_item("Dinosaur Bone Battle Axe", ["Weapon1"], [("melee power", "Enhancement", 1.0)],
                         weapon_type="Battle Axe", damage_type="Slashing", craftable_family=True),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, weapon1_eligible_types={"battle axe"})
    notes = result["tierReport"]["notes"]
    assert not any("fell back" in n for n in notes), notes


def test_weapon1_pre_equipped_exempt_from_eligible_types_filter():
    # A saved gearset's pre-equipped Weapon1 must never be invalidated by a
    # filter introduced after it was saved — same principle as every other
    # pre_equipped bypass in this codebase.
    items = [
        make_weapon_item("Bludgeoning Club", ["Weapon1"], [("melee power", "Enhancement", 1.0)],
                         weapon_type="Club", damage_type="Bludgeoning", craftable_family=False),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, weapon1_eligible_types={"longsword"},
                         pre_equipped={"Weapon1": "Bludgeoning Club"})
    assert result["gearSet"]["Weapon1"] == "Bludgeoning Club"


def test_weapon2_eligible_types_restricts_to_craftable_family_kama():
    # Thrower off-hand: Weapon2 must specifically be a Kama, and still
    # respects the craftable-family + highest-ML heuristic.
    items = [
        make_weapon_item("Ordinary Kama", ["Weapon2"], [("melee power", "Enhancement", 50.0)],
                         weapon_type="Kama", damage_type="Slashing", craftable_family=False),
        make_weapon_item("Dinosaur Bone Kama", ["Weapon2"], [("melee power", "Enhancement", 1.0)],
                         weapon_type="Kama", damage_type="Slashing", craftable_family=True),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, weapon2_eligible_types={"kama"}, require_weapon2=True)
    assert result["gearSet"]["Weapon2"] == "Dinosaur Bone Kama"


def test_weapon_types_for_damage_type_matches_weapon_damage_types():
    slashing = optimizer.weapon_types_for_damage_type("Slashing")
    assert "battle axe" in slashing
    assert "longsword" in slashing
    assert "warhammer" not in slashing
    assert optimizer.weapon_types_for_damage_type("Bludgeoning") == {
        w for w, d in optimizer.WEAPON_DAMAGE_TYPES.items() if d == "Bludgeoning"
    }


# ---------------------------------------------------------------------------
# docs/HARD_REQUIRED_SLOTS_SPEC.md — Ranged/Tank addendum
# ---------------------------------------------------------------------------

def test_resolve_weapon_lists_bow_always_longbow_and_blocks_weapon2():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Ranged", "weapon_style": "Bow"})
    assert w1_types == {"longbow"}
    assert w2 == ["none"]
    assert req2 is False


def test_resolve_weapon_lists_repeating_crossbow_always_heavy():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Ranged", "weapon_style": "Repeating Crossbow"})
    assert w1_types == {"repeating heavy crossbow"}


def test_resolve_weapon_lists_great_crossbow():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Ranged", "weapon_style": "Great Crossbow"})
    assert w1_types == {"great crossbow"}


def test_resolve_weapon_lists_dual_crossbow_always_heavy():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Ranged", "weapon_style": "Dual Crossbow"})
    assert w1_types == {"heavy crossbow"}


def test_resolve_weapon_lists_crossbows_allow_runearm_only_when_checked():
    for style in ("Repeating Crossbow", "Great Crossbow", "Dual Crossbow"):
        w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
            {"build_type": "Ranged", "weapon_style": style, "runearm_use": True})
        assert w2 == ["rune arm", "runearm"], style
        assert req2 is True, style

        w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
            {"build_type": "Ranged", "weapon_style": style, "runearm_use": False})
        assert w2 == ["none"], style
        assert req2 is False, style


def test_resolve_weapon_lists_thrown_weapon2_is_always_kama():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Ranged", "weapon_style": "Thrown"})
    assert w2 == ["kama"]
    assert req2 is True
    assert w2_types == {"kama"}
    assert w1_types == {"throwing dagger", "throwing axe", "dart"}


def test_resolve_weapon_lists_shuriken_weapon2_is_always_kama():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Ranged", "weapon_style": "Shuriken"})
    assert w1_types == {"shuriken"}
    assert w2 == ["kama"]
    assert req2 is True
    assert w2_types == {"kama"}


def test_resolve_weapon_lists_tank_always_longsword_and_large_shield():
    # Blanket override — regardless of whatever weapon_style is selected.
    for style in ("Two Weapon Fighting", "Two Handed Fighting", "Sword and Board", "junk-value"):
        w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
            {"build_type": "Tank", "weapon_style": style})
        assert w1 == ["longsword"], style
        assert w2 == ["large shield"], style
        assert req2 is True, style
        assert w1_types == {"longsword"}, style
        assert w2_types == {"large shield"}, style


def test_resolve_weapon_lists_melee_damage_type_narrows_within_weapon_style():
    # Two Handed Fighting's own list spans both Slashing and Bludgeoning
    # types — picking Bludgeoning must narrow to just the Bludgeoning subset.
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Melee", "weapon_style": "Two Handed Fighting", "weapon_damage_type": "Bludgeoning"})
    assert w1_types == optimizer.weapon_types_for_damage_type("Bludgeoning")
    assert "maul" in w1_types
    assert "great axe" not in w1_types


def test_resolve_weapon_lists_melee_no_damage_type_is_unrestricted():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Melee", "weapon_style": "Two Weapon Fighting"})
    assert w1_types is None


def test_resolve_weapon_lists_caster_crossbow_and_runearm():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Caster", "weapon_style": "Crossbow and Runearm"})
    assert set(w1) == {'light crossbow', 'heavy crossbow', 'repeating light crossbow',
                       'repeating heavy crossbow', 'great crossbow'}
    assert w2 == ['rune arm', 'runearm']
    assert req2 is True
    # No further narrowing to one specific crossbow type — any crossbow type
    # is eligible, unlike the Ranged crossbow styles.
    assert w1_types is None


def test_resolve_weapon_lists_melee_single_handed_weapon_and_runearm():
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists(
        {"build_type": "Melee", "weapon_style": "Single Handed Weapon and Runearm"})
    assert set(w1) == optimizer.ONE_HANDED_WEAPON_TYPES
    assert w2 == ['rune arm', 'runearm']
    assert req2 is True
    # No weapon_damage_type set — unrestricted, same as any other melee style.
    assert w1_types is None


def test_resolve_weapon_lists_melee_single_handed_weapon_and_runearm_respects_damage_type():
    # The weapon_damage_type override is gated on build_type == 'Melee', not
    # on weapon_style, so it applies to this new style automatically — no
    # special-casing needed in the style branch itself.
    w1, w2, req2, w1_types, w2_types = solver.resolve_weapon_lists({
        "build_type": "Melee",
        "weapon_style": "Single Handed Weapon and Runearm",
        "weapon_damage_type": "Piercing",
    })
    assert w1_types == optimizer.weapon_types_for_damage_type("Piercing")
    assert w2 == ['rune arm', 'runearm']
    assert req2 is True


def test_weapon2_required_when_flag_set_even_with_no_priority_benefit():
    # Two distinct items — a single item can't legitimately occupy both
    # Weapon1 and Weapon2 at once (the model caps each item to one slot
    # total), same as real main-hand + offhand gear.
    items = [
        make_item("Main Hand Weapon", ["Weapon1"], [("melee power", "Enhancement", 1.0)]),
        make_item("Plain Runearm", ["Weapon2"], [("melee power", "Enhancement", 1.0)]),
    ]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    result, _log = solve(items, entries, require_weapon2=True)
    assert result["gearSet"].get("Weapon2"), "Weapon2 must be filled when require_weapon2 is set"


def test_weapon2_not_forced_when_flag_unset():
    # Without require_weapon2, create_model must not add the extra
    # "sum(Weapon2) == 1" constraint.
    items = [make_item("Plain Runearm", ["Weapon1", "Weapon2"], [])]
    entries = [PriorityEntry("melee power", 1, None, 0)]
    model = optimizer.create_model(items, {}, [], [], entries, 4, ["Weapon1", "Weapon2"])
    assert "Weapon2_Required" not in model.prob.constraints
    assert "Weapon1_Always_Required" in model.prob.constraints


# ---------------------------------------------------------------------------
# §7 — alternatives
# ---------------------------------------------------------------------------

def _alt_fixture():
    items = [
        make_item("Current Hat", ["Helmet"], [("A", "Enhancement", 5.0)]),
        make_item("Better Hat", ["Helmet"], [("A", "Enhancement", 9.0)]),
        make_item("Best Hat", ["Helmet"], [("A", "Enhancement", 12.0)]),
        make_item("Mid Hat", ["Helmet"], [("A", "Enhancement", 7.0)]),
        make_item("Weak Hat", ["Helmet"], [("A", "Enhancement", 2.0)]),
        make_item("Cape", ["Cloak"], [("A", "Stacking", 3.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    required = ["Helmet", "Cloak"]
    ub_sources = optimizer.build_ub_sources(items, {}, [], [], required)
    ub_all = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, False)
    weights = optimizer.compute_tier_weights(entries)
    return items, entries, required, ub_all, ub_nofil, weights


def test_ac33_count_is_clamped_and_ranks_are_dense():
    items, entries, required, ub_all, ub_nofil, weights = _alt_fixture()
    equipped = {"Helmet": "Current Hat", "Cloak": "Cape"}

    low = optimizer.find_slot_alternatives(items, {}, [], [], entries, required, equipped,
                                           {}, {}, "Helmet", "Current Hat", 1,
                                           ub_all, ub_nofil, weights)
    assert len(low["alternatives"]) == 3

    high = optimizer.find_slot_alternatives(items, {}, [], [], entries, required, equipped,
                                            {}, {}, "Helmet", "Current Hat", 99,
                                            ub_all, ub_nofil, weights)
    # only 4 other helmets exist
    assert len(high["alternatives"]) == 4
    assert [a["rank"] for a in high["alternatives"]] == [1, 2, 3, 4]


def test_ac32_ac34_ranking_is_lexicographic_and_excludes_equipped_items():
    items, entries, required, ub_all, ub_nofil, weights = _alt_fixture()
    equipped = {"Helmet": "Current Hat", "Cloak": "Cape"}
    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required, equipped,
                                           {}, {}, "Helmet", "Current Hat", 3,
                                           ub_all, ub_nofil, weights)
    assert res["success"] is True
    names = [a["itemName"] for a in res["alternatives"]]
    assert names == ["Best Hat", "Better Hat", "Mid Hat"]
    assert "Current Hat" not in names and "Cape" not in names

    scores = [tuple(a["tierScores"].get(str(t), 0.0) for t in range(1, 6))
              for a in res["alternatives"]]
    assert scores == sorted(scores, reverse=True)


def test_ac35_ring_slots_match_the_ring_item_pool():
    items = [
        make_item("Ring Of A", ["Ring"], [("A", "Enhancement", 9.0)]),
        make_item("Ring Of B", ["Ring"], [("A", "Enhancement", 4.0)]),
        make_item("Worn Ring", ["Ring"], [("A", "Enhancement", 1.0)]),
        make_item("Hat", ["Helmet"], [("A", "Enhancement", 2.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    required = ["Helmet", "Ring_1", "Ring_2"]
    ub_sources = optimizer.build_ub_sources(items, {}, [], [], required)
    ub_all = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, False)
    weights = optimizer.compute_tier_weights(entries)

    equipped = {"Ring_1": "Worn Ring", "Ring_2": "Ring Of B"}
    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required, equipped,
                                           {}, {}, "Ring_1", "Worn Ring", 3,
                                           ub_all, ub_nofil, weights)
    names = [a["itemName"] for a in res["alternatives"]]
    assert names == ["Ring Of A"]          # Ring Of B is equipped in Ring_2 (EC-15)
    assert "Hat" not in names


def test_ac36_cold_callable_baseline_is_populated():
    items, entries, required, ub_all, ub_nofil, weights = _alt_fixture()
    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required,
                                           {"Helmet": "Current Hat"}, {}, {},
                                           "Helmet", "Current Hat", 3,
                                           ub_all, ub_nofil, weights)
    assert res["baselineTierScores"]["1"] > 0


def test_ac37_slot_with_no_candidates_is_success_with_an_empty_list():
    items, entries, required, ub_all, ub_nofil, weights = _alt_fixture()
    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required,
                                           {"Cloak": "Cape"}, {}, {},
                                           "Cloak", "Cape", 5,
                                           ub_all, ub_nofil, weights)
    assert res["success"] is True
    assert res["alternatives"] == []
    assert res["baselineTierScores"]["1"] > 0
    assert not res.get("errorMessage")


def test_ac38_objective_score_is_the_documented_collapse():
    items, entries, required, ub_all, ub_nofil, weights = _alt_fixture()
    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required,
                                           {"Helmet": "Current Hat", "Cloak": "Cape"},
                                           {}, {}, "Helmet", "Current Hat", 3,
                                           ub_all, ub_nofil, weights)
    for alt in res["alternatives"]:
        expected = sum((10.0 ** (5 - t)) * alt["tierScores"].get(str(t), 0.0)
                       for t in range(1, 6))
        assert abs(alt["objectiveScore"] - expected) < 1e-6


def test_ac39_stat_deltas_are_zero_for_an_identical_candidate():
    items = [
        make_item("Current Hat", ["Helmet"], [("A", "Enhancement", 5.0)]),
        make_item("Clone Hat", ["Helmet"], [("A", "Enhancement", 5.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    required = ["Helmet"]
    ub_sources = optimizer.build_ub_sources(items, {}, [], [], required)
    ub_all = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, False)
    weights = optimizer.compute_tier_weights(entries)

    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required,
                                           {"Helmet": "Current Hat"}, {}, {},
                                           "Helmet", "Current Hat", 3,
                                           ub_all, ub_nofil, weights)
    assert res["alternatives"][0]["itemName"] == "Clone Hat"
    assert all(abs(v) < 1e-6 for v in res["alternatives"][0]["statDeltas"].values())


def test_ties_break_on_item_name_ascending_for_determinism():
    items = [
        make_item("Current Hat", ["Helmet"], [("A", "Enhancement", 5.0)]),
        make_item("Zeta Hat", ["Helmet"], [("A", "Enhancement", 9.0)]),
        make_item("Alpha Hat", ["Helmet"], [("A", "Enhancement", 9.0)]),
        make_item("Mid Hat", ["Helmet"], [("A", "Enhancement", 9.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    required = ["Helmet"]
    ub_sources = optimizer.build_ub_sources(items, {}, [], [], required)
    ub_all = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, False)
    weights = optimizer.compute_tier_weights(entries)

    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required,
                                           {"Helmet": "Current Hat"}, {}, {},
                                           "Helmet", "Current Hat", 3,
                                           ub_all, ub_nofil, weights)
    assert [a["itemName"] for a in res["alternatives"]] == \
        ["Alpha Hat", "Mid Hat", "Zeta Hat"]


def test_ec14_unknown_equipped_item_warns_and_is_ignored():
    items, entries, required, ub_all, ub_nofil, weights = _alt_fixture()
    res = optimizer.find_slot_alternatives(items, {}, [], [], entries, required,
                                           {"Helmet": "Current Hat", "Belt": "Ghost Belt"},
                                           {}, {}, "Helmet", "Current Hat", 3,
                                           ub_all, ub_nofil, weights)
    assert res["success"] is True
    assert any("Ghost Belt" in w and "was not found" in w for w in res["warnings"])


def test_ec16_same_item_in_two_slots_warns_and_is_excluded():
    items = [
        make_item("Twin Ring", ["Ring"], [("A", "Enhancement", 5.0)]),
        make_item("Other Ring", ["Ring"], [("A", "Enhancement", 6.0)]),
    ]
    entries = [PriorityEntry("A", 1, None, 0)]
    required = ["Ring_1", "Ring_2"]
    ub_sources = optimizer.build_ub_sources(items, {}, [], [], required)
    ub_all = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, True)
    ub_nofil = optimizer.compute_stat_upper_bounds(ub_sources, items, required, {}, False)
    weights = optimizer.compute_tier_weights(entries)

    res = optimizer.find_slot_alternatives(
        items, {}, [], [], entries, required,
        {"Ring_1": "Twin Ring", "Ring_2": "Twin Ring"}, {}, {},
        "Ring_1", "Twin Ring", 3, ub_all, ub_nofil, weights)
    assert any("more than one slot" in w for w in res["warnings"])
    assert [a["itemName"] for a in res["alternatives"]] == ["Other Ring"]


# ---------------------------------------------------------------------------
# Regression — calculate_only infeasibility bugs found against a real saved
# gearset (see docs/PHASE10_HANDOFF.md). All three compounded: a save with an
# augment in a Colorless slot, the same augment name in two slots, and a
# raid-item count over an (unrelated, search-time) raid_item_limit made
# calculate_only report "some locked items may be incompatible" even though
# every individual item/augment/filigree in the file was perfectly valid.
# ---------------------------------------------------------------------------

def make_augment(name, a_type, buffs):
    return {'name': name, 'type': a_type, 'buffs': list(buffs)}


def test_augment_fits_slot_colorless_rejects_standard_colors():
    # CORRECTION (confirmed by a real DDO player — this reverses what an
    # earlier version of this test asserted): a Colorless slot does NOT
    # accept the 8 standard elemental/celestial colors. A "Blue"/"Sun"/
    # "Moon"-typed augment (e.g. a Solar or Lunar gem) must NOT fit a plain
    # Colorless slot — this was the actual bug behind GitHub
    # jorgec/ddogearset#2 ("Lunar/Solar gems in colorless slots"), not
    # correct behavior. Colorless only accepts colorless-compatible
    # ("Diamond") augments, identified by name — see the next test.
    assert optimizer.augment_fits_slot('Blue', 'Colorless') is False
    assert optimizer.augment_fits_slot('Green', 'colorless') is False
    assert optimizer.augment_fits_slot('Sun', 'Colorless') is False
    assert optimizer.augment_fits_slot('Moon', 'Colorless') is False
    # Non-Colorless slots still require an actual color match.
    assert optimizer.augment_fits_slot('Blue', 'Red') is False
    assert optimizer.augment_fits_slot('Blue', 'Blue') is True


def test_augment_fits_slot_colorless_accepts_diamond_augments_by_name():
    # DDOBuilderV2 does not reliably encode "colorless-compatible" via
    # <Type> at all — e.g. "Diamond of Charisma" is typed "Blue" in the real
    # corpus, not "Colorless" or anything colorless-adjacent. The augment's
    # NAME is the only reliable signal (COLORLESS_AUGMENT_NAME_PATTERN),
    # confirmed against the real corpus (46 matches, every one independently
    # confirmed typed "Blue").
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Diamond of Charisma') is True
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Diamond of Exceptional Strength') is True
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Clearwater Diamond') is True
    assert optimizer.augment_fits_slot('Blue', 'Colorless', "The Master's Gift") is True
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Globe of Cursed Blood') is True
    assert optimizer.augment_fits_slot('Blue', 'Colorless', "Ravil's Book of Legendary Recipes") is True
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Set Augment: Anything') is True
    # An ordinary Blue-typed augment that ISN'T one of these named exceptions
    # still correctly does not fit Colorless.
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Sapphire of Charisma') is False
    assert optimizer.augment_fits_slot('Blue', 'Colorless', 'Diamondback Ring') is False
    # No name at all (the aug_name=None default) — still correctly rejected,
    # never a crash.
    assert optimizer.augment_fits_slot('Blue', 'Colorless') is False
    # A literal Type=="Colorless" augment (none exist today, but defensively
    # honored if the data ever adds one) fits regardless of name.
    assert optimizer.augment_fits_slot('Colorless', 'Colorless') is True


def test_augment_fits_slot_rejects_special_family_augments_in_colorless():
    # Regression: a dinosaur-artifact augment (type "IoD: Weapon: Fang Slot")
    # was incorrectly matching ANY Colorless slot on an ordinary, non-dino
    # item. Colorless only accepts colorless-compatible "Diamond" augments by
    # name (see above) — every other special slot family (dino IoD slots,
    # Cannith crafting slots, Dolorous/Melancholic/Miserable/Woeful named
    # slots, etc.) must still require an exact slot-type match and never fit
    # a plain Colorless slot.
    assert optimizer.augment_fits_slot('IoD: Weapon: Fang Slot', 'Colorless') is False
    assert optimizer.augment_fits_slot('IoD: Accessory: Artifact Scale Slot', 'Colorless') is False
    assert optimizer.augment_fits_slot('Cannith Ring Prefix', 'Colorless') is False
    assert optimizer.augment_fits_slot('Dolorous Slot (Accessory)', 'Colorless') is False
    # But a dino augment still fits its own matching slot exactly.
    assert optimizer.augment_fits_slot('IoD: Weapon: Fang Slot', 'IoD: Weapon: Fang Slot') is True


def test_augment_fits_slot_rejects_substring_false_positives():
    # Regression: a substring fallback (`slot_color in aug_type`) used to sit
    # under the exact-match check and let through real, confirmed-via-corpus
    # false positives — none of these pairings are legitimate DDO rules, they
    # were purely accidental string containment.
    # "red" is a substring of "incREDible" — completely unrelated augment.
    assert optimizer.augment_fits_slot('Incredible Potential', 'Red') is False
    # A plain color slot must not accept an unrelated crafting system's augment
    # just because its name contains the color word.
    assert optimizer.augment_fits_slot('Greensteel Weapon Tier 1', 'Green') is False
    # Heroic-tier slot must not accept its Legendary-tier counterpart augment —
    # these are different, much stronger raid-locked items.
    assert optimizer.augment_fits_slot('Legendary Alchemical Tier 1', 'Alchemical Tier 1') is False
    assert optimizer.augment_fits_slot('Legendary Slavelords Extra', 'Slavelords Extra') is False
    # A generic "Set Bonus" slot must not accept augments from unrelated named
    # systems just because their type string contains "Set Bonus".
    assert optimizer.augment_fits_slot('Legendary Slavelords Set Bonus', 'Set Bonus') is False
    assert optimizer.augment_fits_slot('IoD: Set Bonus Slot', 'Set Bonus') is False
    # A generic "Variant" slot must not accept an armor-type-specific Shadow
    # variant meant only for a different armor weight.
    assert optimizer.augment_fits_slot('Shadow Heavy Variant', 'Variant') is False


def test_calculate_only_credits_pre_filled_augment_in_a_colorless_slot():
    # Fixture uses a real colorless-compatible ("Diamond") augment name —
    # DDOBuilderV2 types these "Blue" in the data (confirmed against the real
    # corpus), which is exactly why COLORLESS_AUGMENT_NAME_PATTERN matches by
    # name rather than trusting <Type> for Colorless-slot fit.
    item = make_item("Festive Hat", ["Helmet"], [], augments=["Colorless"])
    augments = [make_augment("Diamond of Charisma", "Blue", [("Charisma", "Festive", 2.0)])]
    entries = [PriorityEntry("Charisma", 1, None, 0)]

    result, _ = solve(
        [item], entries, augments=augments,
        pre_equipped={"Helmet": "Festive Hat"},
        pre_filled_augments={"Helmet": {"Colorless": "Diamond of Charisma"}},
        mode="calculate")

    assert result.get("errorMessage") is None
    assert result["realizedStats"]["Charisma"] == 2.0


def test_calculate_only_allows_the_same_augment_name_in_two_slots():
    # Augments like Solar/Lunar Gems are craftable/purchasable in multiple
    # copies — no bind-unique restriction — so the same augment name can
    # legally appear in two different slots of a saved gearset.
    armor = make_item("Plate", ["Armor"], [], augments=["Sun"])
    cloak = make_item("Cape", ["Cloak"], [], augments=["Sun"])
    augments = [make_augment("Solar Gem of Charisma", "Sun", [("Charisma", "Stacking", 4.0)])]
    entries = [PriorityEntry("Charisma", 1, None, 0)]

    result, _ = solve(
        [armor, cloak], entries, augments=augments,
        pre_equipped={"Armor": "Plate", "Cloak": "Cape"},
        pre_filled_augments={
            "Armor": {"Sun": "Solar Gem of Charisma"},
            "Cloak": {"Sun": "Solar Gem of Charisma"},
        },
        mode="calculate")

    # Both Artifact/Insightful-style non-stacking bonuses would collapse to
    # the max of the two (correct DDO rule) and wouldn't prove the fix, so
    # this augment uses a Stacking bonus type: both copies must be credited.
    assert result.get("errorMessage") is None
    assert result["realizedStats"]["Charisma"] == 8.0


def test_calculate_only_ignores_raid_item_limit():
    raid_item = make_item("Raid Trinket", ["Trinket"], [("Charisma", "Stacking", 5.0)])
    raid_item["is_raid"] = True
    other_raid_item = make_item("Raid Belt", ["Belt"], [("Charisma", "Stacking", 5.0)])
    other_raid_item["is_raid"] = True
    entries = [PriorityEntry("Charisma", 1, None, 0)]

    result, _ = solve(
        [raid_item, other_raid_item], entries,
        pre_equipped={"Trinket": "Raid Trinket", "Belt": "Raid Belt"},
        raid_item_limit=1, mode="calculate")

    assert result.get("errorMessage") is None
    assert result["realizedStats"]["Charisma"] == 10.0


def test_optimize_mode_still_enforces_raid_item_limit():
    # The calculate_only bypass above must not weaken the search-mode cap.
    raid_item = make_item("Raid Trinket", ["Trinket"], [("Charisma", "Insightful", 5.0)])
    raid_item["is_raid"] = True
    other_raid_item = make_item("Raid Belt", ["Belt"], [("Charisma", "Insightful", 5.0)])
    other_raid_item["is_raid"] = True
    entries = [PriorityEntry("Charisma", 1, None, 0)]

    result, _ = solve([raid_item, other_raid_item], entries, raid_item_limit=1)

    assert result.get("errorMessage") is None
    equipped_raid = sum(1 for name in result["gearSet"].values()
                        if name in ("Raid Trinket", "Raid Belt"))
    assert equipped_raid <= 1


# ---------------------------------------------------------------------------
# docs/TROVE_INVENTORY_IMPORT_SPEC.md — owned_names item/augment pool filter
#
# Unlike the rest of this file, these exercise parse_items/parse_augments
# directly against the real DDOBuilderV2 checkout rather than synthetic
# make_item fixtures — owned_names is applied inside the XML-walking loop
# itself (see optimizer.py), so a synthetic in-memory item list can't
# exercise the actual code path. Skipped cleanly if DDOBuilderV2 hasn't been
# fetched yet (e.g. a CI environment, or a fresh checkout before first run)
# rather than failing the whole suite over missing external data.
# ---------------------------------------------------------------------------

_DDOBUILDER_DATA_DIR = "DDOBuilderV2/Output/DataFiles"
_has_real_ddobuilder_data = os.path.isdir(_DDOBUILDER_DATA_DIR)
_skip_without_real_data = pytest.mark.skipif(
    not _has_real_ddobuilder_data,
    reason="DDOBuilderV2 not fetched in this environment (see ensureDDOBuilderData in app.go)")


@_skip_without_real_data
def test_parse_items_owned_names_none_is_unrestricted():
    items = optimizer.parse_items(
        _DDOBUILDER_DATA_DIR, 34, [], "", [], [], True, "", owned_names=None)
    items_default = optimizer.parse_items(
        _DDOBUILDER_DATA_DIR, 34, [], "", [], [], True, "")
    assert len(items) == len(items_default)


@_skip_without_real_data
def test_parse_items_owned_names_filters_to_exact_matches():
    owned = {"Legendary Keylock Ring"}
    items = optimizer.parse_items(
        _DDOBUILDER_DATA_DIR, 34, [], "", [], [], True, "", owned_names=owned)
    names = {i["name"] for i in items}
    assert names == owned, f"expected exactly {owned}, got {names}"


@_skip_without_real_data
def test_parse_items_owned_names_never_drops_pre_equipped():
    owned = {"Some Other Item"}
    items = optimizer.parse_items(
        _DDOBUILDER_DATA_DIR, 34, [], "", [], [], True, "",
        pre_equipped_names=["Legendary Keylock Ring"], owned_names=owned)
    names = {i["name"] for i in items}
    assert "Legendary Keylock Ring" in names


@_skip_without_real_data
def test_parse_augments_owned_names_filters_to_exact_matches():
    owned = {"Solar Gem of Healing Amplification (Legendary)"}
    augments = optimizer.parse_augments(
        _DDOBUILDER_DATA_DIR, 34, ["Healing Amplification"], owned_names=owned)
    names = {a["name"] for a in augments}
    assert names == owned, f"expected exactly {owned}, got {names}"


@_skip_without_real_data
def test_parse_augments_never_drops_pre_filled_with_no_priority_matching_buffs():
    # Regression: a pre-filled augment whose only effects fall outside the
    # user's CURRENT stat_priorities (empty here, so nothing can match) used
    # to be silently dropped from the pool entirely — breaking create_model's
    # aggregate sum(y) == total_pre_filled_augments constraint and turning a
    # calculate-only solve infeasible. It must still appear (with empty
    # buffs) when pre-filled, and must NOT appear at all when it isn't.
    name = "Solar Gem of Healing Amplification (Legendary)"

    not_pre_filled = optimizer.parse_augments(_DDOBUILDER_DATA_DIR, 34, [])
    assert name not in {a["name"] for a in not_pre_filled}

    pre_filled = optimizer.parse_augments(
        _DDOBUILDER_DATA_DIR, 34, [], pre_filled_augment_names=[name])
    matches = [a for a in pre_filled if a["name"] == name]
    assert len(matches) == 1, f"expected pre-filled augment to survive with empty buffs, got {matches}"
    assert matches[0]["buffs"] == []
