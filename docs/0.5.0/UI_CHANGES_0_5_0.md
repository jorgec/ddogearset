# UI spec — the 0.5.0 interface work, to be rebuilt

> [!IMPORTANT]
> **None of this exists on `main`.** It was built on a branch that has been
> discarded, and only this document survives. Read every "**After**" below as
> **"build this"**, and every "**Before**" as **"what `main` does today"** —
> the Before descriptions were verified against `main` and are accurate.
>
> Start with [`00_RECALC_PHASE_START_HERE.md`](00_RECALC_PHASE_START_HERE.md)
> for the baseline and what else is missing.

**Written:** 2026-08-10.
**Status:** **Rebuild.** This work was sound and is independent of how stats
get calculated, so it survives the change of direction described in
[`CALCULATE_STATS_RETROSPECTIVE.md`](CALCULATE_STATS_RETROSPECTIVE.md).

This is a spec, not a changelog: it records the **reasoning** so the behaviour
can be rebuilt or defended later. Where a rule looks fussy, the rule is
load-bearing and the note says why — most of them are the fix for a bug that
was actually reported.

---

## 1. Layout — the left column becomes three tabs

**Before:** Gear Sockets occupied the left column. Filigrees lived inside the
bottom configuration drawer. Solver output overwrote the gear sockets in place.

**After:** the left column is a three-tab panel.

| Tab | Shows | Writes to |
|---|---|---|
| **Gear** | The user's socketed items | `pre_equipped` |
| **Filigrees** | The user's filigree picks | `pre_filled_filigrees` |
| **Suggestions** | What the solver proposed | nothing (read-only until Accept) |

**Why:**

- Gear and filigrees are one task. Putting filigrees in the drawer meant
  opening a configuration panel to do gear work, and the drawer's open/closed
  state collapses the gear view to a header strip.
- The drawer becomes single-purpose (Build & Priorities), which is what its
  title claims.
- Suggestions needs to sit *next to* the gearset, because the whole point is
  comparing what you have against what was proposed.

**Rules that matter:**

- **All three tabs stay mounted**; only visibility toggles (`class:hidden`, not
  `{#if}`). Switching tabs must never discard a half-made selection, an
  in-flight fetch, or the socket list's scroll position. This matches the
  existing convention for the right-hand readout column.
- **Tab activation is driven by events, not just clicks:**
  - fresh launch → **Suggestions** (it doubles as the onboarding/empty state)
  - a solve returns → **Suggestions**
  - a file is loaded → **Gear** (the user just opened *their* gearset)
- Filigree slots render in a **single column, unconditionally**. A *viewport*
  breakpoint (`md:`/`xl:grid-cols-2`) does **not** work here: the container is
  always ~25% of the window, so the breakpoint still fires on a wide screen and
  reintroduces the cramping. It is a container-width problem, not a viewport
  one.
- The "Gear Sockets" heading was removed from inside the panel — the tab stud
  above already says it, and keeping both squeezed the three action buttons
  onto two lines.

---

## 2. The two-node model — solver output is a proposal

**The single most important behavioural change.**

**Before:** a solve wrote its results straight into `pre_equipped` via
`hydrateConfigFromSlots`. Gear the user had deliberately chosen could be
replaced without them agreeing to it.

**After:** two separate things, never conflated:

```
pre_equipped          — the USER'S gearset. Their intent.
solvedEquipmentStore  — what the SOLVER proposed. A proposal.
```

`pre_equipped` is written by exactly three things:

1. the user equipping/clearing something,
2. loading a saved file,
3. the user explicitly **accepting** a suggestion.

`hydrateConfigFromSlots` is **deleted**, not merely unused.

**Suggestions tab presentation:**

- Items already in `pre_equipped` render **dimmed with a "Pinned" badge** — the
  solver returned them because it was told to, not because it chose them.
- Solver-chosen items render **highlighted with an Accept button**.
- **Accept All** takes every suggested item *and* the suggested filigrees.
- Empty state doubles as onboarding: *"Set your preferences, then optionally
  fill some slots in your gearset, and run the optimizer to get
  recommendations."* — with "preferences" opening the configuration drawer.

