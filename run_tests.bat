@echo off
rem Runs every test of the project: run this before every git commit.
rem   run_tests.bat            all tests
rem   run_tests.bat -v         one line per test
rem   run_tests.bat -k fade    only the tests whose name contains "fade"
rem   run_tests.bat -f         stop at the first failure
setlocal
cd /d "%~dp0"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"

if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
    echo [NOTE] venv\Scripts\python.exe was not found, so python from PATH is used.
    echo        Run install_windows.bat first if packages are reported missing.
)

"%PYTHON%" tools\run_tests.py %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo.
if not "%RESULT%"=="0" echo [FAILED] Exit code %RESULT%. Do not commit until the tests pass.
exit /b %RESULT%
