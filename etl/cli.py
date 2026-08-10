"""`python -m etl` — builds catalog.db from a DDOBuilderV2 checkout.

Runs Extract (`walk.py`) → Transform (`transform.py`) → Load (`load.py`) once,
and owns everything around that pipeline that is a *decision* rather than a
transformation: which corpus, which registry, what the catalog calls itself,
and what happens when identity drifts (§6.2 — `--strict`).

Typical use:

    python -m etl                                   # dev: warn on drift, keep going
    python -m etl --strict --out bundled/darwin-arm64/catalog.db   # release

Exit codes are meaningful, because a build script reads them:

    0  catalog written
    1  the run failed (bad corpus, validation error, unreadable aliases file)
    2  --strict and there is unresolved identity drift; no catalog was written
       and the registry was NOT modified
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import ETL_VERSION, MIN_APP_VERSION
from .aliases import AliasError, load_aliases
from .drift import render_report
from .identity import NAMESPACES, Registry
from .load import _content_hash, build_catalog

REPO_ROOT = Path(__file__).resolve().parent.parent

# The `data/ddobuilder` SUBMODULE, not the gitignored DDOBuilderV2/ directory
# the (now deleted) runtime fetch used to drop beside it. Both hold the same
# bytes — verified identical, 9070 files, same digest — but only the submodule
# is pinned: `git clone --recurse-submodules` puts the exact revision a given
# catalog was built from on disk, and `_source_fingerprint` can read a real
# upstream SHA out of it instead of falling back to a content digest.
#
# A gitignored working copy cannot promise either. It is whatever someone last
# downloaded.
DEFAULT_SOURCE = REPO_ROOT / "data" / "ddobuilder" / "Output" / "DataFiles"
DEFAULT_REGISTRY = REPO_ROOT / "etl" / "identity_registry.json"
DEFAULT_ALIASES = REPO_ROOT / "etl" / "aliases.yaml"
DEFAULT_DRIFT_DIR = REPO_ROOT / "etl" / "drift"
DEFAULT_OUT = REPO_ROOT / "catalog.db"

EXIT_FAILURE = 1
EXIT_UNRESOLVED_DRIFT = 2


def _log(message: str) -> None:
    print(message, flush=True)


def _built_at() -> str:
    """RFC3339, truncated to midnight UTC.

    Deliberately not the wall clock: `built_at` is written into every registry
    entry minted this run (`first_seen`), and a full timestamp would make
    `identity_registry.json` produce a different diff on every single run even
    when nothing about the corpus changed. Day granularity is all the field is
    ever read at, and it keeps a rebuild on the same day byte-identical — the
    determinism Phase 3's gate asks for.
    """
    today = _datetime.datetime.now(_datetime.timezone.utc).date()
    return f"{today.isoformat()}T00:00:00Z"


def _source_fingerprint(source: Path) -> str:
    """Identifies which game data this catalog was built from
    (`catalog_meta.ddobuilder_commit`).

    A real upstream SHA when one is actually available, and otherwise a hash of
    the corpus itself. The fallback is not a consolation prize: DDOBuilderV2 is
    normally obtained as a zip (there is no `.git` in it — the app used to fetch
    it over plain HTTPS, and since Phase 6 nothing fetches it at all), so a
    content digest is usually the *only* honest answer to "which data is this".

    The `.git` existence check is load-bearing, not defensive. `git -C
    DDOBuilderV2/... rev-parse HEAD` in this repo succeeds and returns
    **goGearset's own HEAD** — git walks up to the enclosing repository, and
    DDOBuilderV2 sits inside it (gitignored). Without this check the field
    would be confidently, silently wrong.
    """
    for candidate in (source, source.parent, source.parent.parent):
        if (candidate / ".git").exists():
            try:
                sha = subprocess.run(
                    ["git", "-C", str(candidate), "rev-parse", "HEAD"],
                    capture_output=True, text=True, check=True).stdout.strip()
                if sha:
                    return sha
            except (subprocess.CalledProcessError, FileNotFoundError):
                break

    digest = hashlib.sha256()
    files = sorted(p for p in source.rglob("*") if p.is_file()
                   and p.suffix.lower() in (".xml", ".item"))
    for path in files:
        digest.update(str(path.relative_to(source)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "content-" + digest.hexdigest()[:12]


def _source_file_count(source: Path) -> int:
    return sum(1 for p in source.rglob("*")
               if p.is_file() and p.suffix.lower() in (".xml", ".item"))


def _read_existing_catalog_meta(out_path: Path):
    """(catalog_version, content_hash) of a catalog already at `out_path`, or
    None. Any failure to read one is treated as 'no previous catalog' — this
    only feeds the version default, which `--catalog-version` overrides."""
    if not out_path.exists():
        return None
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT catalog_version, content_hash FROM catalog_meta WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        return row
    except sqlite3.Error:
        return None


def _resolve_catalog_version(out_path: Path, new_content_hash: str,
                             explicit: Optional[int]) -> int:
    """`catalog_version` is the counter a future 'update catalog' feature
    compares against (schema doc §5.1.2), and `catalog_seed.go` already uses it
    to decide whether an app update's bundled catalog should replace the
    installed one. It therefore has to move when the CONTENT moves.

    Deriving it from the catalog being overwritten works because the build
    scripts write straight into `bundled/<platform>/catalog.db`, which is
    committed (same convention as the other bundled binaries) — so even a clean
    checkout has the previous version to count up from.
    """
    previous = _read_existing_catalog_meta(out_path)
    if explicit is not None:
        if previous and explicit < previous[0]:
            _log(f"   warning: --catalog-version {explicit} is LOWER than the "
                 f"{previous[0]} already at {out_path}. An app holding the older "
                 "catalog will not accept this one as an update.")
        return explicit
    if previous is None:
        return 1
    prev_version, prev_hash = previous
    if prev_hash == new_content_hash:
        _log(f"   catalog content is unchanged — keeping catalog_version {prev_version}.")
        return prev_version
    return prev_version + 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m etl",
        description="Build catalog.db from a DDOBuilderV2 checkout (dev only — "
                    "this never ships with the app).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                   help="DDOBuilderV2's DataFiles directory")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="where to write catalog.db")
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                   help="identity registry (mint-once UUIDs)")
    p.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES,
                   help="operator-confirmed rename answers")
    p.add_argument("--drift-report", type=Path, default=None,
                   help="where to write the drift report "
                        f"(default: {DEFAULT_DRIFT_DIR}/<commit>.md, written "
                        "only when there is drift to report)")
    p.add_argument("--catalog-version", type=int, default=None,
                   help="explicit catalog_version (default: carry the previous "
                        "one forward, +1 when the content changed)")
    p.add_argument("--min-app-version", default=MIN_APP_VERSION,
                   help="oldest app release that can read this catalog")
    p.add_argument("--ddobuilder-commit", default=None,
                   help="upstream data revision to record (default: the "
                        "source's git HEAD if it is a checkout, else a content "
                        "digest of the corpus)")
    p.add_argument("--strict", action="store_true",
                   help="fail the build on unresolved identity drift; release "
                        "builds pass this")
    p.add_argument("--init-registry", action="store_true",
                   help="allow creating the identity registry from nothing. "
                        "Required when --registry does not exist, because "
                        "silently minting a fresh one would issue brand-new "
                        "UUIDs for every entity and orphan every saved gearset")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    source: Path = args.source
    if not (source / "Items").is_dir():
        _log(f"error: no game data at {source} — expected DDOBuilderV2's\n"
             "       DataFiles directory, which has an Items/ subdirectory.\n"
             "\n"
             "       This is the data/ddobuilder submodule, and it is almost\n"
             "       certainly just not checked out:\n"
             "           git submodule update --init --depth 1\n"
             "\n"
             "       It is a BUILD input only. Since 0.5.0 the app ships\n"
             "       catalog.db and never reads this XML at runtime, so nothing\n"
             "       fetches it and it is not needed to RUN anything — only to\n"
             "       build a catalog. Point --source elsewhere to use another copy.")
        return EXIT_FAILURE

    if not args.registry.exists() and not args.init_registry:
        _log(f"error: no identity registry at {args.registry}.\n"
             "       Every UUID in catalog.db is pinned there; building without "
             "it would mint a\n"
             "       fresh identity for every entity in the game and orphan "
             "every saved gearset.\n"
             "       If this really is the first ever build, pass --init-registry.")
        return EXIT_FAILURE

    try:
        aliases = load_aliases(args.aliases, NAMESPACES.keys())
    except AliasError as exc:
        _log(f"error: {exc}")
        return EXIT_FAILURE

    built_at = _built_at()
    commit = args.ddobuilder_commit or _source_fingerprint(source)
    file_count = _source_file_count(source)

    _log("=== ETL: building catalog.db ===")
    _log(f"   source     {source}  ({file_count} data files)")
    _log(f"   data rev   {commit}")
    _log(f"   registry   {args.registry}")
    _log(f"   out        {args.out}")
    _log(f"   mode       {'strict' if args.strict else 'permissive'}")

    # Imported here, not at module scope: `walk` pulls in python/parser.py and
    # python/rules/, so importing it costs real time and can fail on a broken
    # corpus. --help must work regardless of either.
    from .transform import transform
    from .walk import walk_corpus

    started = time.time()
    _log("-> Extract: walking the corpus...")
    corpus = walk_corpus(str(source))
    _log(f"   {len(corpus.items)} items, {len(corpus.augments)} augments, "
         f"{len(corpus.filigrees)} filigrees, {len(corpus.set_tiers)} set tiers, "
         f"{len(corpus.quests)} quests ({time.time() - started:.1f}s)")

    registry = Registry.load(args.registry)
    _log(f"-> Transform: resolving identity against {len(registry.entities)} "
         "known entities...")
    result = transform(corpus, registry, built_at=built_at, commit=commit,
                       aliases=aliases, strict=args.strict)
    _log(f"   minted {registry.new_count} new, auto-resolved "
         f"{registry.auto_resolved_count} rename(s), "
         f"{len(registry.unresolved)} unresolved ({time.time() - started:.1f}s)")

    # Fatal in BOTH modes, unlike unresolved drift. Unresolved drift is the
    # data moving faster than the operator; an alias conflict is the operator's
    # own file being wrong, and permissively "proceeding" past it would apply
    # an identity decision nobody actually made.
    if registry.alias_conflicts:
        _log(f"error: {len(registry.alias_conflicts)} entry(ies) in "
             f"{args.aliases} cannot be applied:")
        for message in registry.alias_conflicts:
            _log(f"   - {message}")
        return EXIT_FAILURE

    if result.validation_errors:
        _log(f"error: Transform produced {len(result.validation_errors)} "
             "validation error(s) — refusing to build:")
        for message in result.validation_errors[:20]:
            _log(f"   - {message}")
        if len(result.validation_errors) > 20:
            _log(f"   ... and {len(result.validation_errors) - 20} more")
        return EXIT_FAILURE

    if result.data_ambiguities:
        _log(f"warning: {len(result.data_ambiguities)} ambiguity(ies) in the "
             "source data — Transform had to pick:")
        for message in result.data_ambiguities:
            _log(f"   - {message}")

    drift_path: Optional[Path] = args.drift_report
    has_drift = bool(registry.unresolved or registry.auto_resolutions
                     or result.data_ambiguities)
    if drift_path is None and has_drift:
        drift_path = DEFAULT_DRIFT_DIR / f"{commit}.md"
    if drift_path is not None:
        report = render_report(registry, commit=commit, built_at=built_at,
                               source_dir=str(source), strict=args.strict,
                               data_ambiguities=result.data_ambiguities)
        drift_path.parent.mkdir(parents=True, exist_ok=True)
        drift_path.write_text(report)
        _log(f"   drift report written to {drift_path}")

    if registry.unresolved:
        _log(f"{'error' if args.strict else 'warning'}: "
             f"{len(registry.unresolved)} identity(ies) disappeared from the "
             "corpus with no clean derivation.")
        for entry in registry.unresolved[:10]:
            _log(f"   - [{entry.kind}] {entry.disappeared!r}")
        if len(registry.unresolved) > 10:
            _log(f"   ... and {len(registry.unresolved) - 10} more")
        if args.strict:
            _log("Refusing to build. Resolve each one in "
                 f"{args.aliases} (the drift report has a block ready to paste), "
                 "then re-run.")
            # Nothing is persisted on this path: no catalog, and crucially no
            # registry save. Saving would bake in the new identities --strict
            # exists to reject, and the next run would see nothing to resolve.
            return EXIT_UNRESOLVED_DRIFT
        _log("   Proceeding anyway (no --strict): these mint new identities. "
             "Anything saved against the old ones stops resolving.")

    catalog_version = _resolve_catalog_version(
        args.out, _content_hash(result), args.catalog_version)

    # Save the registry BEFORE Load, not after: build_catalog hashes the
    # registry FILE into catalog_meta.identity_registry_hash, so a save that
    # came afterwards would stamp the catalog with the hash of the previous
    # registry — a mismatch against the very UUIDs it just wrote. If Load then
    # fails, the saved mints are harmless: mint-once means the next run reuses
    # exactly these UUIDs.
    registry.save()

    _log(f"-> Load: writing {args.out} (catalog_version {catalog_version})...")
    build_catalog(result, args.out, registry_path=args.registry,
                  ddobuilder_commit=commit, etl_version=ETL_VERSION,
                  source_file_count=file_count,
                  min_app_version=args.min_app_version,
                  catalog_version=catalog_version, built_at=built_at)

    size_mb = args.out.stat().st_size / 1024 / 1024
    _log(f"   wrote {args.out} ({size_mb:.1f} MB) in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