**Consequences that must be handled (both were missed once):**

- **Optimize with every slot filled is a no-op.** Say so plainly rather than
  running a search that can only hand back what it was given:
  > *"All slots are filled — the solver has nothing to search for. Clear slots
  > you'd like it to fill, or use Calculate Stats to see your current gearset's
  > totals."*
- **Save must refuse an empty gearset.** Because solver output no longer flows
  into `pre_equipped`, pressing Save while looking at a full Suggestions tab
  wrote a file with nothing in it. Name the missing step:
  > *"Nothing is equipped yet — the optimizer's picks are still just
  > suggestions. Use Accept (or Accept All) in the Suggestions tab first."*

---

## 3. Check Inventory

A **Check Inventory** button in the Gear Sockets header, **between Calculate
and Clear**. Disabled until a Trove inventory CSV is loaded.

On click: badge every socketed item **green** (in the loaded inventory) or
**red** (not in it), and toast an owned/total summary.

**Why the details matter:**

- The comparison is **exact and case-sensitive**, deliberately. That is exactly
  what the solver does (`name not in owned_names`, and a verbatim `itemsByName`
  lookup in Go). Anything looser — trimming, case-folding, fuzzy matching —
  badges an item green that the solver then refuses to use when "restrict to
  owned" is on, and the UI is lying about the only thing this button exists to
  tell you.
- Badges stay **reactive** afterwards, so swapping an item re-badges it without
  another click.
- Badges **clear automatically** if the CSV is unloaded. Stale green/red dots
  pointing at an inventory that is no longer loaded are worse than none.

---

## 4. Progress logging and control lockout during file loads

Loading a gearset or a Trove CSV used to run silently with every button live.

**Two parts:**

**4.1 Narrate the client-side steps.** File read, checksum verify, JSON parse,
CSV cross-reference all happen in the frontend and produce no backend output at
all. An `AddLog` binding lets the frontend write into the same System Console
buffer.

**4.2 Lock the controls.** One shared `isLoadingFile` flag gates every control
that reads — or re-triggers a write to — the stores a load is mutating:
Optimize Gear, Update External Sources, Calculate, Check Inventory, Clear,
Load/Save gearset, and **both** Load-CSV entry points.

**Hard-won correctness rules — these caused a real "spinner never stops and the
whole UI is locked out" report:**

1. **The logging helper must be incapable of throwing.** A `.catch()` is *not*
   sufficient. The generated binding is
   `window['go']['main']['App']['AddLog'](arg)`; if that is unbound (runtime not
   injected, stale dev binary, browser-only preview) the call raises a
   **TypeError synchronously**, before `.catch` is attached. Wrap the whole
   body in `try/catch`.
2. **Nothing may sit between setting the busy flag and entering the `try`.**
   The `finally` is the only thing that clears it; any throw in that gap
   strands it at `true` forever with no recovery short of a restart.
3. **Every `FileReader` needs an `onerror` that clears the flag.** A failed
   read never reaches `onload`, so `onload`'s `finally` cannot help it.
4. **Log lines must be delivered in order.** Firing each `AddLog` independently
   let the console show a load as
   `refused → Parsing → Verifying → Reading` — exactly backwards, which makes a
   healthy load look like a confused one. Serialize them through a promise
   chain.
5. **Always log a terminal line.** The console previously ended on
   *"Restoring saved gear data…"* — an in-progress ellipsis with nothing after
   it — even on complete success. That is indistinguishable from a hang.

---

## 5. System Console buffer is bounded

`GetSystemLogs` is polled about once a second, forever. The buffer was
**unbounded**, and a single solve appends every line GLPK prints.

- Cap retained lines (2000 is far more scrollback than the console shows).
- `GetSystemLogs` returns a **copy** under a mutex — `append` can reallocate
  the backing array mid-read, and `AddLog` made the frontend a *third*
  concurrent writer.

This is not tidiness. A large response re-sent every second is constant load on
the Wails bridge, and bridge overload is how calls get silently dropped (see
the retrospective §2.3).

