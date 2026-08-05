package main

import "embed"

// Not populated from this (darwin/arm64) machine — bundled/windows-amd64/
// must be built and committed from an actual windows/amd64 host by running
// build_releases.sh there. Attempting to build for windows/amd64 before that
// directory exists fails at compile time with a clear "no such file" error,
// which is the correct failure mode.
//
//go:embed all:bundled/windows-amd64
var bundleFS embed.FS

const (
	bundleRoot       = "bundled/windows-amd64"
	solverBinaryName = "solver.exe"
	glpsolBinaryName = "glpsol.exe"
)
