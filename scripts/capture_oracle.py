#!/usr/bin/env python3
"""Capture the outgoing `mode: "calculate"` implementation's answers as the
differential oracle for the 0.5.0 recalculation work.

See docs/0.5.0/01_RECALC_SPEC_AND_PHASED_PLAN.md Phase 0. This script exists for
exactly one reason: `mode: "calculate"` is deleted in Phase 6, and once it is
gone there is no way to ask the current implementation what a given gearset
totals to. Every saved `.ddogearset` is replayed through it here, and the answer
is checked in.

Only 5 of the 14 real saved files carry trustworthy stored stats (v1.2, produced
by the real solver); the other 9 are v1.3 files written by the discarded Go
implementation. Their *stored stats* are worthless but their *gear names* are
real, so replaying all of them turns a corpus of one delta-free reference into
thirteen.

Each output file records the exact payload that produced it, so Phase 4 can
replay the identical gearset through `recalculate` and diff the two.
"""

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEARSETS = REPO / "gearsets"
OUT_DIR = REPO / "python" / "tests" / "fixtures" / "oracle"
SOLVER = REPO / "python" / "solver.py"
PYTHON = REPO / "python" / ".venv" / "bin" / "python"

# Search restrictions are captured verbatim from each file's own config. That is
# deliberate: this records what the OUTGOING implementation answered, including
# any effect its restrictions had. Phase 4 compares restriction-free
# `recalculate` against it, and a divergence caused by a restriction is exactly
# the finding the whole project exists to surface.


def reconstruct_gearset(data):
    """Return (pre_equipped, pre_filled_augments, pre_filled_filigrees, notes).

    A gearset can live in `config` (the user pinned it), in `result` (a solve
    that was saved without the picks ever being written back to config), or in
    both. Real files exist in every combination -- see the plan's §2.2 survey.
    """
    cfg = data.get("config") or {}
    res = data.get("result") or {}
    notes = []

    pre_equipped = dict(cfg.get("pre_equipped") or {})
    if not pre_equipped and (res.get("gearSet") or {}):
        pre_equipped = dict(res["gearSet"])
        notes.append("pre_equipped reconstructed from result.gearSet")

    augments = copy.deepcopy(cfg.get("pre_filled_augments") or {})
    if not augments:
        derived = {}
        for slot, sdata in (res.get("slots") or {}).items():
            for aug in sdata.get("augments") or []:
                color, name = aug.get("color"), aug.get("name")
                if color and name:
                    derived.setdefault(slot, {})[color] = name
        if derived:
            augments = derived
            notes.append("pre_filled_augments reconstructed from result.slots")

    filigrees = copy.deepcopy(cfg.get("pre_filled_filigrees") or {})
    if not any(filigrees.get(k) for k in ("weapon", "artifact")):
        rf = res.get("filigrees") or {}
        if rf.get("weapon") or rf.get("artifact"):
            filigrees = {"weapon": list(rf.get("weapon") or []),
                         "artifact": list(rf.get("artifact") or [])}
            notes.append("pre_filled_filigrees reconstructed from result.filigrees")

    return pre_equipped, augments, filigrees, notes


def stored_reference(data):
    """The file's own saved result, kept alongside the fresh capture.

    For v1.2 files this is real solver output and a second (older) oracle, worth
    a justified-delta comparison. For v1.3 files it was produced by the discarded
    Go implementation and is recorded as untrustworthy so no test ever asserts on
    it by accident.
    """
    res = data.get("result") or {}
    return {
        "trustworthy": data.get("version") == "1.2",
        "why": ("real solver output" if data.get("version") == "1.2"
                else "written by the discarded 0.5.0 Go implementation - "
                     "gear names are real, stats are not"),
        "realizedStats": res.get("realizedStats"),
        "activeSets": res.get("activeSets"),
    }


