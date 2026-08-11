package main

import (
	"database/sql"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"goGearset/internal/appdb"
	"goGearset/internal/catalog"
)

// The unit tests in internal/appdb drive imports against a hand-built catalog
// of three names. This one drives the real thing: the 14 .ddogearset files this
// project actually accumulated, resolved against the shipped catalog.db.
//
// That difference matters. The fake catalog resolves what the fixtures were
// written to resolve; the real one has 8,474 items, two augments called
// "Deathblock", and whatever DDOBuilderV2 has renamed since these gearsets were
// saved. Only this test can say whether a real file imports.
//
// Skipped when either input is missing — .ddogearset files are gitignored user
// data, so a clean checkout legitimately has none.

func realGearsetFiles(t *testing.T) []string {
	t.Helper()
	files, err := filepath.Glob("gearsets/*.ddogearset")
	if err != nil || len(files) == 0 {
		t.Skip("no gearsets/*.ddogearset on this machine (they are gitignored user data)")
	}
	return files
}

func realCatalog(t *testing.T) *sql.DB {
	t.Helper()
	path := "bundled/darwin-arm64/catalog.db"
	if p := os.Getenv(catalogEnvVar); p != "" {
		path = p
	}
	if _, err := os.Stat(path); err != nil {
		t.Skipf("no catalog at %s", path)
	}
	db, err := catalog.Open(path)
	if err != nil {
		t.Fatalf("opening catalog: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

func TestImportRealGearsetsAgainstTheRealCatalog(t *testing.T) {
	files := realGearsetFiles(t)
	catalogDB := realCatalog(t)

	resolver, err := appdb.NewSQLCatalog(catalogDB)
	if err != nil {
		t.Fatalf("building the name resolver: %v", err)
	}

	app, err := appdb.Open(filepath.Join(t.TempDir(), "app.db"), AppVersion)
	if err != nil {
		t.Fatalf("opening app.db: %v", err)
	}
	defer app.Close()

	imported, orphaned := 0, 0
	for _, path := range files {
		outcome := appdb.ImportFile(app, resolver, path, AppVersion)
		if outcome.Status != appdb.StatusImported {
			t.Errorf("%s: %s (%s)", filepath.Base(path), outcome.Status, outcome.Error)
			continue
		}
		imported++
		orphaned += len(outcome.Orphans)
		for _, o := range outcome.Orphans {
			// Reported, not failed: a gearset saved two game updates ago can
			// legitimately name something that has since been removed. Logged
			// so a SURGE in orphans is visible — that would mean the resolver
			// is broken, not that the game changed.
			t.Logf("orphan in %s: %s %q (%s)", filepath.Base(path), o.Kind, o.Name, o.Detail)
		}
	}

	if imported != len(files) {
		t.Fatalf("imported %d of %d real gearsets", imported, len(files))
	}

	// These files are the app's own output. If a large share of their names no
	// longer resolve, the fault is far more likely to be in the resolver than
	// in fourteen years of game updates.
	//
	// Floors, not exact counts: the corpus is gitignored user data and can
	// legitimately grow. What must not happen is an import that reports success
	// while writing nothing — a bug an "imported 14 of 14" check alone would
	// wave straight through. Measured on this corpus: 158 slots, 200 augments,
	// 191 filigrees, 143 priorities, zero orphans.
	counts := map[string]int{}
	for _, table := range []string{"gearset_slot", "gearset_augment", "gearset_filigree", "build_priority"} {
		var n int
		if err := app.QueryRow("SELECT count(*) FROM " + table).Scan(&n); err != nil {
			t.Fatalf("counting %s: %v", table, err)
		}
		counts[table] = n
	}
	for table, floor := range map[string]int{
		"gearset_slot": 100, "gearset_augment": 100, "gearset_filigree": 100, "build_priority": 50} {
		if counts[table] < floor {
			t.Errorf("%s has %d rows after importing %d real gearsets; expected at "+
				"least %d — the import reported success but wrote almost nothing",
				table, counts[table], imported, floor)
		}
	}
	if orphaned > counts["gearset_slot"] {
		t.Errorf("more orphans (%d) than resolved slots (%d) — the resolver looks broken",
			orphaned, counts["gearset_slot"])
	}
	t.Logf("imported %d gearsets: %v, %d orphaned references", imported, counts, orphaned)

	// Idempotency, on the real corpus rather than one synthetic file.
	for _, path := range files {
		if outcome := appdb.ImportFile(app, resolver, path, AppVersion); outcome.Status != appdb.StatusAlreadyImported {
			t.Errorf("re-importing %s: %s, want %s",
				filepath.Base(path), outcome.Status, appdb.StatusAlreadyImported)
		}
	}
	var builds int
	if err := app.QueryRow("SELECT count(*) FROM build").Scan(&builds); err != nil {
		t.Fatalf("counting builds: %v", err)
	}
	if builds != len(files) {
		t.Errorf("%d builds after importing %d files twice", builds, len(files))
	}
}

func TestAppDBPathIsUnderTheUserDataDirectory(t *testing.T) {
	// app.db must never land in the process working directory — the bug this
	// release exists to stop repeating (see legacyGearsetDirName). For a
	// double-clicked .app that directory is not the user's home, and on a
	// read-only volume the write fails outright.
	t.Setenv("DDO_APP_DB", "")
	path, err := appDBPathFor()
	if err != nil {
		t.Fatalf("appDBPathFor: %v", err)
	}
	dataDir, err := userDataDir()
	if err != nil {
		t.Fatalf("userDataDir: %v", err)
	}
	if filepath.Dir(path) != dataDir {
		t.Errorf("app.db resolves to %s, want it inside %s", path, dataDir)
	}
	if !filepath.IsAbs(path) {
		t.Errorf("app.db path %q is relative — that is the bug, not the fix", path)
	}

	exportDir, err := gearsetExportDir()
	if err != nil {
		t.Fatalf("gearsetExportDir: %v", err)
	}
	if !filepath.IsAbs(exportDir) || filepath.Dir(exportDir) != dataDir {
		t.Errorf("gearset exports resolve to %s, want a directory inside %s", exportDir, dataDir)
	}
}

func TestAppDBEnvOverrideWins(t *testing.T) {
	// Tests and dev runs must be able to point somewhere scratch: writing into
	// the real app.db would touch data the user cannot regenerate.
	want := filepath.Join(t.TempDir(), "scratch.db")
	t.Setenv("DDO_APP_DB", want)
	got, err := appDBPathFor()
	if err != nil {
		t.Fatalf("appDBPathFor: %v", err)
	}
	if got != want {
		t.Errorf("appDBPathFor() = %q, want %q", got, want)
	}
}

func TestFirstRunCreatesAppDBWithNoOverrides(t *testing.T) {
	// Every other test here points DDO_APP_DB at a scratch file, which means the
	// path the real app actually takes on first launch — userDataDir() with no
	// override at all — had never been executed. Redirecting HOME exercises it
	// for real: os.UserConfigDir() reads HOME on macOS and Linux, so this walks
	// the same resolution a double-clicked .app does.
	if runtime.GOOS == "windows" {
		t.Skip("os.UserConfigDir reads %AppData% on Windows, not HOME")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_DATA_HOME", "")
	t.Setenv("DDO_APP_DB", "")
	t.Setenv("DDO_GEARSET_DIR", "")

	app := NewApp()
	if err := app.ensureAppDB(); err != nil {
		t.Fatalf("first run could not create app.db: %v", err)
	}
	defer app.appDB.Close()

	if !strings.HasPrefix(app.appDBPath, home) {
		t.Fatalf("app.db landed at %s, outside the redirected home %s", app.appDBPath, home)
	}
	if _, err := os.Stat(app.appDBPath); err != nil {
		t.Fatalf("app.db was not created on disk: %v", err)
	}
	if version, err := appdb.SchemaVersionOf(app.appDB); err != nil || version != appdb.SchemaVersion {
		t.Errorf("first-run schema = %d (%v), want %d", version, err, appdb.SchemaVersion)
	}

	// The migration path runs on a clean install too — that is why a fresh file
	// is created at schema 1 and migrated up rather than built at the current
	// version. Proven by the run tables existing.
	var runTables int
	if err := app.appDB.QueryRow(`SELECT count(*) FROM sqlite_master
		WHERE type='table' AND name LIKE 'run%'`).Scan(&runTables); err != nil {
		t.Fatal(err)
	}
	if runTables < 5 {
		t.Errorf("%d run tables after a first run; the migration did not run", runTables)
	}
}
