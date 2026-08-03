# Changelog

All notable changes to DDO Gearset Optimizer are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [0.1.0] — 2026-08-04

### Added

**Core ILP Optimizer**
- Integer Linear Programming solver (PuLP + GLPK) for mathematically guaranteed optimal gear selection
- Weighted stat priorities (1–100) — higher weights drive the objective function
- Build type support: Melee, Ranged, Caster, Tank
- Weapon style support: TWF, THF, SWF, Sword & Board, Bow, Repeating Crossbow, Great Crossbow, Dual Crossbow, Thrown, Shuriken
- Armor restriction filtering: Any, Cloth, Light, Medium, Heavy
- Expansion pack exclusion — toggle any expansion to prevent items from being selected
- Raid item limit constraint (0 = no raid items, -1 = unlimited)
- Swashbuckling and Runearm slot support
- Caster spell power and spell school targeting
- Minor Artifact slot reservation and filigree slot count (1–5)
- Dinosaur Bone artifact forced selection mode
- Gem of Many Facets exclusion option

**Data Pipeline**
- Reads directly from DDOBuilderV2 XML output files (items, augments, filigrees, quests)
- Automatic item enrichment: Wiki URLs, expansion pack tags, raid flags
- Hot-reload via "Update External Sources" button (runs `git pull` on DDOBuilderV2, reloads caches)

**Gearset Editor**
- Per-slot item selection with real-time search
- Augment slot dropdowns (color-filtered: Yellow, Blue, Red, Orange, etc.)
- Alternative items per slot (top alternatives from constrained re-solves)
- Calculate Stats button — evaluates current manual configuration without re-running full optimization
- Pre-filled items and augments are locked in the ILP; solver builds the rest around them

**Sentient Filigrees**
- Dedicated Filigrees tab for Sentient Weapon (10 slots) and Minor Artifact (1–5 slots)
- Real-time filigree search with set-name filter dropdown
- Filigree stacking rules enforced by ILP:
  - Same filigree: at most once per weapon, at most once per artifact
  - Same filigree may appear in both weapon AND artifact (cross-item stacking)
  - AUTO badge shows solver-recommended filigrees

**Summary & File Management**
- Priority effects panel (sorted by weight, highest first)
- Full effects breakdown grouped by stat (items + augments + set bonuses + filigrees)
- Active set bonuses panel
- `.ddogearset` file format (v1.2, JSON) — stores full configuration + solver result
- Timestamped auto-generated filenames: `<Name>_<BuildType><WeaponStyle>Gearset_<timestamp>.ddogearset`
- Load/Save round-trip: all configuration parameters fully restored on load
- Backwards compatible with legacy `.json` gearset files

**Documentation**
- `docs/USAGE.md` — end-user guide
- `docs/ENGINEERING.md` — developer reference with architecture diagram
- `docs/plans/retrospective.md` — detailed phase retrospective (Phases 1–6)

### Technical
- Wails v2 desktop app (Go backend + Svelte/Vite frontend)
- Python 3.11 solver compiled to standalone binary via PyInstaller (embedded in Go binary)
- GLPK solver via homebrew (`/opt/homebrew/bin/glpsol`)
- Glassmorphism dark-mode UI design
