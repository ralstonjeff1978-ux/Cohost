@echo off
REM ============================================================
REM   COHOST — Self-test wrapper
REM   Hans: double-click this AFTER INSTALL.bat completes.
REM   It produces  install\selftest_report.txt  —
REM   please email that file back.
REM ============================================================
setlocal
cd /d "%~dp0"
echo.
echo Running self-test...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\selftest.ps1"
echo.
echo ============================================================
echo  Report saved to:  install\selftest_report.txt
echo  Please send that file back.
echo ============================================================
pause
