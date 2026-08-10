package main

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestBundleFingerprint_CostFitsTheWarmStartBudget guards the one judgement
// call in the caching scheme: hashing the whole 21 MB bundle on every launch
// (rather than trusting AppVersion alone, which does not change between dev
// builds) is only defensible while it stays far below the ≤0.25 s warm-start
// budget the Phase 7 gate sets.
func TestBundleFingerprint_CostFitsTheWarmStartBudget(t *testing.T) {
	if _, err := bundleFingerprint(); err != nil { // warm the page cache
		t.Fatalf("bundleFingerprint: %v", err)
	}
	started := time.Now()
	if _, err := bundleFingerprint(); err != nil {
		t.Fatalf("bundleFingerprint: %v", err)
	}
	elapsed := time.Since(started)
	t.Logf("bundleFingerprint took %s", elapsed)
	if elapsed > 100*time.Millisecond {
		t.Errorf("fingerprinting took %s — too much of the 250ms warm-start "+
			"budget to spend on a cache-key check", elapsed)
	}
}

// The Phase 7 riders on the PyInstaller --onedir switch
// (docs/0.5.0/00_ETL_START_HERE.md): extraction must recurse into _internal/,
// and it must happen ONCE — "assert zero extraction I/O on the second launch".

func withTempCacheDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	original := userCacheDir
	userCacheDir = func() (string, error) { return dir, nil }
	t.Cleanup(func() { userCacheDir = original })
	return dir
}

// snapshot records every extracted file's path, size and modification time.
// Re-extracting rewrites files, which moves their mtime — so an identical
// snapshot across two calls is the observable form of "no extraction I/O
// happened", without needing to instrument the filesystem.
func snapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		out[relative] = fmt.Sprintf("%s/%d", info.ModTime(), info.Size())
		return nil
	})
	if err != nil {
		t.Fatalf("walking %s: %v", root, err)
	}
	return out
}

func TestExtractSolver_SecondCallDoesNoExtractionIO(t *testing.T) {
	withTempCacheDir(t)
	app := &App{}

	if err := app.extractSolver(); err != nil {
		t.Fatalf("first extractSolver: %v", err)
	}
	first := snapshot(t, app.solverDir)
	if len(first) == 0 {
		t.Fatal("first extraction produced no files")
	}
	firstDir := app.solverDir

	app2 := &App{}
	if err := app2.extractSolver(); err != nil {
		t.Fatalf("second extractSolver: %v", err)
	}
	if app2.solverDir != firstDir {
		t.Errorf("second launch used a different directory:\n  %s\n  %s", firstDir, app2.solverDir)
	}
	second := snapshot(t, app2.solverDir)
	if len(second) != len(first) {
		t.Fatalf("file count changed: %d -> %d", len(first), len(second))
	}
	for name, stamp := range first {
		if second[name] != stamp {
			t.Errorf("%s was rewritten on the second launch (%q -> %q)", name, stamp, second[name])
		}
	}
	if !strings.Contains(strings.Join(app2.logs, "\n"), "already extracted") {
		t.Errorf("second launch did not report a cache hit; logs:\n%s", strings.Join(app2.logs, "\n"))
	}
}

func TestExtractSolver_ExtractsEveryBundledFileAtItsOwnPath(t *testing.T) {
	withTempCacheDir(t)
	app := &App{}
	if err := app.extractSolver(); err != nil {
		t.Fatalf("extractSolver: %v", err)
	}

	// The --onedir solver will not start unless its whole _internal/ tree
	// landed beside the executable, so the check is per-path, not per-count.
	var checked, nested int
	err := fs.WalkDir(bundleFS, bundleRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(bundleRoot, path)
		if err != nil {
			return err
		}
		if d.IsDir() || relative == "." || relative == catalogFileName {
			return nil
		}
		if strings.Contains(relative, string(os.PathSeparator)) {
			nested++
		}
		if _, statErr := os.Stat(filepath.Join(app.solverDir, relative)); statErr != nil {
			t.Errorf("embedded %s was not extracted: %v", relative, statErr)
		}
		checked++
		return nil
	})
	if err != nil {
		t.Fatalf("walking the bundle: %v", err)
	}
	if checked == 0 {
		t.Fatal("the bundle contains no files to extract")
	}
	if nested == 0 {
		t.Errorf("the bundle has no files in subdirectories — this build did not "+
			"stage a --onedir solver (_internal/), so recursion is untested. "+
			"Rebuild with build-mac.sh. (%d top-level files found)", checked)
	}
}