def diagnose(payload):
    """Why a gearset the user legitimately owns fails today's `calculate` mode.

    Every entry here is a SEARCH rule reaching into evaluation, which is the
    defect the 0.5.0 recalculation work exists to remove. Recorded on the fixture
    so Phase 4 asserts the specific thing that used to break, not just "it works
    now".
    """
    found = []
    fils = payload.get("pre_filled_filigrees") or {}

    for bucket in ("weapon", "artifact"):
        entries = fils.get(bucket) or []
        non_empty = [f for f in entries if f]

        if len(entries) != len(non_empty):
            found.append({
                "class": "empty-filigree-entry",
                "bucket": bucket,
                "detail": f"{len(entries) - len(non_empty)} empty-string entry/ies",
                "mechanism": "corrupted saved data counted by the "
                             "sum(f) == total constraint (optimizer.py:1826)",
            })

        if len(non_empty) != len(set(non_empty)):
            dupes = sorted({f for f in non_empty if non_empty.count(f) > 1})
            found.append({
                "class": "duplicate-filigree-name",
                "bucket": bucket,
                "detail": f"{len(non_empty)} non-empty entries, "
                          f"{len(set(non_empty))} distinct: {dupes}",
                "mechanism": "sum(f) == count-of-non-empty, but pins are per "
                             "distinct name - unsatisfiable on arrival",
            })

        bases = {}
        for f in non_empty:
            bases.setdefault(f.split(":")[0].strip() if ":" in f else f, set()).add(f)
        collisions = {b: sorted(v) for b, v in bases.items() if len(v) > 1}
        if collisions:
            found.append({
                "class": "base-name-collision",
                "bucket": bucket,
                "detail": collisions,
                "mechanism": "optimizer.py:1817 constrains sum(f) <= 1 per "
                             "base_name per bucket - a SEARCH heuristic ('only "
                             "one variant of a filigree'), applied to a gearset "
                             "the user actually has equipped",
            })

    if payload.get("is_dino_artifact") and not (
            payload.get("reserved_minor_artifact_slot") or "").strip():
        found.append({
            "class": "dino-fragment",
            "detail": "reserved_minor_artifact_slot is empty with "
                      "is_dino_artifact true -> the ' (dino)' fragment",
            "mechanism": "solver.py:500 concatenates a slot name that is not "
                         "there; parse_items then force-filters minor artifacts",
        })

    for key in ("armor_restriction", "excluded_packs", "owned_item_names",
                "weapon_style", "raid_item_limit"):
        val = payload.get(key)
        if val not in (None, "", [], -1):
            found.append({
                "class": "search-restriction-present",
                "detail": f"{key} = {val!r}",
                "mechanism": "shapes the candidate pool during an evaluation of "
                             "gear the user already owns",
            })

    return found


def build_payload(data):
    cfg = copy.deepcopy(data.get("config") or {})
    pre_equipped, augments, filigrees, notes = reconstruct_gearset(data)
    cfg["pre_equipped"] = pre_equipped
    cfg["pre_filled_augments"] = augments
    cfg["pre_filled_filigrees"] = filigrees
    cfg["mode"] = "calculate"
    cfg.pop("calculate_only", None)
    return cfg, notes


