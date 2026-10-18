@echo off
setlocal
cd /d "%~dp0"
rem Python 3.15 reads and writes text as UTF-8 by default; this gives older versions
rem the same behavior, so song titles and settings read the same on every version.
if not defined PYTHONUTF8 set "PYTHONUTF8=1"
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=python"
)
"%PY%" TTMediaBot.py %*
if errorlevel 1 (
    echo.
    echo The bot stopped with an error. See the message above or TTMediaBot.log.
    pause
)
