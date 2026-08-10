# build-windows.ps1 - Install every dependency and produce a self-contained
# Windows build of DDO Gearset Optimizer, assuming Chocolatey as the only
# package manager.
#
# Deliberately does NOT require or request elevation. Some steps below
# (mainly `choco install`) may still need an elevated shell on your machine,
# depending on how Chocolatey/Windows is configured - if a step fails, this
# script prints the EXACT command to run, once, in a separate elevated
# PowerShell/cmd window, then tells you to close that window and re-run this
# script normally (not elevated). Nothing in here ever tries to elevate
# itself, and nothing needs to stay elevated for the actual build - running
# PyInstaller (or anything else here) elevated is unnecessary and PyInstaller
# itself warns against it.
#
# Run from a normal (non-administrator) PowerShell prompt, from the repo root:
#   .\build-windows.ps1
#
# What it does, in order (every step below prints what it's doing and what it
# found before moving on - nothing should run silently):
#   1. Checks for Chocolatey; if missing, prints the one-time elevated
#      bootstrap command instead of running it for you.
#   2. Installs git, golang, nodejs-lts, python311, glpk, webview2-runtime,
#      nsis via `choco install` (unelevated first; on failure, prints the
#      elevated command to run once instead).
#   3. Creates a Python venv at python\.venv and installs pulp + pyinstaller.
#   4. Installs the Wails CLI (go install, pinned to match go.mod).
#   5. Builds catalog.db from the local DDOBuilderV2 checkout (the ETL).
#   6. Rebuilds the Python solver (PyInstaller --onedir ->
#      python\dist\solver\solver.exe plus its _internal\ tree).
#   7. Locates glpsol.exe + its DLLs from the Chocolatey glpk package and
#      stages them, plus the solver tree and catalog.db, into
#      bundled\windows-amd64\ - this is what embed_windows_amd64.go embeds
#      into the Go binary at compile time. Unlike macOS, Windows needs no
#      path-rewriting: the OS searches an exe's own directory for DLLs first,
#      so co-locating them is enough.
#   8. Runs `wails build` (plus an NSIS installer build, if makensis.exe is
#      available).
#   9. Copies the finished, self-contained build - and the NSIS installer,
#      if one was built - into dist\windows-amd64\, so that directory is
#      immediately ready to hand to someone else: they copy it and run it,
#      nothing else required on their end.
#
# The game data the ETL in step 5 reads is the data\ddobuilder SUBMODULE, so
# a fresh clone needs `git submodule update --init --depth 1` once (or
# `git clone --recurse-submodules` up front). Being a pinned submodule is the
# point: the catalog records the exact upstream revision it was built from.
# NOTHING fetches it at runtime any more - since 0.5.0 the shipped app carries
# catalog.db and never touches DDOBuilderV2, the network, or Python XML parsing
# (docs/0.5.0/00_ETL_START_HERE.md constraints 1 and 3).

$ErrorActionPreference = "Stop"

$WailsVersion = "v2.10.0"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

