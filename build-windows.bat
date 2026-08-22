@echo off
REM build-windows.bat - double-clickable wrapper for build-windows.ps1.
REM
REM Deliberately does NOT require or request Administrator privileges. Just
REM run it normally. If a step inside build-windows.ps1 genuinely needs
REM elevation (mainly `choco install`, depending on your machine), it will
REM print the exact command to run once in a separate elevated window
REM instead of failing silently or trying to elevate itself.
REM
REM Arguments are forwarded to build-windows.ps1, so from a shell you can run
REM   build-windows.bat -UpdateData
REM to fetch the latest data\ddobuilder before the ETL.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1" %*
if %errorLevel% neq 0 (
    echo.
    echo build-windows.ps1 exited with an error ^(see above^).
    pause
    exit /b %errorLevel%
)

pause
