package main

import "embed"

// Not populated from this (darwin/arm64) machine — bundled/linux-amd64/ must
// be built and committed from an actual linux/amd64 host by running
// build_releases.sh there. Attempting to build for linux/amd64 before that
// directory exists fails at compile time with a clear "no such file" error,
// which is the correct failure mode.
//
//go:embed all:bundled/linux-amd64
var bundleFS embed.FS

const (
	bundleRoot       = "bundled/linux-amd64"
	solverBinaryName = "solver"
	glpsolBinaryName = "glpsol"
)
