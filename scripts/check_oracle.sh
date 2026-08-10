#!/usr/bin/env bash
# Phase 0 gate — docs/0.5.0/00_ETL_START_HERE.md §8
#
# The oracle cannot be regenerated once mode:"calculate" is deleted in 0.5.1.
# It is also the baseline the ETL's catalog must reproduce (0.5.0 Phase 4). This script asserts it is present,
# complete, and internally consistent, so its loss is a loud failure rather than
# a quiet one.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=python/.venv/bin/python
[ -x "$PY" ] || PY=python3

exec "$PY" - <<'PYCODE'
import json
import sys
from pathlib import Path

ORACLE = Path("python/tests/fixtures/oracle")
DELTAS = Path("python/tests/fixtures/known_deltas.yaml")

fail = []
def check(ok, msg):
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        fail.append(msg)

print("Phase 0 gate — differential oracle\n")

check(ORACLE.is_dir(), f"{ORACLE} exists")
check(DELTAS.is_file(), f"{DELTAS} exists")
if fail:
    sys.exit(1)

records = {}
for path in sorted(ORACLE.glob("*.oracle.json")):
    records[path.stem.replace(".oracle", "")] = json.loads(path.read_text())

check(len(records) == 14, f"14 fixtures tracked (found {len(records)})")

missing_version = [k for k, r in records.items()
                   if not r.get("source_version") or not r.get("captured_with_app_version")]
check(not missing_version, f"every fixture is version-tagged ({missing_version or 'ok'})")

missing_payload = [k for k, r in records.items() if not r.get("payload")]
check(not missing_payload,
      f"every fixture carries a replayable payload ({missing_payload or 'ok'})")

# A fixture is only a usable oracle if it has a captured result. Two are
# legitimately without one and both are accounted for by name.
no_result = sorted(k for k, r in records.items() if not r.get("result"))
expected_no_result = sorted([
    "__1___MeleeTwoWeaponFighting_20260810021656",   # empty gearset
    "Test_CasterDualCaster_20260809055408",          # unevaluatable today
])
check(no_result == expected_no_result,
      f"exactly the 2 known result-less fixtures ({no_result})")

usable = [k for k, r in records.items() if r.get("result")]
check(len(usable) == 12, f"12 usable 0.4.4 oracle results (found {len(usable)})")

# The v1.3 files' STORED stats came from the discarded Go implementation. The
# rule must be keyed on the version, never on hand-picked filenames.
mislabelled = [k for k, r in records.items()
               if (r.get("stored_reference") or {}).get("trustworthy")
               != (r.get("source_version") == "1.2")]
check(not mislabelled,
      f"trustworthiness derived from source_version, not filenames ({mislabelled or 'ok'})")

trustworthy = [k for k, r in records.items()
               if (r.get("stored_reference") or {}).get("trustworthy")]
check(len(trustworthy) == 5, f"5 v1.2 stored references (found {len(trustworthy)})")

# The headline regression fixture must keep its diagnosis, or Phase 4 loses the
# specific thing it is meant to assert.
head = records.get("Test_CasterDualCaster_20260809055408") or {}
classes = {d.get("class") for d in head.get("diagnosis") or []}
check("base-name-collision" in classes,
      "the unevaluatable fixture retains its base-name-collision diagnosis")
check({"empty-filigree-entry", "duplicate-filigree-name",
       "search-restriction-present"} <= classes,
      "...and its empty-entry / duplicate-name / restriction diagnoses")

print()
if fail:
    print(f"GATE FAILED — {len(fail)} check(s)")
    sys.exit(1)
print("GATE PASSED — oracle present and consistent")
PYCODE
