# Technical Specification — Phase 11: Solver Parameter Adherence & Smart Alternatives

**Branch:** `feature/solver-parameter-adherence`
**Scope:** `app.go`, `python/optimizer.py`, `python/solver.py`, `frontend/`

---

## 1. Overview and invariants

This phase ensures that the gear optimizer and the alternatives generator strictly respect user-defined parameters, with a primary focus on `max_level` and `excluded_packs`. Furthermore, the alternatives generator must become aware of weapon style constraints to prevent suggesting invalid combinations (e.g., suggesting an orb when a two-handed weapon is equipped, or suggesting a two-handed weapon for the offhand slot).

### 1.1 Non-negotiable invariants

| ID | Invariant |
|---|---|
| **INV-1** | **Strict Level Capping:** The solver and alternatives generator must NEVER consider or return an item whose Minimum Level (ML) exceeds `config.max_level`. This is a hard drop during the initial ETL/data load phase in Python. |
| **INV-2** | **Strict Pack Exclusion:** Any item belonging to a pack listed in `config.excluded_packs` must be completely omitted from the candidate pool. |
| **INV-3** | **Alternative Style Adherence:** When requesting alternatives for a weapon or offhand slot, the suggestions must strictly adhere to the user's `weapon_style` and `offhand_style` parameters. |
| **INV-4** | **Uniform Application:** Restrictions must apply equally to base items, augments, and filigrees (where applicable). |

---

## 2. Solver Strict Parameter Adherence

Currently, the solver may occasionally leak items that violate max level or pack restrictions if they are part of pre-equipped items or if the filtering logic is applied too late in the pipeline.

### 2.1 Filtering at the Source
In `python/optimizer.py` (or equivalent data ingestion module):
- The `load_corpus` function (or wherever items are parsed) must accept `max_level` and `excluded_packs` as arguments.
- Any item where `item['ml'] > max_level` must be discarded from the general candidate pool.
- Any item where `item['pack'] in excluded_packs` must be discarded from the general candidate pool.
- **CRITICAL EXEMPTION:** Items, augments, and filigrees that are explicitly passed in the `pre_equipped`, `pre_filled_augments`, and `pre_filled_filigrees` payloads MUST bypass these filters and be injected into the valid pool. The solver must respect the user's manual choices unconditionally.
- This ensures the ILP model only considers valid items for empty slots, while still honoring the user's manual overrides (e.g., an augment from an excluded pack that the user already owns).

### 2.2 Pre-equipped Exemption
If the user's `pre_equipped` items violate `max_level` or `excluded_packs`:
- The solver must gracefully accept the payload and work around the user's choices.
- The UI allows the user full freedom to manually equip any item they want from any level or pack. The hard rules only restrict what the *solver* is allowed to automatically fill into empty slots or suggest as alternatives.

---

## 3. Smart Alternatives Generation

The alternatives endpoint (`AlternativesPayload` introduced in Phase 10) must apply the exact same strict filtering logic. However, weapon slots require additional heuristic filtering based on the build's combat style.

### 3.1 Weapon Style Constraints Matrix
When suggesting alternatives for `Weapon1` (Mainhand) or `Weapon2` (Offhand), the following constraints must be enforced based on `config.weapon_style` and `config.offhand_style`:

| `weapon_style` | `offhand_style` | Valid `Weapon1` types | Valid `Weapon2` types |
|---|---|---|---|
| Two Handed Fighting | None | Two-Handed Melee Weapons | (Locked/None) |
| Two Weapon Fighting | (Implied Weapon) | One-Handed Melee Weapons | One-Handed Melee Weapons |
| Single Weapon Fighting | Orb | One-Handed Melee Weapons | Orbs |
| Single Weapon Fighting | Runearm | One-Handed Melee Weapons | Runearms |
| Single Weapon Fighting | None | One-Handed Melee Weapons | (Locked/None) |
| Sword and Board | Shield (Buckler/Small/Large/Tower) | One-Handed Melee Weapons | Shields (matching type) |
| Dual Caster | None (or Dual) | Scepters, Daggers, Clubs | Scepters, Daggers, Clubs, Orbs |
| Stick and Orb | Orb | Quarterstaff (if 1H variant) / Scepters | Orbs |

*Note: The exact mapping of styles to accepted weapon categories must be extracted into a definitive lookup map in `optimizer.py`.*