function Write-Step($msg) { Write-Host "-> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "OK $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "!! $msg" -ForegroundColor Yellow }
function Fail($msg)       { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$IsElevated = Test-Elevated
Write-Step "Running unelevated (Administrator: $IsElevated) - this script never elevates itself."
if (-not $IsElevated) {
    Write-Warn ("Not running as Administrator. That's intentional - most of this script " + `
        "should work fine without it. If the Chocolatey install step below fails with a " + `
        "permissions error, it will print the exact command to run once in a separate " + `
        "elevated window; you do not need to pre-elevate just in case.")
}

# == 0. Chocolatey itself =====================================================
Write-Step "Checking for Chocolatey..."
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Warn "Chocolatey is not installed."
    Write-Host ""
    Write-Host "Open PowerShell AS ADMINISTRATOR (one time only) and run exactly this:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host '  Set-ExecutionPolicy Bypass -Scope Process -Force' -ForegroundColor White
    Write-Host '  [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072' -ForegroundColor White
    Write-Host "  Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))" -ForegroundColor White
    Write-Host ""
    Write-Host "Then close that elevated window and re-run THIS script normally (not elevated)." -ForegroundColor Yellow
    exit 1
}
Write-Ok "Chocolatey found ($(choco --version))."

# == 1. System packages =======================================================
$ChocoPackages = "git golang nodejs-lts python311 glpk webview2-runtime nsis"
Write-Step "Installing Chocolatey packages: $ChocoPackages"
Write-Host "   (trying unelevated first - this works if Chocolatey is configured for" -ForegroundColor DarkGray
Write-Host "    per-user installs; if not, you'll get exact instructions below)" -ForegroundColor DarkGray
choco install -y git golang nodejs-lts python311 glpk webview2-runtime nsis
if ($LASTEXITCODE -ne 0) {
    Write-Warn "choco install failed (exit $LASTEXITCODE) - this is almost always a permissions issue."
    Write-Host ""
    Write-Host "Open PowerShell or cmd AS ADMINISTRATOR (one time only) and run exactly this," -ForegroundColor Yellow
    Write-Host "from this same directory ($RepoRoot):" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  choco install -y $ChocoPackages" -ForegroundColor White
    Write-Host ""
    Write-Host "Then close that elevated window and re-run THIS script normally (not elevated)." -ForegroundColor Yellow
    exit 1
}
Write-Ok "Chocolatey packages installed."

# Chocolatey updates machine PATH, but this session doesn't see it yet.
# Re-import it from the registry so the rest of this script (and anything it
# shells out to) can find the tools just installed.
Write-Step "Refreshing PATH for this session..."
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"
Write-Ok "PATH refreshed."

Write-Step "Verifying git, go, node, npm, python are all reachable..."
foreach ($tool in @("git", "go", "node", "npm", "python")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Fail ("$tool not found on PATH even after refresh. Close this window, open a NEW " + `
             "PowerShell window (still unelevated), and re-run this script.")
    }
}
Write-Ok "git, go, node, npm, python all on PATH."

# == 2. Wails CLI ==============================================================
Write-Step "Installing Wails CLI $WailsVersion (go install)..."
go install "github.com/wailsapp/wails/v2/cmd/wails@$WailsVersion"
$GoBin = Join-Path (go env GOPATH) "bin"
if ($env:Path -notlike "*$GoBin*") { $env:Path = "$GoBin;$env:Path" }
if (-not (Get-Command wails -ErrorAction SilentlyContinue)) {
    Fail "wails CLI installed to $GoBin but not found on PATH."
}
Write-Ok "Wails CLI ready ($(wails version))."

# == 3. Go modules ============================================================
Write-Step "Downloading Go module dependencies (go mod download)..."
go mod download
Write-Ok "Go modules ready."

# == 4. Frontend ===============================================================
Write-Step "Installing frontend npm dependencies..."
Push-Location "frontend"
npm install --silent
Pop-Location
Write-Ok "Frontend dependencies ready."

# == 4b. Python venv ==========================================================
$VenvDir = "python\.venv"
if (-not (Test-Path $VenvDir)) {
    Write-Step "Creating Python venv at $VenvDir..."
    python -m venv $VenvDir
    Write-Ok "Venv created."
} else {
    Write-Step "Python venv already exists at $VenvDir, reusing it."
}
$VenvPip = "$VenvDir\Scripts\pip.exe"
$VenvPyInstaller = "$VenvDir\Scripts\pyinstaller.exe"
Write-Step "Installing Python dependencies (pulp, pyinstaller) into the venv..."
& $VenvPip install --quiet --upgrade pip
& $VenvPip install --quiet -r python\requirements.txt pyinstaller
Write-Ok "Python venv ready."

