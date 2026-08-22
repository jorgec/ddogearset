# Why loading a Trove CSV sometimes did nothing

**Reported:** clicking to load a CSV Trove file sometimes does not work — nothing happens.
**Investigated & fixed:** 2026-08-18. Two independent causes, both reproduced before being fixed.

The symptom was one sentence, but it covered two different failures with the same
appearance: a file that never arrived, and a file that arrived and matched nothing.
Both were silent — no toast, no console line, no error — which is why neither had a
bug report with anything actionable in it.

---

## Cause 1 — the file input was garbage-collected mid-dialog

### What the code did

All three file loaders (the two Trove ones and gearset loading) used the textbook
pattern:

```js
const input = document.createElement('input');
input.type = 'file';
input.onchange = (e) => { /* read the file */ };
input.click();          // <- input is never referenced again
```

The moment that function returns, `input` is unreachable from JavaScript: it is not
in the document, and no variable holds it. Only the pending native Open panel is
still interested in it.

### Why that breaks

On macOS the webview is WKWebView, so this runs on JavaScriptCore, and JSC is free
to collect that element while the panel is still on screen. The pending file chooser
does not keep it alive. When the element goes, the chooser goes with it — so the file
the user picks arrives nowhere. No `change` event fires, nothing throws, nothing is
logged.

It was intermittent because it was a race against a garbage collector. Two variables
decide it: how long the panel stays open (how long the user hunts for the file), and
how much the page is allocating meanwhile. The app always allocates —
`StatusConsole.svelte` polls `GetSystemLogs()` once a second and the log slice is never
trimmed, so every tick marshals the whole, growing array across IPC and rebuilds it in JS.

### Evidence

A Swift WKWebView harness whose `WKUIDelegate` **replaces `NSOpenPanel`**, so the
dialog is fully scripted and its dwell time is a parameter — no human, no real file
dialog. It runs the app's exact pattern, on macOS 26.5.2:

| dwell in dialog | event ordering | result |
|---|---|---|
| ≤ 2s | `CLICK → CHANGE_FIRED → READ_OK → COLLECTED` | loads (collected harmlessly, after use) |
| 3s | `CLICK → COLLECTED` | **dropped — 6 of 6 trials** |
| 5s | `CLICK → COLLECTED` | **dropped** |

`COLLECTED` comes from a `FinalizationRegistry` on the input, so the collection is
observed directly rather than inferred. In the failing runs it fires *before* the
file is handed back, and no `change` event ever follows.

### The fix

`frontend/src/lib/services/filePicker.ts` — one `pickFile()` for the whole app, which
keeps the element reachable for as long as the dialog can be open by doing both of:

1. putting the input in the document, and
2. holding a module-level reference to it.

Either alone was verified sufficient in the harness; doing both costs nothing. The
reference is released and the element removed only once an outcome is known.
Cancellation comes from the `cancel` event (WebKit 16.4+, WebView2 113+); a
focus-based cancel fallback was deliberately rejected, because it cannot tell "the
user cancelled" from "the user is still browsing" and would reintroduce exactly this
silent drop.

Callers: `OwnedItems.svelte`, `JobConfigurationForm.svelte`, `Summary.svelte`
(`loadGearset` had the same defect — gearset loading could silently fail the same way).

Re-verified with the shipped `filePicker.ts` ported verbatim into the harness:
loads correctly at 5s and 8s dwell under deliberately heavy allocation pressure, and
a cancelled pick followed by a second pick works.

---

## Cause 2 — a CSV that loaded, matched nothing, and said nothing

`loadCaches()` runs in a goroutine from `startup()` while the UI is already clickable.
`GetTroveOwnedItems` read `itemsByName` straight through that window, so a CSV loaded
in the first moments of a launch matched an empty catalog and returned:

```
GetTroveOwnedItems -> success=true totalRows=3 items=0 errorMessage=""
```

Success, with an empty list — which the Owned Items screen renders as its "load a CSV
to see your items" empty state. Indistinguishable, on screen, from the click having
done nothing at all.

The window is ~0.5s (measured: 13ms to read the 58MB bundled catalog, 23ms for
`compareCatalogVersions`, 461ms for `loadCaches`), so this was the rarer of the two —
but it also came with a real data race, confirmed by `go test -race`:

```
WARNING: DATA RACE
  Write at 0x... by goroutine 17:  loadCaches()          app.go:233   (a.itemsByName = ...)
  Previous read by goroutine 18:   GetTroveOwnedItems()  trove_inventory.go:213
```

plus a second race on `addLog`'s unbounded `a.logs` slice, appended from every RPC
goroutine (Wails dispatches each bound call in its own goroutine) while
`GetSystemLogs` hands the live slice to the JSON marshaller once a second.

### The fix

