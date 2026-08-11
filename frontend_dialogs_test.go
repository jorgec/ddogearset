package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// TestFrontendUsesNoNativeDialogs guards a failure mode that is completely
// silent.
//
// Wails' webview does not implement the JavaScript dialog delegates, so
// `window.confirm` returns false without ever showing anything, `alert` does
// nothing, and `prompt` returns null. A button guarded by `confirm()` therefore
// does nothing at all, with no error anywhere — which is exactly how Delete
// shipped: it looked correct, type-checked, passed every Go test of the
// underlying RPC, and silently returned early on every click.
//
// The app has always asked with an action toast (showToast's third argument).
// This keeps it that way, because the next person to reach for `confirm()` will
// have no reason to suspect it.
func TestFrontendUsesNoNativeDialogs(t *testing.T) {
	// Word boundary, and not preceded by a dot or an identifier character, so
	// `confirmDeleteBuild(...)` and `this.confirm(...)` do not trip it.
	banned := regexp.MustCompile(`(^|[^\w.])(confirm|alert|prompt)\s*\(`)

	root := filepath.Join("frontend", "src")
	if _, err := os.Stat(root); err != nil {
		t.Skipf("no frontend source at %s", root)
	}

	var offenders []string
	err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		switch filepath.Ext(path) {
		case ".svelte", ".ts", ".js":
		default:
			return nil
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		for i, line := range strings.Split(string(raw), "\n") {
			trimmed := strings.TrimSpace(line)
			// Comments discussing the ban are fine — this file's own rationale
			// lives in one.
			if strings.HasPrefix(trimmed, "//") || strings.HasPrefix(trimmed, "*") {
				continue
			}
			if banned.MatchString(line) {
				offenders = append(offenders,
					filepath.ToSlash(path)+":"+itoa(i+1)+": "+trimmed)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("scanning the frontend: %v", err)
	}

	if len(offenders) > 0 {
		t.Errorf("native browser dialogs do not work in Wails — they are silently "+
			"ignored, so the code guarded by one never runs. Use showToast(text, "+
			"kind, [{label, onClick}]) instead.\n  %s",
			strings.Join(offenders, "\n  "))
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var digits []byte
	for n > 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	return string(digits)
}
