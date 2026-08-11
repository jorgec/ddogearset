"""The differential oracle, actually executed.

0.5.1 Phase 0 — docs/0.5.1/00_APP_DB_START_HERE.md.

`python/tests/fixtures/oracle/*.oracle.json` holds 14 real saved gearsets, each
with the exact payload that produced it and the answer app 0.4.4's
`mode: "calculate"` gave. They were captured because **that mode is deleted in
0.5.1 Phase 5**, and once it is gone nothing can ask the old implementation what
a gearset totals to ever again.

Until now that was a claim about files on disk. `scripts/check_oracle.sh` checks
the fixtures are present and internally consistent; `scripts/capture_oracle.py`
replays but only to *capture* — it has no compare mode. So "the oracle
reproduces" had never been run. This module is the missing half, and it is the
only thing that will stand between the old numbers and the new when `calculate`
goes away.

It replays every fixture through the CURRENT implementation and demands the
recorded answer back. When Phase 4 lands `mode: "recalculate"`, the same
comparison points at that mode instead and the fixtures do not change.

**Cost.** 12 real solves, ~2-6 s each, run once per session and in parallel
(see `oracle_replays`). Roughly 10 s of wall clock added to the suite. That is
deliberate: a differential nobody runs is not a differential.
"""

import copy
import json
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ORACLE_DIR = REPO / "python" / "tests" / "fixtures" / "oracle"
SOLVER = REPO / "python" / "solver.py"
PYTHON = REPO / "python" / ".venv" / "bin" / "python"

# One solve holds the whole catalog in memory; four at once is comfortable and
# still cuts the wall clock by roughly four.
MAX_PARALLEL_SOLVES = 4
SOLVE_TIMEOUT_SECONDS = 300

# Wall-clock measurements, recorded by the solver for the UI's benefit. They
# differ on every run by definition and say nothing about correctness.
TIMING_KEYS = ("elapsedSeconds", "totalElapsedSeconds", "budgetSeconds")

# Lists whose ORDER carries no meaning. Compared as multisets; everything else
# is compared in order.
#
# This list is short, closed, and justified one entry at a time on purpose. The
# tempting shortcut — sort every list before comparing — would also hide a
# genuine content change in an ordered list, which is most of what this module
# is for.
#
# Why any of them are here: the 0.5.0 catalog migration reordered exactly these
# four and nothing else. Verified across all 12 replayable fixtures, with every
# value identical and the new order stable across three PYTHONHASHSEEDs. Python
# now iterates SQL rows where it used to iterate XML files, so a one-time,
# deterministic reshuffle is expected. The parser snapshot could not catch it
# (it canonicalises before hashing) and the oracle had never been executed, so
# it went unnoticed through all of 0.5.0.
#
# Each is genuinely unordered in the domain, not merely observed to vary:
#   activeSets            a SET of active set-tiers — app.db's run_active_set
#                         primary key says so (schema §5.4)
#   allEffects.<stat>     the contributions to one stat; the total is what is
#                         asserted, and it is a dict value away in realizedStats
#   filigrees.<bucket>    bucket membership. Filigree "position" is storage, not
#                         semantics — no slot index changes what a filigree does
#   slots.<slot>.filigrees  the same membership, per slot
#
# `slots.<slot>.augments` is deliberately NOT here: it did not reorder, so if it
# ever does, that is a signal worth failing on.
UNORDERED_PATHS = (
    ("activeSets",),
    ("allEffects", "*"),
    ("filigrees", "*"),
    ("slots", "*", "filigrees"),
)


def _is_unordered(path: tuple) -> bool:
    for pattern in UNORDERED_PATHS:
        if len(pattern) != len(path):
            continue
        if all(p == "*" or p == actual for p, actual in zip(pattern, path)):
            return True
    return False