- `App.cacheReadyCh` (app.go) closes when `loadCaches` finishes, on every exit path.
  `GetTroveOwnedItems` waits on it before matching. That removes the empty-cache
  window **and** gives the reads a happens-before edge against the writes, so the race
  is gone rather than merely unlikely.
- If the gate opens with an empty catalog — `loadCaches` genuinely failed — the call
  now returns `Success: false` with a message pointing at the System Console, instead
  of an empty list. A CSV whose names simply match nothing still succeeds with zero
  items; those two cases are no longer conflated.
- `addLog` and `GetSystemLogs` take a mutex, and `GetSystemLogs` returns a copy.

Covered by `trove_cachegate_test.go`, including a `-race` regression test.

---

## Ruled out

- **IPC payload size.** The suspicion was that a large CSV — sent *twice*, concurrently,
  by `troveImport.ts` — could be dropped by the Wails bridge. It cannot: WKWebView's
  `postMessage` delivered a 50MB payload intact in 23ms in the harness. Note that
  Wails' own `calls.js` swallows a send failure with only a `console.error` and has no
  default timeout, so if this ever *did* fail the button would sit disabled on
  "Loading…" forever. Real hazard, not this bug.
- **The `accept=".csv"` filter hiding the file.** Wails' `runOpenPanelWithParameters`
  (WailsContext.m) never applies `accept` to the `NSOpenPanel` at all, so every file
  stays selectable on macOS.

## Follow-up, same day: Trove import moved to drag-and-drop only

Both Trove file-picker buttons were removed. Importing is now done by dragging the
CSV onto the Owned Items panel or the configuration drawer's Trove section, which
changes the failure surface rather than just patching it:

- **No file input in the flow at all**, so Cause 1 cannot recur on this path.
  `filePicker.ts` remains, and remains necessary, for gearset file loading.
- **The CSV never crosses the IPC bridge.** Wails' `OnFileDrop` hands the frontend an
  absolute path; the new `LoadTroveFromPath` RPC reads and parses the file once in Go.
  The old pair of content-taking RPCs (`LoadTroveInventory`, `GetTroveOwnedItems`) sent
  the whole file twice, concurrently, and parsed it twice; both are removed.
- **A drop works on an unfocused window**, which sidesteps the still-open issue below
  for this flow specifically — there is no first click to lose.

Verified in WebKit that the design's load-bearing assumption holds: with
`--wails-drop-target: drop` set inline on the zone container, the computed value
inherits to children (`drop`) — so a drop on the text inside the zone counts, which is
what Wails' `getComputedStyle` hit-test requires — while elements outside the zone
compute to empty and are correctly not targets.

The trade-off, accepted deliberately: there is now no keyboard-accessible way to import
a CSV, and no way to import without a Finder window open.

## Still open (not fixed here)

**The first click on an unfocused window is swallowed by macOS.** (Trove import no
longer depends on a click at all — see the follow-up above — but every other control
still does.) `WKWebView`'s
`acceptsFirstMouse:` returns `false` (verified on macOS 26.5.2; a native `NSButton`
returns `true`), so AppKit uses that click to activate the window and never delivers
it to the page. Coming back from Finder or Trove and clicking straight onto "Load
Trove CSV…" therefore does nothing the first time — standard macOS behaviour, the same
as Safari, and it is very likely part of what was being reported.

It cannot be fixed from Go or JavaScript: the click never reaches the webview. It
needs an Objective-C override on the webview that Wails v2 does not expose — but it
does **not** need a Wails fork. `WailsWebView` (Wails' WKWebView subclass) does not
implement `acceptsFirstMouse:`, so the app can add one at runtime from its own cgo:

```objc
static BOOL AcceptsFirstMouseYES(id self, SEL _cmd, NSEvent *e) { return YES; }
class_addMethod(objc_getClass("WailsWebView"), @selector(acceptsFirstMouse:),
                (IMP)AcceptsFirstMouseYES, "B@:@");
```

Verified end-to-end against a non-key window in an inactive app: the page's click
count went 0 → 1 with the patch applied. Note it must target the subclass — WKWebView
itself implements the method (returning NO), so `class_addMethod` on WKWebView fails.
Not applied: it makes click-through global, and the app's only destructive action
(deleting a build) is already a two-step toast confirmation, so the risk is low but
the change is a behaviour choice rather than a bug fix.

---

## Re-running the harness

`scratchpad/wk/harness.swift` (session scratch — copy it somewhere durable if it is
still wanted):

```
swiftc -o harness harness.swift -framework Cocoa -framework WebKit
./harness detached 5        # the old pattern: silently drops the file
./harness shipped 5         # filePicker.ts as shipped: loads
./harness shipped 5 cancel  # cancel, then a second pick
./harness firstmouse        # acceptsFirstMouse
./harness postmessage       # IPC payload sizes up to 50MB
```
