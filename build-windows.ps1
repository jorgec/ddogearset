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
#   5. Rebuilds the Python solver (PyInstaller -> python\dist\solver.exe).
#   6. Locates glpsol.exe + its DLLs from the Chocolatey glpk package and
#      stages them, plus the solver, into bundled\windows-amd64\ - this is
#      what embed_windows_amd64.go embeds into the Go binary at compile time.
#      Unlike macOS, Windows needs no path-rewriting: the OS searches an
#      exe's own directory for DLLs first, so co-locating them is enough.
#   7. Runs `go mod download`, `npm install`, then `wails build` (plus an
#      NSIS installer build, if makensis.exe is available).
#   8. Copies the finished, self-contained build - and the NSIS installer,
#      if one was built - into dist\windows-amd64\, so that directory is
#      immediately ready to hand to someone else: they copy it and run it,
#      nothing else required on their end.
#
# DDOBuilderV2 (the game-data source) is NOT fetched by this script - the
# built app clones/pulls it itself on first run (app.go's
# ensureDDOBuilderData(), into a gitignored .\DDOBuilderV2). That requires
# SSH access to git@github.com:Maetrim/DDOBuilderV2.git on whatever account
# runs the app; this script checks that access and warns (not fails) if it
# can't confirm it.

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

# == 5. Python venv + solver rebuild =========================================
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

Write-Step "Rebuilding the Python solver with PyInstaller (this can take a minute)..."
Push-Location "python"
& "..\$VenvPyInstaller" --noconfirm solver.spec
Pop-Location
if (-not (Test-Path "python\dist\solver.exe")) {
    Fail "Expected python\dist\solver.exe after PyInstaller build - check python\solver.spec's 'name='."
}
Write-Ok "Solver rebuilt at python\dist\solver.exe."

# == 6. Stage bundled\windows-amd64\ (solver.exe + glpsol.exe + DLLs) =======
Write-Step "Staging bundled\windows-amd64\ (embedded into the Go binary at compile time)..."
$BundleDir = "bundled\windows-amd64"
New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null

Copy-Item "python\dist\solver.exe" "$BundleDir\solver.exe" -Force
Write-Ok "staged $BundleDir\solver.exe"

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

# == 7. DDOBuilderV2 SSH access check (not fetched here - see file header) ==
Write-Step "Checking SSH access to DDOBuilderV2's repo (the built app clones this itself)..."
$sshTest = & ssh -o BatchMode=yes -o ConnectTimeout=5 -T git@github.com 2>&1
if ($sshTest -match "successfully authenticated") {
    Write-Ok "SSH access to github.com confirmed."
} else {
    Write-Warn ("SSH access to github.com could not be confirmed. The app clones " + `
        "git@github.com:Maetrim/DDOBuilderV2.git on first run (app.go's " + `
        "ensureDDOBuilderData) - without SSH keys set up for that repo, the clone " + `
        "will fail and every solve will error until you fix that or manually place " + `
        "the repo at .\DDOBuilderV2 yourself.")
}

# == 8. Build ==================================================================
Write-Step "Running wails build (this compiles the frontend and the Go binary)..."
# No .exe suffix here -- wails appends the platform-appropriate extension
# itself (matches build-mac.sh's/build-linux.sh's `-o DDOGearsetOptimizer`;
# passing .exe explicitly here would risk a DDOGearsetOptimizer.exe.exe).
wails build -o DDOGearsetOptimizer
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
    wails build -o DDOGearsetOptimizer -nsis
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
