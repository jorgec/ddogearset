# DDO Gearset Optimizer — User Guide

Everything you need to go from a fresh download to a finished gearset.

No setup, no accounts, no internet connection required. Game data ships inside
the app.

---

## Contents

1. [Installing and starting](#1-installing-and-starting)
2. [The window at a glance](#2-the-window-at-a-glance)
3. [Your first gearset](#3-your-first-gearset)
4. [Stat priorities — the five tiers](#4-stat-priorities--the-five-tiers)
5. [Build settings](#5-build-settings)
6. [Reviewing and adjusting a result](#6-reviewing-and-adjusting-a-result)
7. [Filigrees](#7-filigrees)
8. [Using your own inventory](#8-using-your-own-inventory)
9. [Saving, loading, and sharing](#9-saving-loading-and-sharing)
10. [Where your files live](#10-where-your-files-live)
11. [Tips](#11-tips)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Installing and starting

### Windows

1. Download the Windows installer (`...-installer.exe`) from the
   [Releases page](https://github.com/jorgec/ddogearset/releases).
2. Double-click it and accept the default install location.
3. Launch **DDO Gearset Optimizer** from the Start menu.

**"Windows protected your PC"** — Windows SmartScreen shows this for
applications it hasn't seen many downloads of yet. If you downloaded from the
Releases page above, click **More info → Run anyway**.

**"Install Microsoft Edge WebView2 Runtime?"** — say yes. It's a standard
Microsoft component the app uses to draw its interface. Most Windows 11 machines
already have it.

### macOS (Apple Silicon)

1. Download the macOS `.zip` and double-click to extract.
2. Drag **DDO Gearset Optimizer.app** into **Applications**.
3. First launch only: right-click the app, choose **Open**, then **Open** again.
   (Double-clicking normally will show an "unidentified developer" warning.)

### Linux (64-bit)

1. Download and extract the release archive.
2. Run the `DDOGearsetOptimizer` executable. If it won't start, open its
   Properties and tick **Allow executing file as program**.

You'll need the WebKitGTK runtime, which most desktop distributions include.

### First launch

The app loads its item database in the background — a few seconds. The dot next
to the title reads **Ready** when it's done, and the **System Console** on the
right logs progress.

---

## 2. The window at a glance

The whole app is one screen. Nothing is hidden behind navigation.

```
┌──────────────────────────────────────────────────────────────────────┐
│  DDO Gear Optimizer   ● Ready        [Console] [Owned Items] [Search]│
├─────────────────┬──────────────────────────┬─────────────────────────┤
│  Gear │ Filigrees│                          │                         │
│                 │   Vellum Summary Scroll  │   System Console        │
│  Helmet         │                          │   (or Owned Items,      │
│  Necklace       │   Your stat totals,      │    or Item Search —     │
│  Trinket        │   set bonuses, and       │    pick from the         │
│  ...            │   every effect your      │    buttons up top)      │
│  Weapon 1       │   gear grants            │                         │
│  Weapon 2       │                          │                         │
├─────────────────┴──────────────────────────┤                         │
│ ▸ Configuration & Auto-Solver              │                         │
└────────────────────────────────────────────┴─────────────────────────┘
```

| Area | What it's for |
|---|---|
| **Left — Gear / Filigrees** | Your equipment. Two tabs: gear slots, and filigrees. |
| **Centre — Vellum Summary Scroll** | The results readout, plus saving and loading. |
| **Right — Console / Owned Items / Search** | Three panels; switch with the buttons in the title bar. |
| **Bottom — Configuration & Auto-Solver** | Click the header to expand. All build settings and the **Optimize Gear** button. |

---

## 3. Your first gearset

1. **Open the drawer.** Click **Configuration & Auto-Solver** at the bottom.

2. **Set your build profile.** Build Type, Weapon Style, and Character Level.
   Defaults are Melee / Two Weapon Fighting / level 34.

3. **Pick a starting preset.** Open **Stat Sets** and apply one that matches your
   character — *Melee Physical*, *Ranged Physical*, *Unarmed / Monk*,
   *Spell Caster (Fire / Evocation)*, *Warlock (Eldritch Blast)*, or
   *Mixed (Attack + Spell)*. This fills in sensible priorities that you can then
   edit. Starting from a preset is much easier than starting from nothing.

4. **Click Optimize Gear.** Watch the console. A solve typically takes a few
   seconds to a minute depending on how many priorities you set.

5. **Review the proposal.** Results appear in the centre panel. Nothing has been
   equipped yet — see the next step.

6. **Accept it, or don't.** Click **Accept All** to make the proposal your
   gearset, or cherry-pick individual slots. Until you accept, your own gear is
   untouched.

> **The app never overwrites your gear behind your back.** A solve produces a
> *proposal*. Your gearset only changes when you accept one — so you can solve
> repeatedly and compare without losing what you had.

---

## 4. Stat priorities — the five tiers

This is the part that decides everything, and it works differently from a
simple weighted list.

Priorities go into five lanes. **The solver satisfies them strictly in order** —
it completely finishes Tier 1 before it will spend anything on Tier 2, and no
lower tier is ever allowed to cost you a single point of a higher one.

| Tier | Name | Meaning |
|---|---|---|
| **1** | Must Maximize | Solved first. Nothing below can reduce these. |
| **2** | Maximize Next | Maximized without giving up any Tier 1. |
| **3** | Maximize If Free | Taken only when Tiers 1–2 are untouched. |
| **4** | Get At Least Some | Breadth first — one good source of each, then more. |
| **5** | Nice To Have | Only when convenient. |

Within a lane, **order matters too** — a stat higher in the lane outranks one
below it. Use the up/down arrows on each chip to rank them, and **move to tier ▾**
to shift a stat between lanes.

An empty lane is simply skipped.

### Practical advice

**Put two or three stats in Tier 1, not eight.** Tier 1 is an absolute
commitment. Loading it up means the solver spends the entire gearset satisfying
your first lane and has nothing left for anything else. Your real must-haves go
in Tier 1; everything else belongs further down.

**Tier 4 behaves differently on purpose.** It chases *breadth* — it would rather
give you one decent source of five different stats than a huge amount of one.
That's where things like resistances and utility stats belong.

### Caps

Click the small badge on a chip to set a **cap** — a point past which more of
that stat is worthless to you. Useful when you know a stat's ceiling (or where
your build stops benefiting), and it frees the solver to spend elsewhere once
you've hit it.

### Filigrees only count in Tier 1

Filigrees are considered when solving Tier 1 and nowhere else. If a stat only
appears in Tier 3, filigrees won't be chosen to serve it.

---

## 5. Build settings

All of these live in the **Configuration & Auto-Solver** drawer.

### Build Profile

| Setting | Notes |
|---|---|
| **Build Type** | Melee, Ranged, Caster, Tank. Changes which weapon styles are offered. |
| **Weapon Style** | Determines which weapon slots exist and which items qualify. |
| **Weapon Damage Type** | Melee only. Restricts your main hand to one damage type. |
| **Character Level** | Only items with a minimum level at or below this are considered. |
| **Armor Restriction** | Cloth, Light, Medium, Heavy, Docent, or Any. |

Weapon styles by build type:

- **Melee / Tank** — Two Weapon Fighting, Two Handed Fighting, Single Weapon
  Fighting, Sword and Board, Single Handed Weapon and Runearm
- **Ranged** — Bow, Repeating Crossbow, Great Crossbow, Dual Crossbow, Thrown,
  Shuriken
- **Caster** — Dual Caster, Stick and Orb, Stick and Runearm, Crossbow and
  Runearm, Quarterstaff, Two-Handed Weapon, Any

> Handwraps count as a Two Weapon Fighting style, but they occupy both hands —
> the solver leaves your off-hand empty when it equips them.

### Caster Configuration

Caster builds only: pick your damage elements and spell schools so the right
spellpower and DC stats are recognized.

### Equipment Constraints

- **Max Raid Items** — how many raid items the solver may use. `0` for a
  fully farmable set; `-1` for unlimited.
- **Exclude Gem of Many Facets** — turn it off if you don't have one.

### Artifact Configuration

- **Reserved Minor Artifact Slot** — which equipment slot your Minor Artifact
  occupies.
- **Minor Artifact Filigree Slots** — how many filigrees it holds. Set this to
  match your actual artifact; in game this is usually 1 to 5 depending on the
  item and its minimum level. Set it to `0` if you aren't wearing one.
- **Dinosaur Bone Artifact** — restricts the artifact to Dinosaur Bone items.

### Excluded Expansion Packs

Untick content you don't own and the solver won't propose items from it.

### Solver Settings

**Search time** is the total budget in seconds. If the results panel afterwards
says a stage hit its time limit before proving optimality, raise it and re-run —
that message means the answer is good but not *proven* best.

---

## 6. Reviewing and adjusting a result

### The Gear tab

Every slot, with the item in it. Click an item name to see its full details;
click an empty socket to browse and equip something yourself.

Hovering a slot reveals two buttons:

- **⚙ Find alternatives** — other items that fit this slot, ranked, so you can
  see what you're giving up by swapping.
- **✕ Clear** — empty that slot.

Anything you place by hand is **pinned**: the next solve keeps it and builds
around it.

### The buttons above the slots

| Button | What it does |
|---|---|
| **Calculate** | Recomputes your stat totals from exactly what's equipped now. No solving, no proposals — fast. |
| **Check Inventory** | Marks each equipped item green or red against your loaded Trove inventory. |
| **Clear** | Empties every slot. Your settings and priorities are kept. |
| **New** | Starts over — clears gear *and* settings. Asks first. |

### The Vellum Summary Scroll

The centre panel, showing what your gear actually produces:

- **Priority effects** — your prioritized stats and which items grant them
- **All effects** — everything your gearset gives you, including things you never asked for
- **Set bonuses** — active sets and their piece counts
- **Duplicated stat sources** — where two items grant the same thing and one is
  being wasted. Worth checking; it's usually a free slot.

---

## 7. Filigrees

The **Filigrees** tab sits next to **Gear**, in the same panel.

There are two groups: **Sentient Weapon** (10 slots) and **Minor Artifact**
(however many you set in Artifact Configuration).

Each slot shows one of:

- **LOCKED** — you chose this one; the solver must keep it
- **AUTO** — the solver picked it; free to change on the next solve
- **Empty** — click to choose a filigree

In the picker, search by name or narrow by set with the dropdown. Click
**Unlock** on a locked slot to hand it back to the solver.

**Stacking rules:**

- The same filigree twice on the same item — not allowed
- The same filigree on the weapon *and* the artifact — allowed, and it stacks

After changing filigrees by hand, hit **Calculate** to see the updated totals
without a full re-solve.

---

## 8. Using your own inventory

If you use **Trove** to export your characters' inventory to CSV, the app can
limit itself to gear you actually own.

1. Click **Owned Items** in the title bar.
2. Click **Load Trove CSV...** and pick your export.
3. The panel lists every row it could match to a real item. Augments, filigrees,
   and unrecognized rows are ignored.
4. To actually restrict the solver, open **Owned Items (Trove Import)** in the
   configuration drawer and switch the restriction **on**.

Loading the file alone changes nothing — the restriction is opt-in, so you can
browse your inventory without constraining a solve.

With a CSV loaded, **Check Inventory** on the Gear tab badges each equipped item
green (owned) or red (not owned). Matching is exact and case-sensitive, on
purpose: it matches precisely what the solver does, so nothing shows green that
the solver would then refuse to use.

### Item Search

**Search** in the title bar finds every source of a given stat across the whole
catalog — useful for "what actually grants Melee Power at level 32?" Each result
name links to its DDO Wiki page.

---

## 9. Saving, loading, and sharing

### Save

Type a name in the centre panel and click **Save**. This does two things at
once:

1. Stores the build in the app's database, and
2. Writes a timestamped `.ddogearset` file to your `gearsets` folder.

The toast tells you where the exported copy went. Every export is uniquely
timestamped, so saving repeatedly never overwrites an earlier one.

### Open DB

Browses everything you've saved: name, date, build type, and slot count, with
**Load** and **Delete** on each row. This is the normal way back to a build.

The database also keeps a history of your solve runs.

### Load

Opens a file picker for `.ddogearset` and `.json` files — this is how you take a
gearset from someone else, or restore an older export. It restores the full
configuration along with the gear, then recalculates.

Those files are plain JSON, so you can open one in a text editor if you're
curious what's inside.

---

## 10. Where your files live

On **Windows**, press `Win+R` and paste `%APPDATA%\DDOGearsetOptimizer`.

| File | What it is |
|---|---|
| `app.db` | **Your builds and history.** |
| `gearsets\` | Exported `.ddogearset` files. |
| `catalog.db` | Game data. Replaced whenever you update the app. |

On macOS this folder is `~/Library/Application Support/DDOGearsetOptimizer`; on
Linux, `~/.local/share/DDOGearsetOptimizer`.

> **Back up `app.db` if your builds matter to you.** It's the one file nothing
> can regenerate — everything else is either rebuilt by the app or re-downloaded
> with an update. Copying it somewhere safe occasionally is enough.

---

## 11. Tips

1. **Start from a preset and edit it.** Much faster than building a priority
   list from a blank slate, and the presets encode reasonable defaults.

2. **Keep Tier 1 small.** Two or three stats. Tier 1 is absolute — a crowded
   Tier 1 consumes the whole gearset.

3. **Solve twice to price your raid gear.** Once with **Max Raid Items = 0**,
   once unlimited. The difference tells you exactly what the raiding is buying.

4. **Pin what you already own, then re-solve.** Equip your real best-in-slot
   items by hand and let the solver optimize around them. That's a far more
   useful answer than a theoretical set you'll never assemble.

5. **Read "Duplicated Stat Sources".** It's the quickest win in the app —
   overlapping items mean a slot doing nothing.

6. **Check the last-run time.** If a stage ran out of time, the answer is good
   but unproven. Raise the search time and run again.

7. **Save before big changes.** Saves are cheap and the build browser makes it
   easy to keep several variants side by side.

---

## 12. Troubleshooting

**Windows says "Windows protected your PC."**
SmartScreen doesn't recognize the app yet. **More info → Run anyway**, provided
you downloaded from the official Releases page.

**The app opens but nothing loads / stays on "Parsing".**
Check the System Console for errors. Restarting usually clears it. If the
console reports a catalog problem, reinstalling the app restores `catalog.db`
without touching your builds.

**Optimize Gear does nothing.**
You need at least one stat priority. Open **Stat Priorities** and add one, or
apply a preset.

**No items in a weapon slot.**
Your filters are likely too tight — a high Character Level combined with an
armor restriction, excluded packs, or an owned-items restriction can empty the
pool. Relax them one at a time.

**Results look wrong for my build.**
Remember the app has no idea what your character is. It optimizes precisely what
you asked for. If the answer looks odd, the priority list is usually the reason —
check the tiers, and check that a stat you assumed was Tier 1 is actually there.

**A solve is very slow.**
Too many Tier 1 stats is the usual cause. Move the non-essential ones down.

**My builds disappeared.**
They're in `app.db` (see [above](#10-where-your-files-live)). If that file was
moved or deleted, restore it from a backup — nothing else can rebuild it.
