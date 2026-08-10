"""Reads `etl/aliases.yaml` — the operator's answers to identity drift.

See docs/0.5.0/00_ETL_START_HERE.md §6.1. When DDOBuilderV2 renames something
and the rename is not a *clean derivation* (`identity._is_clean_derivation`),
the ETL refuses to guess and writes a drift report. A human reads it and
records the answer here; the next run folds it into the registry, and the
entity keeps its original UUID.

## Why this file is parsed by hand instead of with PyYAML

Because it decides identity. An entry here silently rewrites what a saved
gearset's item reference *means*, so the parser's job is not to be
accommodating — it is to accept exactly one unambiguous shape and reject
everything else loudly.

PyYAML would accept far more than that shape, and it is not installed in this
project (nothing else needs it). Adding it would mean the file parses on a
machine that has it and fails on one that does not — build behaviour diverging
by machine is strictly worse than a small parser that behaves identically
everywhere. So: no dependency, and a deliberately narrow subset.

## The subset

```yaml
# Free-standing comments and blank lines are ignored anywhere.
- was: "Bracers of the Sun Soul"          # required, must be quoted
  now: "Legendary Bracers of the Sun Soul" # required; quoted, or the bare word null
- was: "Gem of Many Facets"
  now: null                                # confirmed: removed from the game
- kind: augment                            # optional; unqualified entries apply to every kind
  was: "Twilight"
  now: "Twilight Shard"
```

Rules the parser enforces:

- `was` and `now` are both REQUIRED on every entry. A missing `now` is an
  error, never an implied "removed" — deleting an identity must be typed out.
- String values MUST be quoted. A bare unquoted scalar is rejected with a
  message telling you to quote it, which is what makes a trailing `# comment`
  unambiguous (inside quotes a `#` is literal; after the closing quote it
  starts a comment). Item names contain apostrophes, colons and commas, so
  guessing where an unquoted value ends is exactly the kind of near-miss this
  file cannot afford.
- Unknown keys, duplicate keys within an entry, and two entries with the same
  (kind, was) are all errors.
- An entry with an explicit `kind` overrides an unqualified entry for the same
  `was` in that one kind, and only there.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

KNOWN_KEYS = ("kind", "was", "now")

# `now: null` and `now: ~` both mean "confirmed gone". An empty value does NOT
# — it reads as a typo far more often than as an intent, so it is rejected.
_NULL_LITERALS = ("null", "~")


class AliasError(ValueError):
    """A malformed aliases file. Always carries the line number — this file is
    hand-edited, and 'somewhere in aliases.yaml' is not an actionable error."""


@dataclass(frozen=True)
class AliasEntry:
    was: str
    now: Optional[str]
    kind: Optional[str]
    line: int


def _fail(line_no: int, message: str) -> None:
    raise AliasError(f"aliases.yaml line {line_no}: {message}")


def _parse_quoted(raw: str, line_no: int, key: str) -> str:
    """Reads one quoted scalar off the front of `raw` and requires that
    nothing but whitespace or a `#` comment follows it."""
    quote = raw[0]
    out: List[str] = []
    i = 1
    while i < len(raw):
        ch = raw[i]
        if quote == '"' and ch == "\\":
            if i + 1 >= len(raw):
                _fail(line_no, f"{key}: string ends with a dangling backslash")
            nxt = raw[i + 1]
            if nxt not in ('"', "\\"):
                _fail(line_no, f"{key}: unsupported escape '\\{nxt}' "
                               "(only \\\" and \\\\ are understood)")
            out.append(nxt)
            i += 2
            continue
        if quote == "'" and ch == "'":
            # YAML's single-quote escape is a doubled quote.
            if i + 1 < len(raw) and raw[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            i += 1
            break
        if ch == quote:
            i += 1
            break
        out.append(ch)
        i += 1
    else:
        _fail(line_no, f"{key}: unterminated {quote}-quoted string")

    trailing = raw[i:].strip()
    if trailing and not trailing.startswith("#"):
        _fail(line_no, f"{key}: unexpected text after the closing quote: {trailing!r}")
    return "".join(out)


def _parse_value(raw: str, line_no: int, key: str, *, allow_null: bool,
                 allow_bare_word: bool) -> Optional[str]:
    raw = raw.strip()
    if raw.startswith('"') or raw.startswith("'"):
        return _parse_quoted(raw, line_no, key)

    # Strip a trailing comment only for the un-quoted forms below, where there
    # is no closing quote to anchor it to.
    bare = raw.split("#", 1)[0].strip()
    if not bare:
        _fail(line_no, f"{key}: missing value (use a quoted string"
                       + (", or the bare word null" if allow_null else "") + ")")
    if allow_null and bare.lower() in _NULL_LITERALS:
        return None
    if allow_bare_word and bare.replace("_", "").isalnum():
        return bare
    _fail(line_no, f"{key}: value must be quoted — got {bare!r}. "
                   "Item names contain punctuation, so unquoted values are "
                   "not guessed at.")
    return None  # unreachable; _fail always raises


def parse_aliases_text(text: str) -> List[AliasEntry]:
    # Fields accumulate into a plain dict per entry rather than straight into
    # AliasEntry, because `now: null` is a legal VALUE — "was `now` written?"
    # can only be answered by which keys were seen, never by what they hold.
    parsed: List[dict] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith("- "):
            parsed.append({"line": line_no, "fields": {}})
            body = line[2:]
        elif line.startswith((" ", "\t")):
            if not parsed:
                _fail(line_no, "indented line before any '- ' entry")
            body = line.strip()
        else:
            _fail(line_no, f"expected a '- ' entry, an indented key, a comment "
                           f"or a blank line — got {line!r}")
            return []  # unreachable; _fail always raises

        key, sep, value = body.partition(":")
        key = key.strip()
        if not sep:
            _fail(line_no, f"expected 'key: value' — got {body!r}")
        if key not in KNOWN_KEYS:
            _fail(line_no, f"unknown key {key!r} (expected one of "
                           f"{', '.join(KNOWN_KEYS)})")
        fields = parsed[-1]["fields"]
        if key in fields:
            _fail(line_no, f"duplicate key {key!r} in the same entry")

        if key == "was":
            fields[key] = _parse_value(value, line_no, key, allow_null=False,
                                       allow_bare_word=False)
        elif key == "now":
            fields[key] = _parse_value(value, line_no, key, allow_null=True,
                                       allow_bare_word=False)
        else:  # kind
            fields[key] = _parse_value(value, line_no, key, allow_null=False,
                                       allow_bare_word=True)

    entries: List[AliasEntry] = []
    for raw in parsed:
        fields, line_no = raw["fields"], raw["line"]
        if "was" not in fields:
            _fail(line_no, "entry is missing 'was'")
        if "now" not in fields:
            _fail(line_no,
                  f"entry for {fields['was']!r} is missing 'now'. Write the "
                  "answer explicitly — 'now: \"New Name\"' for a rename, or "
                  "'now: null' if it is genuinely gone.")
        entries.append(AliasEntry(was=fields["was"], now=fields["now"],
                                  kind=fields.get("kind"), line=line_no))
    return entries


def load_aliases(path: Path, kinds: Iterable[str]) -> Dict[str, Dict[str, Optional[str]]]:
    """Returns `{kind: {old_key: new_key_or_None}}` for every kind in `kinds`,
    the shape `transform()` passes straight to `Registry.reconcile_disappeared`.
    A missing file is not an error — it just means no drift has been resolved
    yet."""
    kinds = list(kinds)
    result: Dict[str, Dict[str, Optional[str]]] = {k: {} for k in kinds}
    if not path.exists():
        return result

    entries = parse_aliases_text(path.read_text())

    seen: Dict[tuple, int] = {}
    for entry in entries:
        if entry.kind is not None and entry.kind not in result:
            _fail(entry.line, f"unknown kind {entry.kind!r} (expected one of "
                              f"{', '.join(sorted(result))})")
        dedup_key = (entry.kind, entry.was)
        if dedup_key in seen:
            _fail(entry.line, f"{entry.was!r} already has an answer on line "
                              f"{seen[dedup_key]}"
                              + (f" for kind {entry.kind!r}" if entry.kind else ""))
        seen[dedup_key] = entry.line

    # Unqualified entries first so an explicitly-kinded one wins in its own
    # kind — see this module's docstring.
    for entry in entries:
        if entry.kind is None:
            for kind in result:
                result[kind][entry.was] = entry.now
    for entry in entries:
        if entry.kind is not None:
            result[entry.kind][entry.was] = entry.now

    return result
