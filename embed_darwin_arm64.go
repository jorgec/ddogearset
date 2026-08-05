package main

import "embed"

// Go's filename-based build-constraint convention (_GOOS_GOARCH.go) means
// this file compiles only when targeting darwin/arm64. See the comment above
// bundleFS's declaration-site sibling in app.go for why this is per-platform.
//
//go:embed all:bundled/darwin-arm64
var bundleFS embed.FS

const (
	bundleRoot       = "bundled/darwin-arm64"
	solverBinaryName = "solver"
	glpsolBinaryName = "glpsol"
)
