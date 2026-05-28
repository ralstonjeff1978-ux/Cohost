@echo off
REM ============================================================
REM   COHOST — One-click installer wrapper
REM   Hans: double-click this file.
REM ============================================================
setlocal
cd /d "%~dp0"
echo.
echo Starting Cohost installer. This may take 10-20 minutes.
echo Window will stay open at the end. If anything fails the log
echo lives at  install\install_log.txt — please send it back.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1"
echo.
echo ============================================================
echo  Installer finished. Window stays open so you can read it.
echo ============================================================
pause