### 3.2 Dynamic Filtering Logic for Alternatives
1. **Identify Target Slot:** Is the requested slot `Weapon1` or `Weapon2`? If neither, proceed with standard slot filtering.
2. **Determine Valid Types:** Query the weapon style matrix (above) using the current configuration.
3. **Filter Candidates:** Drop any candidate item whose weapon type does not match the valid types for that specific slot.

### 3.3 Handling "Stick and Orb" and "Dual Caster"
Caster styles have unique rules:
- **Dual Caster:** Usually implies two spellcasting implements. Valid types are typically One-Handed weapons with caster stats (Scepters, Daggers, Clubs).
- **Quarterstaff Caster:** If the user is using a two-handed Quarterstaff, `Weapon2` must be locked.

---

## 4. Blank Gearset (Parameter-Only) Saving

Users often want to create and save "templates" consisting solely of parameter choices (e.g., specific priority tiers, max levels, pack exclusions, and weapon styles) without having any pre-equipped gear items locking them down.

### 4.1 Save Payload Modifications
- The backend API and frontend save handlers must allow saving a `.ddogearset` file even if all equipment slots in `pre_equipped` are completely empty.
- Previously, gearset validation might have required at least one item or an initial solver run. This validation must be relaxed to allow storing a purely configuration-based file.
- Loading such a file will simply populate the configuration form, leaving the user with a blank canvas ready to run the solver.

---

## 5. Implementation Steps

### Step 1: Python Backend Hardening (`python/optimizer.py` & `python/solver.py`)
1. Centralize the item filtering logic into a single function: `is_item_valid(item, config)`.
2. Apply `is_item_valid` to the main optimization loop *and* the alternatives loop.
3. Implement the Weapon Style Matrix for the alternatives generator.

### Step 2: Go Backend Orchestration (`app.go`)
1. Ensure `MaxLevel`, `ExcludedPacks`, `WeaponStyle`, and `OffhandStyle` are accurately populated in the `AlternativesPayload`.
2. Add validation to reject alternatives requests for `Weapon2` if the current style dictates it should be empty (e.g., Two Handed Fighting).

### Step 3: Frontend Alignment (`frontend/src/lib/`)
1. Ensure the UI disables the "Find Alternatives" button for `Weapon2` when using a Two-Handed weapon.
2. When displaying warnings returned by the alternatives endpoint (e.g., if no valid alternatives exist due to strict pack exclusions), render them clearly to the user.
3. **Limit Indicators:** The alternatives list should visually warn the user if an item violates a global limit, rather than filtering the item out completely:
   - **Minor Artifacts:** If a Minor Artifact is already equipped in a *different* slot, any Minor Artifacts in the alternatives suggestion list MUST be highlighted with a **red border**.
   - **Raid Items:** If the user is already at their `raid_item_limit` from other slots, any new Raid Items in the alternatives suggestion list MUST be highlighted with a **gold border**.

---

## 6. Edge Cases & Testing

| ID | Edge Case | Expected Behavior |
|---|---|---|
| **EC-1** | User requests alternatives for `Weapon2` while using a Greatsword. | Backend returns an error/warning: "Cannot suggest alternatives for Weapon2 while using a Two-Handed weapon style." |
| **EC-2** | User has `Chill of Ravenloft` in `excluded_packs`, but requests alternatives for a slot where the only viable upgrades are from Ravenloft. | Alternatives list is empty. `Warnings` array contains: "No valid items found matching current level and pack restrictions." |
| **EC-3** | User requests alternative for `Armor` with `armor_restriction` set to `Light`. | Only Light Armor and Cloth (if permitted) are returned. Medium/Heavy are strictly filtered. |
| **EC-4** | User manually equips an ML 30 item, then changes `max_level` to 29 and runs solver. | Solver accepts the ML 30 item unconditionally (since it was pre-equipped) and successfully builds the rest of the gearset using only ML <= 29 items for the empty slots. |

---

## 7. Future Work & Known Limitations

**Augment Level Bump (ML Contagion):**
In DDO, slotting an augment with a Minimum Level (ML) higher than the base item raises the item's effective ML. Currently, this phase does not strictly enforce augment ML capping against the `max_level` configuration when assigning them to lower-level items. This is a known limitation that will be addressed in a future phase (e.g., Phase 12).
