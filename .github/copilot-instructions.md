# goGearset

A Wails v2 desktop app (Go backend + Svelte/TS frontend) that generates optimal DDO (Dungeons & Dragons Online)
gear sets. Item/set data is parsed from a bundled DDOBuilderV2 XML data submodule; the actual gear optimization
is delegated to a Python ILP (Integer Linear Programming) solver built with `pulp`.

## Architecture

Three components glued together by Wails bindings and process embedding:

1. **Go backend** (`main.go`, `app.go`, `internal/`) — the Wails app shell.
   - `internal/services/parser.go` walks `data/ddobuilder/**/*.xml` (a git submodule pointing at
     `Maetrim/DDOBuilderV2`) and unmarshals `Items`/`Sets` XML into `internal/models` structs.
   - `internal/services/enrichment.go` maps raw XML items into the enriched `models.Item` JSON shape (wiki URL,
     pack ID, raid flag) using `data/PackMappings.json` and a raids list, loaded via `InitEnrichment`.
   - `scripts/update_data.go` is a standalone `go run` script that runs the parse+enrich pipeline and writes
     the consolidated `models.AppData` JSON — this is the offline data-refresh step, not part of the running app.
   - `app.go`'s `App` struct is bound to the frontend via Wails (`Bind: []interface{}{app}` in `main.go`).
     `RunOptimization(config OptimizationPayload) (ResultPayload, error)` is the main entry point the frontend
     calls.
2. **Embedded Python solver** — `python/dist/solver` (a PyInstaller-built standalone binary) is embedded into
   the Go binary via `//go:embed python/dist/solver` in `app.go`. At startup, `App.extractSolver()` writes it to
   a temp dir and marks it executable; `RunOptimization` then serializes the `OptimizationPayload` to a temp
   JSON file and invokes the extracted binary as a subprocess, streaming stdout back into `App.logs`
   (exposed to the frontend via `GetSystemLogs()`).
   - Source for the embedded binary lives in `python/`: `solver.py` (entry point, reads JSON payload from a
     file arg or stdin), `optimizer.py` (builds and solves the ILP model with `pulp`), `parser.py`.
   - **When editing `python/*.py`, the embedded `python/dist/solver` binary must be rebuilt with PyInstaller
     and committed** — the Go build embeds whatever binary is on disk, it does not build Python itself.
3. **Frontend** (`frontend/`) — Svelte + TypeScript + Tailwind, built with Vite. Wails auto-generates Go bindings
   into `frontend/wailsjs/go/models` (imported in `frontend/src/lib/store.ts` as `main.OptimizationPayload` /
   `main.ResultPayload` — these TS types mirror `app.go`'s Go structs and must be kept in sync manually when the
   Go payload/result structs change).
   - App state lives in Svelte stores (`frontend/src/lib/store.ts`): `configStore`, `resultStore`, `logsStore`,
     `isParsing`, `isOptimizing`.
   - Domain UI components are under `frontend/src/lib/components/domain/` (e.g. `JobConfigurationForm.svelte`,
     `ResultsDataGrid.svelte`, `StatusConsole.svelte`).

## Build & run

- Full desktop app dev loop: `wails dev` (from repo root; needs the Wails CLI). Production build: `wails build`.
- Go only: `go build ./...` / `go vet ./...` from repo root.
- Frontend only (from `frontend/`): `npm run dev`, `npm run build`, `npm run check` (svelte-check type checking).
- Data refresh (regenerate enriched item/set JSON from the DDOBuilder XML submodule):
  `go run scripts/update_data.go` from repo root.
- Rebuilding the embedded solver after Python changes (from `python/`, with the venv active):
  build a standalone binary with PyInstaller and place the result at `python/dist/solver` before `wails build`.

## Testing

- Go tests: `go test ./...` from repo root. Run a single test with
  `go test ./internal/services/... -run TestEnrichItem_WikiURLAndPackMappingAndRaid -v`.
  Tests live in `internal/services/*_test.go` (`parser_test.go`, `enrichment_test.go`) and cover XML parsing and
  item enrichment; `enrichment_test.go` uses `services.InitEnrichmentForTest` to inject mock pack-mapping/raid
  data instead of reading real files.
- Python tests: `pytest python/tests/` (requires `pulp` and `pytest` installed in `python/.venv`). Test files
  under `python/tests/` describe expected optimizer/payload behavior — note `test_phase3_integration.py` is
  currently written as a set of documented blueprints with assertions commented out, so a passing run doesn't
  guarantee solver behavior is covered; check whether assertions are live before trusting green results.

## Conventions

- `data/ddobuilder` is a **git submodule**; don't edit files inside it — treat it as read-only upstream game data.
- Go JSON payload/result structs in `app.go` (`OptimizationPayload`, `ResultPayload`) are the contract with both
  the Python solver's JSON input and the frontend's TypeScript types — changing field names/types requires
  updating all three: `app.go`, the Python payload consumers (`solver.py`/`optimizer.py`), and
  `frontend/src/lib/store.ts`.
- Weapon-style/armor category lists (e.g. `twf_weapons`, `thf_weapons`, `swash_weapons`) are currently
  duplicated between `python/cli.py` and `python/solver.py` — keep both in sync if updating weapon categories.
