package main

// Fetches DDOBuilderV2 over plain HTTPS instead of shelling out to a `git`
// binary — see docs/DDOBUILDER_FETCH_WITHOUT_GIT_PLAN.md for the full
// rationale (the short version: git isn't guaranteed to be installed on a
// machine that runs this app, especially Windows, and we don't want to
// assume any particular package manager is available to install it either).
//
// Mechanism: download the repo's GitHub-generated zip archive
// (https://codeload.github.com/Maetrim/DDOBuilderV2/zip/refs/heads/main,
// public repo, no credentials needed — confirmed via a real request), extract
// it into a staging directory, and atomically swap it into place. The
// archive is ~79MB / 20,521 files, so before doing that at all, check
// GitHub's lightweight commits API for the latest commit SHA and skip the
// whole thing if it matches what we fetched last time — otherwise every
// "Update External Sources" click would re-download the full archive even
// when nothing changed.

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	ddoZipURL            = "https://codeload.github.com/Maetrim/DDOBuilderV2/zip/refs/heads/main"
	ddoCommitsAPIURL     = "https://api.github.com/repos/Maetrim/DDOBuilderV2/commits/main"
	ddoZipTopLevelPrefix = "DDOBuilderV2-main/"
	// Deliberately outside ddoRepoDir itself (project-root, gitignored) so the
	// XML parsers walking DDOBuilderV2/Items, /Augments etc. never have any
	// reason to know or care this file exists.
	ddoCommitMarkerPath = ".ddobuilderv2_commit"
)

type ghCommitResponse struct {
	SHA string `json:"sha"`
}

// latestDDOBuilderCommitSHA asks GitHub what the current tip of main is,
// without downloading anything beyond a few KB of JSON.
func latestDDOBuilderCommitSHA() (string, error) {
	req, err := http.NewRequest("GET", ddoCommitsAPIURL, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "goGearset")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("contacting GitHub API: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return "", fmt.Errorf("GitHub API returned %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var parsed ghCommitResponse
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", fmt.Errorf("parsing GitHub API response: %w", err)
	}
	if parsed.SHA == "" {
		return "", fmt.Errorf("GitHub API response had no commit sha")
	}
	return parsed.SHA, nil
}

// fetchAndExtractDDOBuilderZip downloads the DDOBuilderV2 archive and
// atomically replaces ddoRepoDir with its contents. A failure at any point
// before the final rename leaves whatever ddoRepoDir already existed
// completely untouched — this never leaves a half-replaced data directory
// behind, whether the failure is a network error, a full disk, or the
// process being killed mid-extraction.
func fetchAndExtractDDOBuilderZip() error {
	tmpZip, err := os.CreateTemp("", "ddobuilderv2-*.zip")
	if err != nil {
		return fmt.Errorf("creating temp file: %w", err)
	}
	tmpZipPath := tmpZip.Name()
	defer os.Remove(tmpZipPath)

	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Get(ddoZipURL)
	if err != nil {
		tmpZip.Close()
		return fmt.Errorf("downloading %s: %w", ddoZipURL, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		tmpZip.Close()
		return fmt.Errorf("downloading %s: HTTP %d", ddoZipURL, resp.StatusCode)
	}
	if _, err := io.Copy(tmpZip, resp.Body); err != nil {
		tmpZip.Close()
		return fmt.Errorf("writing downloaded archive: %w", err)
	}
	if err := tmpZip.Close(); err != nil {
		return fmt.Errorf("closing downloaded archive: %w", err)
	}

	zr, err := zip.OpenReader(tmpZipPath)
	if err != nil {
		return fmt.Errorf("opening downloaded archive: %w", err)
	}
	defer zr.Close()

	stagingDir := ddoRepoDir + ".download"
	if err := os.RemoveAll(stagingDir); err != nil {
		return fmt.Errorf("clearing old staging directory: %w", err)
	}
	if err := os.MkdirAll(stagingDir, 0755); err != nil {
		return fmt.Errorf("creating staging directory: %w", err)
	}

	absStagingDir, err := filepath.Abs(stagingDir)
	if err != nil {
		os.RemoveAll(stagingDir)
		return fmt.Errorf("resolving staging directory: %w", err)
	}

	for _, f := range zr.File {
		relPath := strings.TrimPrefix(f.Name, ddoZipTopLevelPrefix)
		if relPath == "" {
			continue // the top-level directory entry itself
		}

		destPath := filepath.Join(stagingDir, relPath)
		absDestPath, err := filepath.Abs(destPath)
		if err != nil || !strings.HasPrefix(absDestPath, absStagingDir+string(os.PathSeparator)) {
			// Zip-slip guard: a malicious or corrupt archive entry name
			// (e.g. containing "../") must never be allowed to write
			// outside the staging directory.
			os.RemoveAll(stagingDir)
			return fmt.Errorf("archive entry has unsafe path: %s", f.Name)
		}

		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(destPath, 0755); err != nil {
				os.RemoveAll(stagingDir)
				return fmt.Errorf("creating directory %s: %w", relPath, err)
			}
			continue
		}

		if err := os.MkdirAll(filepath.Dir(destPath), 0755); err != nil {
			os.RemoveAll(stagingDir)
			return fmt.Errorf("creating parent directory for %s: %w", relPath, err)
		}
		if err := extractZipEntry(f, destPath); err != nil {
			os.RemoveAll(stagingDir)
			return fmt.Errorf("extracting %s: %w", relPath, err)
		}
	}

	if err := os.RemoveAll(ddoRepoDir); err != nil {
		os.RemoveAll(stagingDir)
		return fmt.Errorf("removing old %s: %w", ddoRepoDir, err)
	}
	if err := os.Rename(stagingDir, ddoRepoDir); err != nil {
		return fmt.Errorf("finalizing %s (staged data left at %s): %w", ddoRepoDir, stagingDir, err)
	}
	return nil
}

func extractZipEntry(f *zip.File, destPath string) error {
	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()

	mode := f.Mode()
	if mode == 0 {
		mode = 0644
	}
	out, err := os.OpenFile(destPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, mode)
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, rc)
	return err
}

func shortSHA(sha string) string {
	if len(sha) > 12 {
		return sha[:12]
	}
	return sha
}
