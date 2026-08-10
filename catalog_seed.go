package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"

	"goGearset/internal/catalog"
)

// appDataDirName is the per-app subdirectory under the OS's standard user
// data location. Both catalog.db and, from 0.5.1, app.db live here — see
// docs/0.5.0/00_ETL_START_HERE.md §5.2.1.
const appDataDirName = "DDOGearsetOptimizer"

// catalogFileName is constant across platforms (unlike solverBinaryName,
// which gains ".exe" on Windows) — it is a plain data file, not an
// executable, so there is exactly one name regardless of OS.
const catalogFileName = "catalog.db"

// userDataDir resolves the OS-standard per-user data directory:
//
//	macOS    ~/Library/Application Support/DDOGearsetOptimizer/
//	Windows  %APPDATA%\DDOGearsetOptimizer\
//	Linux    ${XDG_DATA_HOME:-~/.local/share}/DDOGearsetOptimizer/
//
// os.UserConfigDir() gives exactly the macOS and Windows paths already. It
// does NOT give the Linux one — it resolves XDG_CONFIG_HOME (~/.config), and
// the spec deliberately wants the DATA directory (~/.local/share), so Linux
// gets its own branch rather than accepting UserConfigDir's close-but-wrong
// answer.
func userDataDir() (string, error) {
	if runtime.GOOS == "linux" {
		base := os.Getenv("XDG_DATA_HOME")
		if base == "" {
			home, err := os.UserHomeDir()
			if err != nil {
				return "", fmt.Errorf("resolving home directory: %w", err)
			}
			base = filepath.Join(home, ".local", "share")
		}
		return filepath.Join(base, appDataDirName), nil
	}

	base, err := os.UserConfigDir()
	if err != nil {
		return "", fmt.Errorf("resolving user config directory: %w", err)
	}
	return filepath.Join(base, appDataDirName), nil
}

// ensureCatalogSeeded makes sure a usable catalog.db exists in the user data
// directory and returns its path. The release ALSO carries catalog.db inside
// the bundle (bundleFS, alongside the solver) — purely as installation
// media, never as the file anything reads directly. See START_HERE §5.2.2:
// on macOS people drag only the .app to /Applications, so a catalog shipped
// merely beside it would be left behind; seeding makes a single .app
// self-sufficient.
//
// Seeds when: no catalog.db exists yet in the data directory, OR the
// bundled copy's catalog_version is strictly higher than the installed
// one's (an app update carrying a newer catalog). Never overwrites an
// EQUAL-or-newer installed catalog — protects a future update feature
// (schema doc §5.1.2) from ever being clobbered by a stale bundled copy.
func (a *App) ensureCatalogSeeded() (string, error) {
	if p := os.Getenv(catalogEnvVar); p != "" {
		a.addLog(fmt.Sprintf("%s set — using %s directly, no seeding.", catalogEnvVar, p))
		return p, nil
	}

	dataDir, err := userDataDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		return "", fmt.Errorf("creating data directory %s: %w", dataDir, err)
	}
	installedPath := filepath.Join(dataDir, catalogFileName)

	bundled, err := bundleFS.ReadFile(bundleRoot + "/" + catalogFileName)
	if err != nil {
		return "", fmt.Errorf("reading embedded catalog: %w", err)
	}

	needsSeed := true
	if existing, statErr := os.Stat(installedPath); statErr == nil && existing.Size() > 0 {
		needsSeed = false
		if bundledVersion, installedVersion, cmpErr := compareCatalogVersions(bundled, installedPath); cmpErr == nil {
			needsSeed = bundledVersion > installedVersion
		}
		// A comparison error (e.g. the installed file is corrupt/unreadable)
		// deliberately does NOT trigger a reseed here — see the fallback
		// below, which only reseeds on an outright open failure. A readable
		// but unparseable catalog_meta is left alone rather than guessed at.
	}

	if !needsSeed {
		if _, err := catalog.Open(installedPath); err == nil {
			return installedPath, nil
		}
		// The installed file exists but won't even open — corrupt or from an
		// interrupted previous seed that never got renamed atomically (see
		// the temp+rename below, which should prevent exactly this, but a
		// prior version or an external interruption could still leave one).
		a.addLog("Installed catalog is unreadable; reseeding from the bundle.")
		needsSeed = true
	}

	fd, err := os.CreateTemp(dataDir, catalogFileName+".tmp-*")
	if err != nil {
		return "", fmt.Errorf("creating temp file for catalog seed: %w", err)
	}
	tmpPath := fd.Name()
	if _, err := fd.Write(bundled); err != nil {
		fd.Close()
		os.Remove(tmpPath)
		return "", fmt.Errorf("writing catalog seed: %w", err)
	}
	if err := fd.Close(); err != nil {
		os.Remove(tmpPath)
		return "", fmt.Errorf("closing catalog seed: %w", err)
	}
	// os.Rename over an existing file is atomic on both POSIX and Windows
	// (unlike a plain write), so a reader can never observe a half-written
	// catalog.db — it sees either the old file or the fully-written new one.
	if err := os.Rename(tmpPath, installedPath); err != nil {
		os.Remove(tmpPath)
		return "", fmt.Errorf("installing catalog seed: %w", err)
	}
	a.addLog(fmt.Sprintf("Catalog seeded to %s (%.1f MB).", installedPath, float64(len(bundled))/1024/1024))
	return installedPath, nil
}

// compareCatalogVersions reads catalog_version from the embedded bytes (via
// a temp file — catalog.Open needs a real path) and from the already-
// installed file, without touching either's real location.
func compareCatalogVersions(bundledBytes []byte, installedPath string) (bundledVersion, installedVersion int, err error) {
	tmp, err := os.CreateTemp("", "ddo-catalog-cmp-*")
	if err != nil {
		return 0, 0, err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if _, err := tmp.Write(bundledBytes); err != nil {
		tmp.Close()
		return 0, 0, err
	}
	if err := tmp.Close(); err != nil {
		return 0, 0, err
	}

	bundledDB, err := catalog.Open(tmpPath)
	if err != nil {
		return 0, 0, err
	}
	defer bundledDB.Close()
	bundledMeta, err := catalog.ReadMeta(bundledDB)
	if err != nil {
		return 0, 0, err
	}

	installedDB, err := catalog.Open(installedPath)
	if err != nil {
		return 0, 0, err
	}
	defer installedDB.Close()
	installedMeta, err := catalog.ReadMeta(installedDB)
	if err != nil {
		return 0, 0, err
	}

	return bundledMeta.CatalogVersion, installedMeta.CatalogVersion, nil
}
