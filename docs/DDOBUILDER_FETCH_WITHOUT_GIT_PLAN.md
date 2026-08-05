# Plan — Fetch DDOBuilderV2 Without Requiring a `git` Binary

**Status:** Planning only, not implemented.
**Problem:** `ensureDDOBuilderData()` (`app.go`) shells out to `git clone`/`git pull` to
fetch DDOBuilderV2. On a Windows machine without `git` on `PATH`, this fails outright —
and per this task, we're not allowed to paper over that by assuming a package manager
(Chocolatey or otherwise) is available to install `git` first. The fix needs to not need
`git` at all, on any platform.

---

## Chosen approach: plain HTTPS zip download, Go stdlib only

Replace the `git clone`/`git pull` calls with an HTTP GET of GitHub's repository archive
endpoint, extracted with Go's standard library. **No new dependencies** — `net/http` and
`archive/zip` are both stdlib, so this needs nothing installed on the build *or* the
runtime machine beyond what already ships in the compiled binary.

```
https://codeload.github.com/Maetrim/DDOBuilderV2/zip/refs/heads/main
```

Verified directly (not assumed):
- The redirect chain from `github.com/.../archive/refs/heads/main.zip` resolves to
  `codeload.github.com` — calling codeload directly skips the redirect.
- The repo's default branch is `main` (confirmed via `git ls-remote --symref`).
- No authentication needed — DDOBuilderV2 is public.
- **The archive is 79MB, 20,521 files, ~200MB uncompressed.** This is the number that
  drives most of the design below — it's too large to casually re-download on every
  "Update External Sources" click without a way to skip it when nothing changed.

This replaces the git-based fetch **uniformly across all platforms** (not just Windows).
Keeping a git-if-available/zip-if-not hybrid would mean two code paths doing the same
job, tested differently, for no real benefit — the zip approach works everywhere git
would have, including machines that do have git installed.

---

## Design

### 1. Fetch + extract (`fetchDDOBuilderData()`, replaces the clone half of `ensureDDOBuilderData()`)

1. `http.Get("https://codeload.github.com/Maetrim/DDOBuilderV2/zip/refs/heads/main")`,
   stream the body to a temp file (`os.CreateTemp`) via `io.Copy` — not buffered fully in
   memory, 79MB is fine on disk but no need to hold it in RAM too.
2. Open the temp file with `zip.OpenReader`. GitHub's archive wraps everything in a
   single top-level directory named `<repo>-<branch>` (confirmed: `DDOBuilderV2-main/`)
   — strip that prefix from every entry's path as it's extracted.
3. Extract into a **staging directory** (`DDOBuilderV2.download/`, sibling to the real
   `DDOBuilderV2/`), not directly into the final location.
4. Only after every entry extracts successfully: remove the old `DDOBuilderV2/` (if any)
   and rename `DDOBuilderV2.download/` → `DDOBuilderV2/`. This is the atomicity property
   that matters — a failed download or a mid-extraction crash must never leave the app
   with a half-replaced, broken data directory. If anything fails before that final
   rename, delete the staging directory and leave whatever `DDOBuilderV2/` already
   existed completely untouched.
5. Delete the temp zip file.

### 2. Skip re-fetching when nothing changed (the part that makes #1 not wasteful)

Without this, every click of "Update External Sources" re-downloads the full 79MB even
if DDOBuilderV2 hasn't changed since last time — a real regression from `git pull`
(which only ever transfers new objects). This isn't a nice-to-have; the size numbers
above make it load-bearing for the feature to be usable at all as a repeat action.

- After a successful extract, write the fetched commit SHA to a small marker file
  **outside** `DDOBuilderV2/` itself (e.g. project-root `.ddobuilderv2_commit`,
  gitignored) — keeping it out of the data directory means the XML parsers, which walk
  `DDOBuilderV2/Items/`, `/Augments/`, etc., never have to know or care it exists.
- Before fetching, call GitHub's lightweight commits API:
  `https://api.github.com/repos/Maetrim/DDOBuilderV2/commits/main` (returns a small JSON
  object with a `sha` field — kilobytes, not megabytes) and compare against the stored
  marker. If they match, skip the 79MB download entirely and report "already up to
  date." If they differ (or the marker is missing / this is the first run), proceed
  with the full fetch in #1, then update the marker.
- Unauthenticated GitHub API calls are rate-limited to 60/hour per source IP. That's
  irrelevant here since this is only ever called on explicit user action (first run, or
  the "Update External Sources" button) — never polled automatically in the background.

### 3. When this runs

Same triggers as today, just a different mechanism underneath:
- **App startup**: only if `./DDOBuilderV2` doesn't exist yet at all (first run) — skip
  the SHA-check API call entirely in this case, since there's nothing to compare
  against; just fetch.
- **"Update External Sources" button** (`UpdateExternalSources()`): always runs the
  SHA-check first, then fetches only if it's actually behind.

This preserves the existing UX (`ensureDDOBuilderData()`'s current call sites in
`startup()` and `UpdateExternalSources()` don't need to change *what* triggers them,
only *how* the fetch itself works).

### 4. Downstream cleanup this unlocks

Since `git` was only ever needed for this one thing, removing it means:
- `install.sh`'s Homebrew/apt package lists no longer need `git` installed for this
  purpose specifically (it may still be worth keeping for general dev workflow, but
  it's no longer a hard runtime requirement for the app itself).
- `build-windows.ps1`'s Chocolatey package list can drop `git` too, **if** nothing else
  in the build needs it. Worth double-checking before removing: `go mod download`
  fetches modules via the Go module proxy (`proxy.golang.org`) by default, which serves
  pre-packaged module zips over plain HTTPS and does not need a local `git` binary for
  any publicly-available module (which covers everything this project currently
  depends on) — so this is very likely also git-free already, but should be verified
  with a real `git`-free Windows machine before removing the package from the install
  script, not assumed.
- The reachability checks in `install.sh` / `build-windows.ps1` (currently
  `git ls-remote https://...`) become a plain HTTPS `GET`/HEAD check against
  `codeload.github.com` (or reuse the same commits-API endpoint from step 2 above,
  which doubles as both a reachability check and the thing that will actually be called
  at runtime — closer to testing the real path).

---

## What this plan deliberately does NOT cover

- **Branch/tag pinning.** Always tracks `main`. If DDOBuilderV2 ever needs pinning to a
  specific release, that's a separate, later decision — not blocking this fix.
- **Partial/incremental updates.** The SHA-check in #2 avoids *wasted* re-downloads, but
  a real change still means a full 79MB re-fetch, not a diff — there's no equivalent of
  git's object-level delta transfer without actually vendoring git protocol logic
  (e.g. via `go-git`, a much heavier dependency for comparatively little gain here,
  since DDOBuilderV2 updates are infrequent and user-triggered, not a hot path).
- **Removing `git` from the Windows Chocolatey install list.** Flagged above as likely
  safe but *unverified* — needs confirming on an actual git-free Windows machine before
  acting on it, not assumed from Go module proxy behavior alone.

---

## Effort estimate

Small-to-medium. Core mechanism (fetch, stage, atomic swap) is straightforward stdlib
Go — most of the complexity is in the "don't leave things half-broken on failure"
handling, which is worth taking seriously but isn't large. The SHA-check optimization
is a second, separable piece that could ship slightly after the core mechanism if
sequencing matters, though given the 79MB cost it's recommended to land together.