---

## 6. Wails calls that carry a large payload need a timeout

A Wails call is a promise that settles when Go answers over the webview bridge.
If the bridge **drops** the message, the promise never settles — it does not
reject, it hangs. Anything awaiting it hangs too, so a `finally` that clears a
busy flag never runs: locked UI, no error.

`withTimeout` converts that invisible, unrecoverable hang into an ordinary
error. It is a **backstop, not a fix** — every wrapped call should normally
answer in milliseconds.

**Better than a timeout: don't put a large call on the critical path.**
Checksum verification is advisory ("warn, don't block"), so it is now
fire-and-forget: the load proceeds immediately and the warning arrives when (or
if) the check returns.

---

## 7. Loading refuses files that need upgrading; Upgrade is its own action

**Before:** an old file was migrated on the fly during load.

**After:** loading **refuses** it, before a single store is written, and points
at an **Upgrade** button beside Load and Save.

**Why:**

- Migrating during a load did slow, invisible work *after* it had already
  replaced what was on screen. A migration that stalled left a half-applied
  gearset with no way to tell that had happened.
- Upgrade is inert: it reads a file, converts it, writes a **new** file (the
  original is never modified — every save gets a fresh timestamped name), and
  changes nothing on screen. The user then loads the upgraded copy as an
  ordinary load. The conversion is reviewable instead of something that happens
  to them.
- It reports names the catalog no longer resolves rather than dropping them
  silently.

**The detection rule is the important part.** Key on the **defect**, not the
version stamp:

> a file needs upgrading exactly when it has equipped gear but not the data
> needed to evaluate that gear

Keying on "the new data is empty" alone was wrong: an **empty gearset**
legitimately has neither, and branding it legacy sent the user to an upgrade
that then reported "nothing to upgrade" — a dead end.

Also: gear can live **only** in `result.gearSet` with an empty `pre_equipped`.
That is what a solve-then-save produces under the two-node model, and it is
still a real gearset — the upgrade must rescue it, not call it empty.

> **This feature may have nothing to do.** It existed because the abandoned
> approach persisted a derived cache (`enriched_gear`) in the save file, so old
> files needed converting. The Python-side design persists no such cache, so
> there is likely no migration to perform — save format v1.2 on `main` stays
> valid. **Keep the *rules* above** (refuse-don't-migrate; detect on the defect,
> not the version; empty gearsets are loadable; rescue gear that lives only in
> `result.gearSet`) for whenever a genuine format change does arrive, and skip
> the button until then.

---

## 8. Backend change that is user-visible: unbuffered solver output

`PYTHONUNBUFFERED=1` in the solver subprocess's environment.

CPython block-buffers stdout when it is not a TTY — always the case here, since
Go owns the other end of the pipe. Without it, `solver.py`'s progress prints
only flush when the subprocess **exits**, so the System Console stays silent
for the entire solve and a working 40-second run is indistinguishable from a
hang.

**Keep this regardless of direction.** It matters *more* if recalculation moves
back into Python, since that adds another subprocess round trip the user waits
on.

---

## 9. Build checklist — the non-negotiable details

| # | Behaviour | Non-negotiable detail |
|---|---|---|
| 1 | Three-tab left column | All tabs stay mounted; filigrees single-column always |
| 2 | Solver output is a proposal | `pre_equipped` written only by user action, load, or Accept |
| 2 | Optimize / Save guards | Both explain the missing step rather than no-op'ing silently |
| 3 | Check Inventory | Exact, case-sensitive match — must agree with the solver |
| 4 | Load progress + lockout | Logger cannot throw; nothing between flag and `try`; `onerror`; ordered lines; terminal line |
| 5 | Bounded log buffer | Copy under mutex; three concurrent writers |
| 6 | Large-payload calls | Timeout backstop; keep advisory calls off the critical path |
| 7 | Refuse-then-upgrade *(only if a format migration is ever needed)* | Detect on the defect, not the version; empty gearsets are loadable |
| 8 | `PYTHONUNBUFFERED=1` | Otherwise the console is silent for the whole solve |