# == 5. Build catalog.db from DDOBuilderV2 (the ETL) =========================
# $env:RELEASE = "0" builds permissively for day-to-day dev; the default (1)
# passes --strict, so an unexplained rename in DDOBuilderV2 fails the build
# instead of quietly minting a new identity that orphans saved gearsets
# (docs/0.5.0/00_ETL_START_HERE.md section 6.2).
$Release = if ($env:RELEASE) { $env:RELEASE } else { "1" }
if ($Release -eq "1") {
    Write-Step "Building catalog.db (strict - unresolved identity drift fails the build)..."
    python -m etl --out "bundled\windows-amd64\catalog.db" --strict
} else {
    Write-Step "Building catalog.db (permissive - RELEASE=0)..."
    python -m etl --out "bundled\windows-amd64\catalog.db"
}
if ($LASTEXITCODE -eq 2) {
    Write-Host ""
    Fail ("DDOBuilderV2 renamed something the ETL will not guess at. Read the drift " + `
          "report it just wrote under etl\drift\, record the answers in " + `
          "etl\aliases.yaml, and re-run. To build anyway (dev only, new identities " + `
          "get minted): `$env:RELEASE = '0'; .\build-windows.ps1")
} elseif ($LASTEXITCODE -ne 0) {
    Fail "The ETL failed (exit $LASTEXITCODE) - see output above."
}
Write-Ok "catalog.db built."

# == 6. Solver rebuild ========================================================
Write-Step "Rebuilding the Python solver with PyInstaller (this can take a minute)..."
Push-Location "python"
& "..\$VenvPyInstaller" --noconfirm solver.spec
Pop-Location
# --onedir (python\solver.spec): an executable plus an _internal\ tree it
# cannot start without. Both are staged; app.go's extractSolver recurses.
if (-not (Test-Path "python\dist\solver\solver.exe")) {
    Fail ("Expected python\dist\solver\solver.exe after PyInstaller build - check " + `
          "python\solver.spec (it must have a COLLECT step; --onefile puts the binary " + `
          "at python\dist\solver.exe instead).")
}
Write-Ok "Solver rebuilt at python\dist\solver\solver.exe."

# == 7. Stage bundled\windows-amd64\ (solver tree + glpsol.exe + DLLs) =====
Write-Step "Staging bundled\windows-amd64\ (embedded into the Go binary at compile time)..."
$BundleDir = "bundled\windows-amd64"
New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null

# Wipe the previous solver tree first: PyInstaller's output is authoritative,
# and a file it no longer produces must not survive into the bundle. Explicitly
# NOT the whole $BundleDir - glpsol.exe, its DLLs and catalog.db live there too
# and are staged by other steps.
Remove-Item "$BundleDir\_internal" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$BundleDir\solver.exe" -Force -ErrorAction SilentlyContinue
Copy-Item "python\dist\solver\_internal" "$BundleDir\_internal" -Recurse -Force
Copy-Item "python\dist\solver\solver.exe" "$BundleDir\solver.exe" -Force
$InternalCount = (Get-ChildItem "$BundleDir\_internal" -Recurse -File).Count
Write-Ok "staged $BundleDir\solver.exe + _internal\ ($InternalCount files)"

# The Chocolatey glpk package installs winglpk under
# C:\ProgramData\chocolatey\lib\glpk\tools\ - search it rather than hardcode
# an exact version-numbered subfolder (e.g. w64\), since that changes between
# GLPK releases.
Write-Step "Locating glpsol.exe from the Chocolatey glpk package..."
$ChocoLib = Join-Path $env:ChocolateyInstall "lib\glpk\tools"
$GlpsolExe = Get-ChildItem -Path $ChocoLib -Recurse -Filter "glpsol.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $GlpsolExe) {
    Fail "glpsol.exe not found under $ChocoLib - did 'choco install glpk' succeed?"
}
$GlpkDir = $GlpsolExe.DirectoryName
Write-Ok "Found glpsol.exe at $($GlpsolExe.FullName)"

Copy-Item $GlpsolExe.FullName "$BundleDir\glpsol.exe" -Force
Write-Ok "staged $BundleDir\glpsol.exe"

