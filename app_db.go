package main

import (
	"fmt"
	"os"
	"path/filepath"

	"goGearset/internal/appdb"
	"goGearset/internal/catalog"
)

// appDBFileName sits beside catalog.db in the user data directory. Two files,
// one directory, opposite lifecycles: catalog.db is replaced wholesale by an
// app update, app.db is never replaced by anything (schema doc §4).
const appDBFileName = "app.db"

// legacyGearsetDirName is where SaveGearset has always written .ddogearset
// files: a RELATIVE path, resolved against the process working directory.
//
// That was only ever correct when the app was launched from the repo during
// development. A double-clicked macOS .app has no meaningful working directory,
// and on a read-only volume the write fails outright. 0.5.1 is the release that
// decides where user data lives, so the export directory moves under
// userDataDir() with the databases — see gearsetExportDir.
const legacyGearsetDirName = "gearsets"

// appDBPathFor returns where app.db lives, honouring an override.
//
// DDO_APP_DB mirrors DDO_CATALOG_DB's convention so a test or a dev run can
// point at a scratch file without touching the real one. That matters more here
// than it does for the catalog: pointing a test at the real app.db would write
// into data the user cannot regenerate.
func appDBPathFor() (string, error) {
	if p := os.Getenv("DDO_APP_DB"); p != "" {
		return p, nil
	}
	dir, err := userDataDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, appDBFileName), nil
}

// gearsetExportDir is where .ddogearset files are written from 0.5.1 on.
//
// They are an EXPORT format now, not storage (schema §8 Q3) — a file can be
// sent to someone, a database cannot, so the feature stays while the source of
// truth moves to app.db.
func gearsetExportDir() (string, error) {
	dir, err := userDataDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "gearsets"), nil
}

// ensureAppDB opens (creating on first run) the user's app.db and stores the
// handle on the App.
//
// Unlike ensureCatalogSeeded there is nothing to seed: app.db starts empty and
// is filled by the user. A failure here is NOT fatal to startup — the app still
// solves, it just cannot persist — because refusing to launch over a storage
// problem would leave someone with no way to reach their own exported files.
func (a *App) ensureAppDB() error {
	path, err := appDBPathFor()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("creating data directory for app.db: %w", err)
	}
	db, err := appdb.Open(path, AppVersion)
	if err != nil {
		return err
	}
	a.appDB = db
	a.appDBPath = path
	a.addLog(fmt.Sprintf("User data ready at %s (schema %d).", path, appdb.SchemaVersion))
	return nil
}

// legacyGearsetFiles finds .ddogearset files left by pre-0.5.1 builds, so the
// import can offer them.
//
// Looks in the new export directory AND the old working-directory-relative one,
// because whether the latter has anything in it depends entirely on where the
// app happened to be launched from before now.
func legacyGearsetFiles() []string {
	var dirs []string
	if exportDir, err := gearsetExportDir(); err == nil {
		dirs = append(dirs, exportDir)
	}
	if cwd, err := os.Getwd(); err == nil {
		dirs = append(dirs, filepath.Join(cwd, legacyGearsetDirName))
	}

	seen := map[string]bool{}
	var found []string
	for _, dir := range dirs {
		matches, err := filepath.Glob(filepath.Join(dir, "*.ddogearset"))
		if err != nil {
			continue
		}
		for _, m := range matches {
			resolved, err := filepath.Abs(m)
			if err != nil {
				resolved = m
			}
			if !seen[resolved] {
				seen[resolved] = true
				found = append(found, resolved)
			}
		}
	}
	return found
}

// ImportLegacyGearsets imports every .ddogearset this machine can find into
// app.db and reports what happened to each.
//
// Explicit — nothing calls this on startup. Importing is a decision, and one
// made silently during launch is one nobody can connect to its effects.
//
// Safe to run repeatedly: a file already imported is reported as such and
// nothing about its build is touched (see appdb.ImportFile). Re-import is not a
// sync, because the build may have been edited in the app since.
func (a *App) ImportLegacyGearsets() ([]appdb.ImportOutcome, error) {
	if a.appDB == nil {
		return nil, fmt.Errorf("user data is not available; nothing was imported")
	}
	// Opened for the duration of the import rather than held: resolving names
	// is the only thing an import needs the catalog for, and it is read-only
	// and immutable, so there is nothing to keep warm.
	path := a.catalogDBPath
	if path == "" {
		path = catalogPath()
	}
	catalogDB, err := catalog.Open(path)
	if err != nil {
		return nil, fmt.Errorf("cannot resolve item names without the catalog: %w", err)
	}
	defer catalogDB.Close()

	resolver, err := appdb.NewSQLCatalog(catalogDB)
	if err != nil {
		return nil, err
	}

	files := legacyGearsetFiles()
	outcomes := make([]appdb.ImportOutcome, 0, len(files))
	for _, path := range files {
		outcome := appdb.ImportFile(a.appDB, resolver, path, AppVersion)
		outcomes = append(outcomes, outcome)
		switch outcome.Status {
		case appdb.StatusImported:
			a.addLog(fmt.Sprintf("Imported %s (%d unresolved reference(s)).",
				filepath.Base(path), len(outcome.Orphans)))
		case appdb.StatusAlreadyImported:
			a.addLog(fmt.Sprintf("Already imported, left alone: %s", filepath.Base(path)))
		default:
			a.addLog(fmt.Sprintf("Could not import %s: %s", filepath.Base(path), outcome.Error))
		}
	}
	return outcomes, nil
}
