@echo off
REM ============================================================
REM   COHOST — Launcher
REM   Hans: double-click this to start Aria in voice mode.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Cohost is not installed yet. Double-click INSTALL.bat first.
    pause
    exit /b 1
)

echo Starting Cohost...
echo.
".venv\Scripts\python.exe" cohost.py --voice
echo.
echo Cohost ended. Window stays open so you can read any errors.
pause
