# DDO Gearset Optimizer — User Guide

> A desktop app that uses Integer Linear Programming (ILP) to find the mathematically optimal gear set for your DDO character build, with full support for manual overrides, sentient jewels, and filigrees.

---

## Table of Contents

1. [Overview](#overview)
2. [Launching the App](#launching-the-app)
3. [Tab-by-Tab Walkthrough](#tab-by-tab-walkthrough)
   - [Auto Solver](#1-auto-solver)
   - [Gearset Editor](#2-gearset-editor)
   - [Filigrees](#3-filigrees)
   - [Summary](#4-summary)
4. [The `.ddogearset` File Format](#the-ddogearset-file-format)
5. [Tips & Best Practices](#tips--best-practices)

---

## Overview

DDO Gearset Optimizer reads your character's build parameters (build type, weapon style, stat priorities, etc.) and automatically selects the mathematically best combination of items from all available gear in DDOBuilderV2. You can:

- **Auto-solve** a full 14-slot gearset in one click
- **Manually pin** specific items or augments and let the solver fill in the rest
- **Pre-fill filigrees** for your Sentient Weapon (10 slots) and Minor Artifact (1–5 slots)
- **Save and load** gearsets as `.ddogearset` files that fully restore all parameters

---

## Launching the App

Build and run from the project root:

```bash
wails dev         # development mode (hot reload)
wails build       # production binary
```

The app opens a desktop window with a tabbed interface. On first launch, the item/augment/filigree caches load in the background (watch the Status Console at the bottom for progress).

### Updating External Data

Click **"Update External Sources"** in the Auto Solver tab to run `git pull` on the DDOBuilderV2 repository and hot-reload all item, augment, and filigree data without restarting.

---

## Tab-by-Tab Walkthrough

### 1. Auto Solver

This is the primary configuration tab. Set all your build constraints here before running the solver.

#### Build Identity

| Field | Options | Description |
|---|---|---|
| **Build Type** | Melee, Ranged, Caster, Tank | Determines which weapon styles are available and how items are filtered |
| **Weapon Style** | TWF, THF, SWF, S&B, Bow, Crossbow types, Thrown, Shuriken, None | Controls which weapon slots are activated and which items are eligible |
| **Offhand Style** | Empty Hand, Orb, Buckler, Runearm | Only shown for Single Weapon Fighting builds |
| **Character Level** | 29–36 | Maximum Minimum Level (ML) cap for items. Only items with ML ≤ this value are considered |
| **Armor Restriction** | Any, Cloth, Light, Medium, Heavy | Filters items to only include armor of this type or lighter |

#### Checkboxes

| Field | Description |
|---|---|
| **Swashbuckling** | Enables buckler off-hand slot for swashbuckler builds |
| **Runearm** | Adds a Runearm slot to the solve |
| **Exclude Gem of Many Facets** | Removes the GoMF from consideration (useful if you don't have it) |
| **Dinosaur Bone Artifact** | Forces the Minor Artifact slot to be filled by a Dinosaur Bone item only |

#### Caster Options

- **Spell Powers**: Multi-select for your active spell power types (e.g., `Fire`, `Force`, `Positive`)
- **Spell Schools**: Multi-select for DC schools (e.g., `Necromancy`, `Evocation`)

#### Stat Priorities

This is the heart of the optimizer. Add stats you care about with a **weight from 1–100**.

- Weight `100` = highest importance
- Weight `1` = very low importance
- The solver maximizes a weighted sum — higher weights mean the solver will sacrifice lower-priority stats to gain more of this stat

**To add a stat:**
1. Type the stat name (e.g., `Melee Power`, `Fortification`, `PRR`)
2. Set the weight (1–100)
3. Click **Add** or press **Enter**

Click any existing stat in the list to edit its name and weight. Click the × to remove it.

#### Constraints

| Field | Description |
|---|---|
| **Max Raid Items** | Maximum number of raid items the solver may pick (0 = no raid items, -1 = unlimited) |
| **Minor Artifact Filigree Slots** | How many filigree slots your Minor Artifact has (1–5, see rules below) |
| **Reserved Minor Artifact Slot** | Which equipment slot is taken by your Minor Artifact (Ring, Trinket, etc.) |

**Filigree slot rules:**
- Epic Voice of the Master → 1 slot
- ML 30 → 3 slots
- ML 31 → 4 slots
- ML 33+ (Myth Drannor / Den of Vipers) → 5 slots; ML 34+ (Chill of Ravenloft) → 5; ML 35 (Demogorgon) → 5

#### Excluded Expansion Packs

Toggle expansions off to prevent the solver from picking items from those packs. Useful if you don't own certain content.

#### Running the Solver

Click **Run Optimization**. The solver may take 30–120 seconds for complex configurations. Progress is shown in the Status Console. When complete, the app automatically switches to the **Gearset Editor** tab.

---

### 2. Gearset Editor

Review and manually adjust the solved gearset. The left panel shows equipped items per slot; the right panel shows available alternatives for the selected slot.

#### Equipment Slots

Each slot shows:
- The currently equipped item name
- Its minimum level
- **Augment slots** — drop-downs to assign specific augments to each augment slot on that item

Click a slot row to select it and browse alternatives on the right panel.

#### Alternatives Panel

Shows alternative items for the selected slot, ranked by solver score. Click any item to swap it in.

#### Augment Assignment

When an item is selected, its augment slots appear. Each slot has a color (e.g., Yellow, Blue, Red) and a drop-down showing compatible augments. Selections are persisted as `pre_filled_augments` — the next time you run the solver, those augments are locked in and the solver builds around them.

> **Tip:** You can also get augment recommendations. The solver will only suggest an upgrade if the recommended augment provides a greater benefit than your current selection.

#### Calculate Stats Button

Click **Calculate Stats** to evaluate all effects from the current manual selections (items + augments + filigrees) without re-running the full optimization. Results populate in the **Summary** tab instantly.

#### Clear Button

Resets all equipment slot assignments.

---

### 3. Filigrees

Manage filigree assignments for your Sentient Weapon and Minor Artifact. This tab is independent of item identification — it uses your configuration settings directly.

#### Weapon Filigrees (10 slots)

10 slots for your Sentient Weapon filigrees. Each slot can be:
- **AUTO** — the solver picked this filigree as optimal
- **Manually assigned** — type to search by name or filter by Set Name

#### Artifact Filigrees (1–5 slots)

The number of slots matches **Minor Artifact Filigree Slots** from your configuration.

#### Filigree Picker

- Type in the search box to filter by filigree name
- Use the **Set Filter** dropdown to show only filigrees from a specific set (e.g., "Primal Scream", "Through the Mists")
- The AUTO badge indicates a solver-recommended filigree

#### Stacking Rules

- **Same filigree on the same item** → not allowed (the solver enforces this)
- **Same filigree on weapon AND artifact** → allowed and fully stacks
- **Same filigree from different sets on the same item** → allowed and stacks (unless noted otherwise)

---

### 4. Summary

A comprehensive breakdown of your full gearset.

#### Gearset Name

Enter a name for this gearset (e.g., `Sentinel`, `Fire Sorc`). This becomes the prefix in the saved filename.

#### Priority Effects (Top Section)

Lists all effects that match your stat priorities, sorted by weight (highest first). Shows which item/filigree/augment grants each effect and the total value.

#### All Effects

A full alphabetical list of every effect granted by your gearset — items, augments, set bonuses, and filigrees — grouped by stat name.

#### Set Bonuses

Active set bonuses from equipped items and filigrees, showing piece count and granted effects.

#### Load / Save

- **Load** — opens a file picker accepting `.ddogearset` and `.json`. Fully restores the configuration parameters (build type, priorities, etc.) and the result into the UI, then automatically recalculates
- **Save Output** — saves the current gearset as a `.ddogearset` file. The filename is auto-generated as:

```
<Name>_<BuildType><WeaponStyle>Gearset_<YYYYMMDDHHMMSS>.ddogearset
```

If no name is given:
```
<BuildType><WeaponStyle>Gearset_<YYYYMMDDHHMMSS>.ddogearset
```

Every save is uniquely timestamped — no overwrites.

---

## The `.ddogearset` File Format

`.ddogearset` files are plain JSON (rename to `.json` to inspect in any editor). Structure (v1.2):

```json
{
  "version": "1.2",
  "gearset_name": "My Fire Sorc",
  "saved_at": "2026-08-04T01:00:00Z",
  "config": {
    "gearset_name": "My Fire Sorc",
    "max_levels": [34],
    "build_type": "Caster",
    "weapon_style": "None",
    "stat_priorities": { "Fire Spell Power": 100, "Universal Spell Power": 80 },
    "armor_restriction": "Cloth",
    "minor_artifact_filigree_slots": 5,
    "reserved_minor_artifact_slot": "Ring",
    "raid_item_limit": 1,
    "pre_equipped": { "Helmet": "Legendary Crest of the Sun Soul" },
    "pre_filled_augments": { "Helmet|0": ["Deadly VII"] },
    "pre_filled_filigrees": {
      "weapon": ["Spines of the Manticore: +6 Fire Spell Power", "..."],
      "artifact": ["Through the Mists: +3 Fire SP", "..."]
    },
    "excluded_packs": ["Sharn"],
    "...": "..."
  },
  "result": {
    "success": true,
    "timeTaken": 45.3,
    "gearSet": { "Helmet": "Legendary Crest of the Sun Soul", "..." },
    "realizedStats": { "Fire Spell Power": 342 },
    "activeSets": ["Feywild Frenzy (3pc)", "..."],
    "filigrees": { "weapon": ["..."], "artifact": ["..."] },
    "allEffects": { "Fire Spell Power": ["Item A: +50", "..."] }
  }
}
```

When loaded, all `config` fields are restored to the UI, and `result` is immediately displayed in the Summary tab.

---

## Tips & Best Practices

1. **Start with high-weight priorities only.** Too many equal-weight stats can make the solver take much longer. Start with 2–3 stats at high weight, then add secondary stats at lower weights.

2. **Use Raid Item Limit = 0** for a farmable-only gearset, then compare against Raid Item Limit = 2 to evaluate the upgrade delta.

3. **Lock your best-in-slot items first.** Use the Gearset Editor to pin items you already own (pre_equipped), then re-run the solver to fill the rest optimally.

4. **Name your gearsets** before saving — the name prefix makes it trivial to find the right file when you have many iterations.

5. **Filigrees are solver-recommended by default.** Review the Filigrees tab after solving — the AUTO badges show what the ILP chose. Override any slot you want to change, then click **Calculate Stats** to see the updated breakdown without re-solving.

6. **Update External Sources regularly.** DDOBuilder updates its data files frequently. Hit the Update button before major solves.