def run_solver(payload, workdir, env):
    """Run solver.py in its own directory (it writes gearset_output.txt to cwd)."""
    # Absolute: solver.py is invoked with cwd=workdir (it writes
    # gearset_output.txt to cwd), so a relative payload path would not resolve.
    payload_path = (workdir / "payload.json").resolve()
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(json.dumps(payload))
    t0 = time.time()
    proc = subprocess.run(
        [str(PYTHON), str(SOLVER), str(payload_path)],
        cwd=str(workdir), env=env, capture_output=True, text=True, timeout=900)
    elapsed = round(time.time() - t0, 1)

    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("JSON_RESULT:"):
            result = json.loads(line[len("JSON_RESULT:"):])
    return result, elapsed, proc.returncode, proc.stderr[-2000:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="substring filter on filename")
    ap.add_argument("--force", action="store_true",
                    help="allow a failed capture to overwrite a fixture that "
                         "currently holds a successful one (see the guard in "
                         "the failure branch below)")
    ap.add_argument("--app-version", default="0.4.4",
                    help="version stamp recorded in each capture")
    args = ap.parse_args()

    if not PYTHON.exists():
        sys.exit(f"python venv not found at {PYTHON}")

    env = dict(os.environ)
    bundle = REPO / "bundled" / "darwin-arm64"
    # DDO_CATALOG_DB, not the DDO_DATA_PATH this used to set: 0.5.0 Phase 6
    # switched solver.py to read catalog.db and stopped reading DDO_DATA_PATH
    # entirely, which left this script silently unable to capture anything —
    # every run failed with "Catalog not found" and, before the guard below
    # existed, wrote that failure over the fixture it was replaying.
    catalog = Path(os.environ.get("DDO_CATALOG_DB") or (bundle / "catalog.db"))
    if not catalog.exists():
        sys.exit(f"no catalog at {catalog}; build one with `python -m etl` "
                 "or set DDO_CATALOG_DB")
    env["DDO_CATALOG_DB"] = str(catalog.resolve())
    if (bundle / "glpsol").exists():
        env["GLPSOL_PATH"] = str(bundle / "glpsol")
        env["DYLD_LIBRARY_PATH"] = str(bundle)
    env["PYTHONUNBUFFERED"] = "1"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    workdir = OUT_DIR.parent / ".capture_tmp"
    workdir.mkdir(exist_ok=True)

    files = sorted(GEARSETS.glob("*.ddogearset"))
    if args.only:
        files = [f for f in files if args.only in f.name]

    captured = skipped = failed = 0
    for path in files:
        data = json.loads(path.read_text())
        payload, notes = build_payload(data)
        stem = path.stem
        out_path = OUT_DIR / f"{stem}.oracle.json"
        existing_result = None
        if out_path.exists():
            try:
                existing_result = json.loads(out_path.read_text()).get("result")
            except (ValueError, OSError):
                existing_result = None

        if not payload["pre_equipped"]:
            record = {
                "source_file": path.name,
                "source_version": data.get("version"),
                "source_app_version": data.get("app_version"),
                "captured_with_app_version": args.app_version,
                "capture_mode": "calculate",
                "stored_reference": stored_reference(data),
                "empty_gearset": True,
                "notes": notes + ["no equipped gear; retained as the empty-gearset "
                                  "regression fixture (plan §17)"],
                "payload": payload,
                "result": None,
            }
            out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(f"  SKIP  {stem[:52]:54s} empty gearset -> fixture only")
            skipped += 1
            continue

        print(f"  RUN   {stem[:52]:54s} {len(payload['pre_equipped']):2d} slots ...",
              end="", flush=True)
        result, elapsed, rc, stderr = run_solver(payload, workdir, env)

        if not result or result.get("success") is False:
            msg = (result or {}).get("errorMessage") or f"rc={rc} {stderr[-200:]}"
            print(f" FAILED after {elapsed}s: {msg}")
            failed += 1
            # NEVER let a failure destroy a good capture. These fixtures cannot
            # be regenerated once mode:"calculate" is deleted (0.5.1 Phase 5),
            # and a failed run is far more often a broken environment than a
            # real finding — a stale env var here silently replaced a
            # successful capture with `capture_failed: true` on its first run
            # after Phase 6. Recording a genuine new failure is what --force is
            # for, and it should be a decision, not a side effect.
            if existing_result and not args.force:
                print(f"        REFUSING to overwrite {out_path.name}, which "
                      "holds a successful capture. Re-run with --force if this "
                      "failure is the thing you meant to record.")
                continue
            record = {
                "source_file": path.name,
                "source_version": data.get("version"),
                "source_app_version": data.get("app_version"),
                "captured_with_app_version": args.app_version,
                "capture_mode": "calculate",
                "stored_reference": stored_reference(data),
                "capture_failed": True,
                "capture_error": msg,
                "diagnosis": diagnose(payload),
                "notes": notes,
                "payload": payload,
                "result": None,
            }
            out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            continue

        record = {
            "source_file": path.name,
            "source_version": data.get("version"),
            "source_app_version": data.get("app_version"),
            "captured_with_app_version": args.app_version,
            "capture_mode": "calculate",
            "stored_reference": stored_reference(data),
            "capture_seconds": elapsed,
            "notes": notes,
            "payload": payload,
            "result": result,
        }
        out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f" ok in {elapsed}s -> {len(result.get('realizedStats') or {})} stats, "
              f"{len(result.get('activeSets') or [])} sets")
        captured += 1

    print(f"\ncaptured={captured} skipped={skipped} failed={failed} -> {OUT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
