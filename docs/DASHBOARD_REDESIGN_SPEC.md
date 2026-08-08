# Dashboard Redesign — implementation notes

**Status:** Implemented (0.4.0).

**Source of truth:** `docs/DDO_Gear_Optimizer_Design_Spec.pdf`. That document
owns the *design* (palette, typography, zones, component treatments); this one
records how it was mapped onto the existing codebase and every place the
implementation had to decide something the PDF didn't cover.

## Decisions taken during implementation

1. **The Belt switches the right column only** (explicit instruction). The
   design spec consolidates all six old tabs into permanently-visible zones,
   yet its mockup still shows a nav belt. Reconciled as: Gear Sockets, the
   Vellum Scroll and the configuration drawer are *always* live, and the belt
   swaps only between the three right-column readouts the spec's §5 zone table
   itself assigns to that column (Console / Owned Items / Item Search).
2. **Everything stays reactive** (explicit instruction). Panels that aren't
   fronted are hidden with `class:hidden`, **not** unmounted via `{#if}`. Both
   the right column and the drawer's two sections follow this rule, so
   switching never drops scroll position, an in-flight search, a loaded CSV or
   a half-filled configuration. This is a real behaviour change from the old
   tab system, which destroyed and recreated each view on every switch —
   `OwnedItems.svelte` had a comment explaining that it kept state in a module
   store specifically to survive that; the store is still correct, but for a
   different reason now (it is shared with the solver form), and the comment
   was corrected rather than left stale.
3. **Ornamentation: restrained, with texture hooks.** The mockup shows
   leather, wood grain, ornate gold frames and parchment. No image assets for
   those exist, and CSS-gradient imitations of photographic material tend to
   read as cheap. Implemented the full palette, typography, gold inlays,
   carved-stone borders, recessed sockets and console glow — but no faux wood
   or leather. Four CSS custom properties in `style.css`
   (`--texture-belt`, `--texture-panel`, `--texture-vellum`, `--texture-stone`)
   are composited into the relevant surfaces and currently resolve to subtle
   procedural gradients; dropping in real artwork later is a one-line
   `url(...)` override per variable, with no markup changes. *This question was
   put to the user and dismissed rather than answered, so the recommended
   option was taken — it is the cheapest one to revisit.*
4. **Dark is the only theme.** `darkMode: ["class"]` was removed rather than
   maintaining a light/dark pair for a design that only ever ships dark. The
   semantic tokens (`background`, `card`, `border`, …) now *are* the dark
   values, which is what flipped the whole app over at once: ~4,300 lines of
   Svelte across 17 components mostly consume those tokens, so only about 40
   hardcoded `slate-*`/`amber-*`/`white` spots needed hand-fixing.
5. **Fonts are bundled, not linked.** Cinzel / Inter / Fira Code ship via
   `@fontsource` (latin subsets only). A Google Fonts `<link>` would silently
   degrade to system fonts whenever the machine is offline, and this is an
   offline desktop app.

## Zone mapping (design spec §5)

| Zone | Width | Component | Notes |
|---|---|---|---|
| Title bar | — | `App.svelte` | Logo, Cinzel title, status **crystal** (§4.1) |
| The Belt | — | `App.svelte` | 3 studs, icons + text, switches the right column |
| Left | 25% | `GearsetEditor` | Sockets (§4.2) |
| Center | 45% | `Summary` | Vellum scroll + pips (§4.3) |
| Right | 30% | `StatusConsole` / `OwnedItems` / `ItemSearch` | §4.4 |
| Bottom drawer | collapsible | `JobConfigurationForm` / `FiligreeEditor` | §5 |

Widths are `grid-cols-[5fr_9fr_6fr]` — exactly 25/45/30 — collapsing to a
single stacked column below `lg`.

## Component notes

### Gear Sockets (§4.2)
Slots render as recessed sockets (`.socket`, inset shadow) reading
**"Socket Empty"**, or **"Engrave Relic"** for the two weapon slots. A filled
socket switches to `.socket-filled` with a gold-tinted rim, an item-type glyph,
and the item name in a **rarity colour**.

Rarity is derived from data that genuinely exists rather than a fabricated
field: DDO names items `"Legendary …"` / `"Epic …"`, and minimum level is the
authoritative fallback. Legendary/ML≥30 → Artificer Gold; Epic/ML≥20 → purple
(the spec names purple for Epic explicitly); everything else → vellum.

The item picker and item detail **moved out of a side pane into a modal**
(§6: blurred backdrop, Obsidian body). The old side-by-side `w-1/2` layout
cannot fit a 25%-wide column, and the spec asks for exactly this modal
treatment anyway.

### Vellum Scroll (§4.3)
Burnt Vellum (`#2B271D`) panel. Set bonuses render as lit/dim pips.

**Data caveat worth knowing:** the solver's `activeSets` lists every active
*tier*, not every set — a 4-piece Zarigan's appears three times, as
`(2-piece)`, `(3-piece)` and `(4-piece)`. Rendering one row per entry would
claim three separate sets were active. They are collapsed to one row per set at
its highest active tier.

The pip *denominator* (how many pieces the set tops out at) is not in the
result payload, so it is looked up per set via the existing `GetSetBonus` RPC
and cached. If that lookup fails or the set is unknown, the row falls back to
`total == active` (all pips lit) rather than inventing a denominator.

### Arcane console (§4.4)
`.arcane-console`: Fira Code, blue-tinted border, outer glow, and a CSS
scanline overlay (`::after`, `pointer-events: none` so it never eats clicks).

### Owned Items (§4.4)
The spec asks for "a condensed table view". A real five-column `<table>`
(Name/ML/Pack/Character/Location) does not fit a 30%-wide column, so each row
folds into a two-line entry — name + ML above, provenance beneath. The filter
input gets the spec'd glowing bottom border on focus (`.trove-filter`).

## Behaviour changes

- `currentTab` (6 values) → `rightPanel` (3 values) + `drawerOpen`, both in
  `store.ts`. `drawerOpen` persists to `localStorage`, defaulting open.
- `JobConfigurationForm` used to run `$currentTab = 'editor'` after a
  successful solve to reveal the result. The sockets and summary are now always
  on screen, so there is no tab to jump to — it **collapses the drawer**
  instead, which is what actually reveals the result.

## Known gaps

- The native app window could not be screenshotted during development (screen
  recording permission not granted), so visual verification was done in the
  Vite preview with a **real saved `.ddogearset` payload** injected into
  `resultStore`. That exercises the real data shape and the real rendering
  path, but the Wails RPC layer is unavailable in a plain browser — meaning the
  set-bonus pip *denominators* (which need `GetSetBonus`) were only observed on
  their fallback path. Worth a look in the built app.
- The four texture hooks are procedural gradients, not artwork (decision 3).
