---
name: frontend_tester
description: Validates and fixes frontend structural gotchas, specifically ensuring import paths (especially Wails bindings and nested component imports) resolve correctly, preventing common build compilation failures.
---

# Frontend Tester Skill

When working on a frontend project (especially Svelte/Wails), invoke this skill or act with its mindset to verify the following before concluding:

1. **Import Paths**: Deeply nested components often suffer from incorrect relative paths (e.g., to `wailsjs/go/...` or `$lib`). Carefully calculate the exact directory depth relative to the project root.

2. **Missing Aliases**: Favor aliases (like `$lib` or `$components`) over fragile relative `../../` paths if they are configured in `svelte.config.js` or `tsconfig.json`.

3. **Build Readiness**: Mentally verify that all generated or modified files align properly with the active build tools (Vite, Rollup, Wails) to ensure a flawless compilation loop.

4. **Wails-specific checks**: Verify that any Go bindings being imported from `wailsjs/go/...` match the actual generated bindings after running `wails generate`.