# Windows resolves DLLs from an exe's own directory first (unlike macOS/Linux,
# no rpath/LD_LIBRARY_PATH rewriting is needed) - just copy every DLL sitting
# alongside glpsol.exe so nothing it needs is missing at runtime.
Write-Step "Copying glpsol's DLLs alongside it..."
Get-ChildItem -Path $GlpkDir -Filter "*.dll" | ForEach-Object {
    Copy-Item $_.FullName "$BundleDir\$($_.Name)" -Force
    Write-Ok "staged $BundleDir\$($_.Name)"
}

# == 8. Build =================================================================
# go:embed reads the FILESYSTEM, not git - anything sitting in $BundleDir right
# now is compiled into the shipped binary, tracked or not. SQLite's WAL
# sidecars appear whenever something opens the bundled catalog read-write, and
# the solver drops a progress log wherever it runs. Both are gitignored, so
# without this they would ride into a release completely unnoticed.
Write-Step "Clearing runtime debris out of $BundleDir before embedding..."
# "$BundleDir\*", not "$BundleDir" - -Include is silently ignored on a plain
# directory path (it only applies to a wildcarded path or with -Recurse), and
# would quietly match nothing.
Get-ChildItem "$BundleDir\*" -File -Include "*.db-wal", "*.db-shm", "*.log" -ErrorAction SilentlyContinue |
    Remove-Item -Force
Write-Ok "done."

Write-Step "Running wails build (this compiles the frontend and the Go binary)..."
# Confirmed by an actual Windows run: wails does NOT append .exe to -o itself
# on Windows (unlike the assumption this script started with) -- it writes
# exactly the name given. Without the explicit .exe here, the build produced
# a plain 'DDOGearsetOptimizer' file with no extension at all. -o must
# include .exe explicitly on Windows.
wails build -o DDOGearsetOptimizer.exe
if ($LASTEXITCODE -ne 0) { Fail "wails build failed - see output above." }

$BuiltPath = "build\bin\DDOGearsetOptimizer.exe"
if (-not (Test-Path $BuiltPath)) {
    Write-Warn "Expected output not found at '$BuiltPath' - check build\bin\ manually."
    Get-ChildItem "build\bin" -ErrorAction SilentlyContinue
    Fail "Build did not produce the expected .exe - stopping before the dist\ copy step."
}
Write-Ok "wails build produced $BuiltPath"

$Makensis = Get-Command makensis -ErrorAction SilentlyContinue
$InstallerPath = $null
if ($Makensis) {
    Write-Step "makensis found - also building an NSIS installer..."
    wails build -o DDOGearsetOptimizer.exe -nsis
    if ($LASTEXITCODE -eq 0) {
        $found = Get-ChildItem "build\bin" -Filter "*-installer.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $InstallerPath = $found.FullName
            Write-Ok "NSIS installer built: $InstallerPath"
        } else {
            Write-Warn "wails build -nsis exited 0 but no *-installer.exe was found in build\bin - skipping it."
        }
    } else {
        Write-Warn "NSIS installer build failed (exit $LASTEXITCODE) - continuing with just the plain .exe."
    }
} else {
    Write-Warn "makensis.exe not on PATH (nsis package may need a new shell to register) - skipping the installer build. The plain .exe below is still fully self-contained."
}

# == 9. Copy into dist\windows-amd64\ - the "just copy and run" folder ======
Write-Step "Copying the finished build into dist\windows-amd64\..."
$DistDir = "dist\windows-amd64"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
Copy-Item $BuiltPath "$DistDir\DDOGearsetOptimizer.exe" -Force
Write-Ok "copied $DistDir\DDOGearsetOptimizer.exe"
if ($InstallerPath) {
    Copy-Item $InstallerPath "$DistDir\DDOGearsetOptimizer-Setup.exe" -Force
    Write-Ok "copied $DistDir\DDOGearsetOptimizer-Setup.exe"
}

Write-Host ""
Write-Ok "Build complete (self-contained, windows-amd64)."
Write-Ok "Ready to hand off from: $((Resolve-Path $DistDir).Path)"
Write-Ok "Bundle staged at: $BundleDir\ - commit it so this build is reproducible without redoing the glpsol staging step."
