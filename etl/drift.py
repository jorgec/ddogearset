"""Renders the drift report — docs/0.5.0/00_ETL_START_HERE.md §6.1.

The report exists for exactly one reader: a human deciding what a disappeared
name became. Everything here is in service of making that decision fast and
making the answer cheap to record — hence the ranked candidates and the
ready-to-paste `aliases.yaml` block at the end of the unresolved section.

It reports what the run DID, not just what it could not do: auto-resolutions
are listed too, because "the ETL quietly decided Epic X became Legendary X" is
a decision worth being able to audit after the fact.
"""

from __future__ import annotations

from typing import List, Optional

from .identity import Registry

# A first run against a fresh registry mints ~19k entities and auto-resolves
# nothing; a later run that renames a whole file's worth of items could
# auto-resolve hundreds. Listing every one turns the report into a data dump
# and buries the part that needs a human. Unresolved entries are NEVER capped —
# those are the whole point of the file.
_AUTO_LIST_CAP = 200


def _escape_cell(text: str) -> str:
    """Markdown table cells break on a literal pipe, and augment natural keys
    embed a US separator (\\x1f) that renders as nothing at all — make both
    visible rather than silently mangling the name a human has to match."""
    return text.replace("\x1f", " ␟ ").replace("|", "\\|")


def render_report(registry: Registry, *, commit: str, built_at: str,
                  source_dir: str, strict: bool,
                  data_ambiguities: Optional[List[str]] = None) -> str:
    out: List[str] = []
    unresolved = registry.unresolved
    autos = registry.auto_resolutions
    ambiguities = data_ambiguities or []

    out.append(f"# Identity drift report — `{commit}`")
    out.append("")
    out.append(f"- **Source:** `{source_dir}`")
    out.append(f"- **Built at:** {built_at}")
    out.append(f"- **Mode:** {'`--strict` (unresolved drift fails the build)' if strict else 'permissive (unresolved drift mints new identities)'}")
    out.append("")
    out.append("| | Count |")
    out.append("|---|---:|")
    out.append(f"| New entities minted | {registry.new_count} |")
    out.append(f"| Auto-resolved renames | {registry.auto_resolved_count} |")
    out.append(f"| **Unresolved — needs a decision** | **{len(unresolved)}** |")
    if ambiguities:
        out.append(f"| Source-data ambiguities | {len(ambiguities)} |")
    out.append("")

    if not unresolved and not autos and not ambiguities:
        out.append("No renames detected. Nothing to decide.")
        out.append("")
        return "\n".join(out)

    if unresolved:
        out.append("## Unresolved")
        out.append("")
        out.append("These keys vanished from the corpus and no *clean derivation* "
                   "explains where they went (§6.1 — a tier prefix, whitespace/case "
                   "alone, or an explicit `version of` relationship; anything else "
                   "is a guess, and a wrong guess silently rewrites what a saved "
                   "gearset means).")
        out.append("")
        out.append("Candidates are the current corpus keys ranked by string "
                   "similarity — a starting point, not an answer. Confirm against "
                   "`DropLocation` and the effect list before recording one.")
        out.append("")
        out.append("| Kind | Disappeared | Closest current keys |")
        out.append("|---|---|---|")
        for entry in unresolved:
            candidates = ", ".join(f"`{_escape_cell(c)}`" for c in entry.candidates) or "*(none similar)*"
            out.append(f"| {entry.kind} | `{_escape_cell(entry.disappeared)}` | {candidates} |")
        out.append("")
        out.append("### Record the answers in `etl/aliases.yaml`")
        out.append("")
        out.append("Paste this in and fill each `now:` — a quoted new name, or "
                   "`null` if it is genuinely gone from the game. Both forms keep "
                   "the original UUID reachable; leaving an entry out does not.")
        out.append("")
        out.append("```yaml")
        for entry in unresolved:
            # Comment, never a filled-in value: pre-filling `now:` with the top
            # similarity match is precisely the guess §6.1 forbids, and one that
            # arrives pre-typed is one nobody re-checks.
            if entry.candidates:
                out.append(f"# candidates: {', '.join(entry.candidates)}")
            out.append(f"- kind: {entry.kind}")
            out.append(f"  was: {_yaml_quote(entry.disappeared)}")
            out.append("  now: # \"New Name\" or null")
        out.append("```")
        out.append("")

    if autos:
        out.append("## Auto-resolved")
        out.append("")
        out.append("Folded into the registry as `aka` entries — the UUID did not "
                   "change. Listed so the decision is auditable, not because "
                   "anything is required of you.")
        out.append("")
        out.append("| Kind | Was | Now | Why |")
        out.append("|---|---|---|---|")
        for res in autos[:_AUTO_LIST_CAP]:
            out.append(f"| {res.kind} | `{_escape_cell(res.old_key)}` | "
                       f"`{_escape_cell(res.new_key)}` | {res.reason} |")
        if len(autos) > _AUTO_LIST_CAP:
            out.append(f"| … | *and {len(autos) - _AUTO_LIST_CAP} more* | | |")
        out.append("")

    if ambiguities:
        out.append("## Source-data ambiguities")
        out.append("")
        out.append("Two things in DDOBuilderV2 want the same identity and no "
                   "field tells them apart. Transform picked deterministically "
                   "and says which; `aliases.yaml` cannot fix these, because "
                   "the problem is upstream, not a rename. They are listed on "
                   "every run so a *new* one is noticeable among the known ones.")
        out.append("")
        for message in ambiguities:
            out.append(f"- {message}")
        out.append("")

    return "\n".join(out)


def _yaml_quote(value: str) -> str:
    """Double-quoted, with the two escapes `aliases.py` understands. Kept in
    step with `aliases._parse_quoted` — this function's output is pasted
    straight into the file that parser reads."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
