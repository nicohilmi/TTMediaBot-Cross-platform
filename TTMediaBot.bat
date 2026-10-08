@echo off
setlocal
cd /d "%~dp0"
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
