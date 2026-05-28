@echo off
REM ============================================================
REM   COHOST — Web Interface Launcher
REM   Double-click to start Aria with the visual interface.
REM   Opens http://localhost:6500 in your browser (first free of 6500-6510).
REM ============================================================
setlocal
cd /d "%~dp0"

set "COHOST_HOME=%~dp0"
REM Trim trailing backslash so Python's pathlib resolves cleanly
if "%COHOST_HOME:~-1%"=="\" set "COHOST_HOME=%COHOST_HOME:~0,-1%"

if not exist ".venv\Scripts\python.exe" (
    echo Cohost is not installed yet. Double-click INSTALL.bat first.
    pause
    exit /b 1
)

REM Kill any existing cohost processes to prevent duplicates
echo Cleaning up old processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'web.app\.py|tts_server\.py|whisper_server\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 2 /nobreak >nul

echo Starting Aria web interface...
echo.
start "" http://localhost:6500
".venv\Scripts\python.exe" web\app.py
echo.
echo Cohost ended. Window stays open so you can read any errors.
pause