func TestExtractSolver_DoesNotExtractTheCatalog(t *testing.T) {
	withTempCacheDir(t)
	app := &App{}
	if err := app.extractSolver(); err != nil {
		t.Fatalf("extractSolver: %v", err)
	}
	// catalog.db has its own destination (ensureCatalogSeeded, into the
	// persistent user data directory). A copy here would be 58 MB of waste in
	// a directory the OS is free to evict.
	if _, err := os.Stat(filepath.Join(app.solverDir, catalogFileName)); err == nil {
		t.Errorf("%s was extracted into the solver cache", catalogFileName)
	}
}

func TestExtractSolver_UnstampedDirectoryIsReplacedNotFatal(t *testing.T) {
	cacheDir := withTempCacheDir(t)
	app := &App{}
	if err := app.extractSolver(); err != nil {
		t.Fatalf("extractSolver: %v", err)
	}
	target := app.solverDir

	// Debris from an interrupted extraction by an older build: the directory
	// is there, the stamp is not. It must not block the app forever.
	if err := os.Remove(filepath.Join(target, extractionStampName)); err != nil {
		t.Fatalf("removing stamp: %v", err)
	}
	if err := os.RemoveAll(filepath.Join(target, solverBinaryName)); err != nil {
		t.Fatalf("removing solver: %v", err)
	}

	app2 := &App{}
	if err := app2.extractSolver(); err != nil {
		t.Fatalf("extractSolver over unstamped debris: %v", err)
	}
	if app2.solverDir != target {
		t.Errorf("re-extraction went somewhere else: %s", app2.solverDir)
	}
	if _, err := os.Stat(app2.solverPath); err != nil {
		t.Errorf("solver missing after re-extraction: %v", err)
	}
	if _, err := os.Stat(filepath.Join(cacheDir, solverCacheDirName, filepath.Base(target), extractionStampName)); err != nil {
		t.Errorf("stamp missing after re-extraction: %v", err)
	}
}

func TestExtractSolver_PrunesOtherVersionsExtractions(t *testing.T) {
	cacheDir := withTempCacheDir(t)
	parent := filepath.Join(cacheDir, solverCacheDirName)
	if err := os.MkdirAll(filepath.Join(parent, "0.0.1-deadbeefdeadbeef"), 0755); err != nil {
		t.Fatalf("seeding a stale extraction: %v", err)
	}

	app := &App{}
	if err := app.extractSolver(); err != nil {
		t.Fatalf("extractSolver: %v", err)
	}
	entries, err := os.ReadDir(parent)
	if err != nil {
		t.Fatalf("reading cache parent: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(app.solverDir) {
		names := make([]string, len(entries))
		for i, e := range entries {
			names[i] = e.Name()
		}
		t.Errorf("stale extraction was not pruned; cache holds %v", names)
	}
}

func TestBundleFingerprint_IsStableAndNamesTheCacheDirectory(t *testing.T) {
	first, err := bundleFingerprint()
	if err != nil {
		t.Fatalf("bundleFingerprint: %v", err)
	}
	second, err := bundleFingerprint()
	if err != nil {
		t.Fatalf("bundleFingerprint (again): %v", err)
	}
	if first != second {
		t.Errorf("fingerprint is not stable: %q vs %q", first, second)
	}

	withTempCacheDir(t)
	app := &App{}
	if err := app.extractSolver(); err != nil {
		t.Fatalf("extractSolver: %v", err)
	}
	// The directory name carries BOTH, so a dev rebuild that leaves AppVersion
	// alone still gets a fresh extraction rather than a stale cached solver.
	if want := AppVersion + "-" + first; filepath.Base(app.solverDir) != want {
		t.Errorf("cache directory is %q, want %q", filepath.Base(app.solverDir), want)
	}
}