def _bundle_dir() -> Path:
    """The bundled/<platform>/ directory for THIS machine.

    The catalog and glpsol both live here. Named per-platform because neither
    can be cross-built (see build-mac.sh's header), so only one of these
    directories is ever populated on a given machine.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64",
            "aarch64": "arm64"}.get(machine, machine)
    name = {"darwin": f"darwin-{arch}", "linux": f"linux-{arch}",
            "windows": f"windows-{arch}"}.get(system, f"{system}-{arch}")
    return REPO / "bundled" / name


def _catalog_path() -> Path:
    """The catalog to replay against.

    DDO_CATALOG_DB wins, matching the convention app.go and catalog_source.py
    already share, so this can be pointed at a freshly built catalog without
    editing anything.
    """
    override = os.environ.get("DDO_CATALOG_DB")
    if override:
        return Path(override)
    return _bundle_dir() / "catalog.db"


def _solver_env() -> dict:
    env = dict(os.environ)
    env["DDO_CATALOG_DB"] = str(_catalog_path().resolve())
    env["PYTHONUNBUFFERED"] = "1"
    bundle = _bundle_dir()
    # optimizer.py's _glpk_cmd() reads GLPSOL_PATH; without it the solver looks
    # for glpsol on PATH, which is fine on a dev box that installed GLPK and
    # not fine anywhere else.
    if (bundle / "glpsol").exists():
        env["GLPSOL_PATH"] = str(bundle / "glpsol")
        env["DYLD_LIBRARY_PATH"] = str(bundle)
        env["LD_LIBRARY_PATH"] = str(bundle)
    return env


def _fixtures() -> list:
    return sorted(ORACLE_DIR.glob("*.oracle.json"))


def _fixture_id(path: Path) -> str:
    return path.name[: -len(".oracle.json")]


def _run_solver(payload: dict, workdir: Path, env: dict):
    """Returns (result_or_None, error_message_or_None).

    Each replay gets its OWN working directory: solver.py writes
    gearset_output.txt and solver_progress.log relative to cwd, and four
    parallel replays sharing one directory would overwrite each other's output
    while the runs are still in flight.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    payload_path = (workdir / "payload.json").resolve()
    payload_path.write_text(json.dumps(payload))
    try:
        proc = subprocess.run(
            [str(PYTHON), str(SOLVER), str(payload_path)],
            cwd=str(workdir), env=env, capture_output=True, text=True,
            timeout=SOLVE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {SOLVE_TIMEOUT_SECONDS}s"

    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("JSON_RESULT:"):
            result = json.loads(line[len("JSON_RESULT:"):])

    if result is None:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        return None, f"no JSON_RESULT (rc={proc.returncode}): {tail}"
    if result.get("success") is False:
        return None, result.get("errorMessage") or "solver reported failure"
    return result, None


def canonical(value, path=()):
    """The form two results are compared in: timings dropped, and the four
    documented unordered lists sorted. Every other list keeps its order."""
    if isinstance(value, dict):
        return {k: canonical(v, path + (k,)) for k, v in value.items()
                if k not in TIMING_KEYS}
    if isinstance(value, list):
        items = [canonical(v, path) for v in value]
        if _is_unordered(path):
            return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
        return items
    return value


@pytest.fixture(scope="session")
def oracle_replays(tmp_path_factory):
    """Every fixture replayed once, in parallel, for the whole session.

    Session-scoped on purpose: the per-fixture tests below exist so a failure
    names the gearset that broke, not so the solver runs 12 more times.
    """
    catalog = _catalog_path()
    if not catalog.exists():
        # Deliberately not a skip. A differential that quietly opts out when its
        # baseline is missing is the failure mode this module was written to
        # end — it would report green for the rest of 0.5.1 and nobody would
        # notice until `calculate` was already deleted.
        pytest.fail(
            f"No catalog at {catalog}. The oracle differential cannot run "
            f"without one, and it must not pass without running. Build one "
            f"(`python -m etl --out {catalog}`) or set DDO_CATALOG_DB.")
    if not PYTHON.exists():
        pytest.fail(f"No venv interpreter at {PYTHON}; cannot replay the oracle.")

    env = _solver_env()
    root = tmp_path_factory.mktemp("oracle")

    jobs = []
    for path in _fixtures():
        data = json.loads(path.read_text())
        if data.get("empty_gearset"):
            continue  # nothing to solve; asserted separately below
        jobs.append((_fixture_id(path), data["payload"]))

    def replay(job):
        name, payload = job
        result, error = _run_solver(copy.deepcopy(payload), root / name, env)
        return name, (result, error)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SOLVES) as pool:
        return dict(pool.map(replay, jobs))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.mark.parametrize("fixture_path", _fixtures(), ids=_fixture_id)
