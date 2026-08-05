@echo off
REM build-windows.bat - double-clickable wrapper for build-windows.ps1.
REM
REM Deliberately does NOT require or request Administrator privileges. Just
REM run it normally. If a step inside build-windows.ps1 genuinely needs
REM elevation (mainly `choco install`, depending on your machine), it will
REM print the exact command to run once in a separate elevated window
REM instead of failing silently or trying to elevate itself.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1"
if %errorLevel% neq 0 (
    echo.
    echo build-windows.ps1 exited with an error ^(see above^).
    pause
    exit /b %errorLevel%
)

pause