def test_oracle_fixture_reproduces(fixture_path, oracle_replays):
    """Replaying a fixture's own payload must return the answer it recorded.

    This is the whole point of the corpus. Any divergence here is either a real
    regression or a deliberate change that needs the fixtures re-captured — and
    re-capture is only possible while `mode: "calculate"` still exists.
    """
    data = _load(fixture_path)
    name = _fixture_id(fixture_path)

    if data.get("empty_gearset"):
        # Retained as the empty-gearset regression fixture. There is nothing to
        # replay, but the fixture must keep saying so — if a future capture
        # silently gives it gear, the corpus has drifted.
        assert not data["payload"].get("pre_equipped"), (
            f"{name} is recorded as the empty-gearset fixture but its payload "
            "now carries equipped items")
        assert data["result"] is None
        return

    result, error = oracle_replays[name]

    if data.get("capture_failed"):
        # The headline fixture: today's `calculate` REFUSES this gearset (see
        # known_deltas.yaml `unevaluatable_today` — optimizer.py:1817's
        # one-filigree-per-base-name rule, a SEARCH heuristic reaching into an
        # evaluation of gear the user actually owns).
        #
        # Asserting the failure is not celebrating it. It pins the exact
        # behaviour Phase 4 has to change, so that when `recalculate` returns
        # numbers for this gearset, this test fails and has to be rewritten
        # deliberately rather than passing by accident.
        assert result is None, (
            f"{name} now evaluates, but the fixture records it as unevaluatable.\n"
            "If this is Phase 4 landing recalculate: that is the goal — move "
            "this fixture out of `capture_failed` and assert the numbers plus "
            "the expected warnings instead.")
        assert error, "expected an error message for a capture_failed fixture"
        return

    assert error is None, f"{name} failed to replay: {error}"
    assert canonical(result) == canonical(data["result"]), (
        f"{name} no longer reproduces its recorded answer")


def test_the_corpus_is_intact():
    """Guards the shape of the corpus itself.

    Every assertion above is per-fixture, so a fixture that simply vanished
    would take its test with it and the suite would still be green.
    """
    fixtures = _fixtures()
    assert len(fixtures) == 14, (
        f"expected 14 oracle fixtures, found {len(fixtures)}. These cannot be "
        "regenerated once mode:\"calculate\" is deleted — see this module's "
        "docstring before accepting a new count.")

    kinds = {"captured": 0, "empty": 0, "failed": 0}
    for path in fixtures:
        data = _load(path)
        assert data.get("payload"), f"{path.name} has no payload to replay"
        if data.get("empty_gearset"):
            kinds["empty"] += 1
        elif data.get("capture_failed"):
            kinds["failed"] += 1
        else:
            kinds["captured"] += 1
            assert data.get("result"), f"{path.name} is neither failed nor has a result"
    assert kinds == {"captured": 12, "empty": 1, "failed": 1}, kinds


SAMPLE = "Test_CasterDualCaster_20260810053044"


def _sample_result() -> dict:
    return _load(ORACLE_DIR / f"{SAMPLE}.oracle.json")["result"]


def test_the_comparison_still_compares_something():
    """A guard against the differential going hollow.

    If `canonical` ever broadened to the point of comparing empty dicts, every
    fixture would pass and mean nothing.
    """
    canon = canonical(_sample_result())
    for key in ("gearSet", "realizedStats", "activeSets", "allEffects", "slots"):
        assert canon.get(key), f"{key} vanished from the comparison"
    assert "totalElapsedSeconds" not in canon["tierReport"]
    assert len(canon["realizedStats"]) == 12


def test_a_changed_number_fails_the_comparison():
    """The assertion that matters: a moved value must be caught.

    Written out explicitly because every other test here passes when the code
    is correct, and a comparison that cannot fail looks exactly the same.
    """
    original = _sample_result()
    mutated = copy.deepcopy(original)
    mutated["realizedStats"]["force spellpower"] += 1.0
    assert canonical(mutated) != canonical(original)

    mutated = copy.deepcopy(original)
    mutated["gearSet"]["Helmet"] = "Some Other Helmet"
    assert canonical(mutated) != canonical(original)

    # A dropped contribution, even though the stat total is untouched.
    mutated = copy.deepcopy(original)
    mutated["allEffects"]["force spellpower"].pop()
    assert canonical(mutated) != canonical(original)


def test_only_the_documented_lists_may_be_reordered():
    """Pins the ordering allowance so it cannot widen unnoticed.

    Reordering one of the four unordered lists must pass; reordering ANY other
    list must fail. Without this, someone adding a path to UNORDERED_PATHS to
    make a failure go away would silently weaken every assertion above.
    """
    original = _sample_result()

    for path_desc, mutate in (
        ("activeSets", lambda r: r["activeSets"].reverse()),
        ("allEffects.<stat>", lambda r: r["allEffects"]["force spellpower"].reverse()),
        ("filigrees.weapon", lambda r: r["filigrees"]["weapon"].reverse()),
    ):
        mutated = copy.deepcopy(original)
        mutate(mutated)
        assert canonical(mutated) == canonical(original), (
            f"{path_desc} is documented as unordered but reordering it failed")

    # ...and an ordered one still is. unmatchedPriorities is a list the user
    # sees in the order the solver reports it.
    mutated = copy.deepcopy(original)
    assert len(mutated["unmatchedPriorities"]) > 1, "sample no longer exercises this"
    mutated["unmatchedPriorities"].reverse()
    assert canonical(mutated) != canonical(original), (
        "reordering unmatchedPriorities was tolerated — the ordering allowance "
        "has widened beyond UNORDERED_PATHS")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
