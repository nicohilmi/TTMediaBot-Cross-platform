@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TTMediaBot - Windows setup

rem Python 3.15 reads and writes text as UTF-8 by default; this gives older versions
rem the same behavior for pip and for the helper scripts started below.
if not defined PYTHONUTF8 set "PYTHONUTF8=1"

echo ==============================================================
echo  TTMediaBot - Windows setup
echo ==============================================================
echo.

rem ---- Options (for a run without questions) --------------------
rem   install_windows.bat --pot      install and start the PO token provider (steps 4 and 5)
rem   install_windows.bat --no-pot   skip steps 4 and 5
set "POT_CHOICE="
for %%A in (%*) do call :read_option "%%~A"

rem ---- Python ---------------------------------------------------
rem The bot is optimized for Python 3.15 and still runs on Python 3.10 or newer (64-bit).
call :find_python
if defined PY goto have_python

echo [INFO] Python 3.10 or newer (64-bit) was not found on this computer.
echo        Installing Python 3.15 through the Python install manager.
where winget >nul 2>nul
if errorlevel 1 goto python_manual
echo        winget install 9NQ7512CXL7T --accept-package-agreements
winget install 9NQ7512CXL7T --accept-package-agreements --accept-source-agreements
rem winget also reports an error when the manager is already installed, so only the
rem result counts: is the manager there now?
call :find_pymanager
if not defined PYM goto python_restart
echo        "%PYM%" install --configure -y
"%PYM%" install --configure -y
echo        "%PYM%" install -y 3.15
"%PYM%" install -y 3.15
call :find_python
if defined PY goto have_python
goto python_restart

:python_manual
echo [ERROR] Python 3.10 or newer (64-bit) was not found and winget is not available.
echo         Install Python 3.15 yourself (recommended):
echo           winget install 9NQ7512CXL7T --accept-package-agreements
echo           py install 3.15
echo         or download the Python install manager from https://www.python.org/downloads/
echo         Then open a NEW command window and run this file again.
goto fail

:python_restart
echo.
echo [INFO] Python 3.15 was requested, but this window cannot see it yet (Windows updates
echo        the search path only for windows opened afterwards). If the installation above
echo        reported a problem, fix it first. Then close this window, open a NEW one and
echo        run install_windows.bat again.
goto fail

:have_python
%PY% -c "import sys; print('[OK] Python {}.{}.{} ({}-bit) will be used.'.format(sys.version_info[0], sys.version_info[1], sys.version_info[2], 64 if sys.maxsize > 2**32 else 32))"
%PY% -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 15) else 1)" >nul 2>nul
if errorlevel 1 call :note_older_python
echo.

echo [1/6] Creating the virtual environment...
if exist "venv\Scripts\python.exe" goto venv_ready
%PY% -m venv venv
if errorlevel 1 goto fail
:venv_ready
"venv\Scripts\python.exe" -c "import sys; print('    Virtual environment: Python {}.{}.{}'.format(sys.version_info[0], sys.version_info[1], sys.version_info[2]))"

echo [2/6] Installing the Python requirements...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo [3/6] Installing the YouTube.js bridge. It needs Node.js and Git.
set "NODE_OK="
where node >nul 2>nul
if errorlevel 1 goto bridge_skipped
where npm >nul 2>nul
if errorlevel 1 goto bridge_skipped
where git >nul 2>nul
if errorlevel 1 goto bridge_skipped
set "NODE_OK=1"

pushd youtube_bridge
call npm install --omit=dev
set "NPM_RESULT=%errorlevel%"
popd
if "%NPM_RESULT%"=="0" goto bridge_done
echo [WARNING] npm install failed. YouTube playback will not work until it succeeds.
echo           Run "npm install --omit=dev" inside the youtube_bridge folder to see why.
goto bridge_done

:bridge_skipped
echo [WARNING] Node.js LTS and/or Git were not found, so the YouTube bridge was not installed.
echo           Install both and run this file again:
echo             winget install OpenJS.NodeJS.LTS
echo             winget install Git.Git
:bridge_done

echo [4/6] PO token provider (bgutil). YouTube answers "403 Forbidden" without it.
echo           One provider is enough for every bot on this computer: all bots use the
echo           same one on port 4416. If another bot already has it, answer N: steps 4
echo           and 5 are skipped, nothing is installed and no new window is opened.
if /i "%POT_CHOICE%"=="Y" goto pot_install
if /i "%POT_CHOICE%"=="N" goto pot_declined

set "POT_DEFAULT=Y"
set "POT_PROMPT=[Y/n]"
curl.exe -s -m 2 http://127.0.0.1:4416/ping >nul 2>nul
if errorlevel 1 goto pot_ask
echo           A PO token provider is answering on port 4416 right now.
set "POT_DEFAULT=N"
set "POT_PROMPT=[y/N]"

:pot_ask
set "ANSWER="
set /p "ANSWER=          Install and start the PO token provider for this bot? %POT_PROMPT%: "
if not defined ANSWER set "ANSWER=%POT_DEFAULT%"
set "ANSWER=%ANSWER:"=%"
if /i "%ANSWER%"=="y" goto pot_install
if /i "%ANSWER%"=="yes" goto pot_install
if /i "%ANSWER%"=="n" goto pot_declined
if /i "%ANSWER%"=="no" goto pot_declined
echo           Please type Y or N, then press Enter.
goto pot_ask

:pot_declined
echo     Skipped (your choice): the PO token provider is not installed.
echo           Make sure one provider is running on port 4416 before you start the bot.
echo [5/6] Skipped together with step 4: no provider is started.
goto launch_done

:pot_install
echo           Installing it. It needs Node.js and Git. This step can take a few minutes.
where node >nul 2>nul
if errorlevel 1 goto pot_skipped
where git >nul 2>nul
if errorlevel 1 goto pot_skipped

if exist "bgutil-provider\.git" goto pot_clone_done
git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git bgutil-provider
if errorlevel 1 goto pot_failed
:pot_clone_done

if exist "bgutil-provider\server\build\main.js" goto pot_done
if not exist "bgutil-provider\server\package.json" goto pot_failed
pushd bgutil-provider\server
call npm ci
if errorlevel 1 goto pot_failed_build
call npx tsc
if errorlevel 1 goto pot_failed_build
popd
goto pot_done

:pot_failed_build
popd
echo [WARNING] Building the PO token provider failed. Run these inside the bot folder to see why:
echo             cd bgutil-provider\server
echo             npm ci
echo             npx tsc
echo             cd ..\..
goto pot_done

:pot_failed
echo [WARNING] Could not download the PO token provider from GitHub. Check your internet
echo           connection and run this file again.
goto pot_done

:pot_skipped
echo [WARNING] Node.js and/or Git were not found, so the PO token provider was not installed.
echo           Install both (winget install OpenJS.NodeJS.LTS and winget install Git.Git),
echo           then run this file again.
:pot_done

echo [5/6] Starting the PO token provider in a second window...
if not exist "bgutil-provider\server\build\main.js" goto launch_skipped
curl.exe -s -m 2 http://127.0.0.1:4416/ping >nul 2>nul
if not errorlevel 1 goto launch_already
start "TTMediaBot PO token provider" cmd /k "cd /d ""%~dp0bgutil-provider\server"" && node build\main.js --port 4416"
echo     Started in a new window. Keep that window open while the bot is running.
goto launch_done

:launch_already
echo     Already running on port 4416, so nothing was started.
goto launch_done

:launch_skipped
echo     Skipped: bgutil-provider\server\build\main.js is missing (see the warning above).
:launch_done

echo [6/6] Checking FFmpeg and the TeamTalk 5 SDK library...
echo           Missing pieces are installed or downloaded for you: FFmpeg through winget
echo           (or Chocolatey / Scoop), the SDK from the official BearWare download page.
echo           The SDK is a .7z archive: it is downloaded and unpacked in your Temp folder
echo           and deleted afterwards; only TeamTalk5.dll, TeamTalk5.lib and TeamTalk.h
echo           stay, in the TeamTalk_DLL folder of the bot. When
echo           nothing on this computer can open .7z files, 7-Zip is installed with winget
echo           or its portable 7zr.exe is downloaded for the unpacking.
"venv\Scripts\python.exe" tools\setup_deps.py all
if errorlevel 1 goto deps_attention
goto finish

:deps_attention
echo.
echo [WARNING] FFmpeg and/or the TeamTalk library still need your attention. Read the
echo           messages above; they say what to do by hand. The bot cannot start before both
echo           are in place. Afterwards run this file again, or only this step with:
echo             venv\Scripts\python.exe tools\setup_deps.py all
echo           If only the TeamTalk library failed: download the Standard Edition for
echo           Windows 10/11 x64 in your browser from https://bearware.dk/?page_id=419
echo           and install that file with:
echo             venv\Scripts\python.exe tools\setup_deps.py sdk --sdk-file "C:\path\to\tt5sdk_v5.23a_win64.7z"

:finish
echo.
echo Done. Edit config.json, then start the bot with TTMediaBot.bat.
echo Run TTMediaBot.bat --check to verify which FFmpeg will be used.
echo.
pause
exit /b 0

:fail
echo.
echo Setup failed. Fix the problem above and run this file again.
pause
exit /b 1

rem ---------------------------------------------------------------
rem Subroutines (reached only through "call")
rem ---------------------------------------------------------------

:read_option
if /i "%~1"=="--pot" set "POT_CHOICE=Y"
if /i "%~1"=="--no-pot" set "POT_CHOICE=N"
exit /b 0

:find_python
rem Sets PY to the command that starts the best Python: 3.15 first, then any
rem 64-bit Python 3.10 or newer. PY stays empty when there is none.
set "PY="
call :try_python "py -V:3.15"
if defined PY exit /b 0
call :try_python "py -3.15"
if defined PY exit /b 0
call :try_python "py -3"
if defined PY exit /b 0
call :try_python "python"
exit /b 0

:try_python
set "CANDIDATE=%~1"
rem Standard input is closed here (nul) so a first-run question of the Python launcher
rem can never wait for a key press.
%CANDIDATE% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>nul <nul
if errorlevel 1 exit /b 0
set "PY=%CANDIDATE%"
exit /b 0

:find_pymanager
rem Sets PYM to the Python install manager command (empty when it cannot be found).
set "PYM="
where pymanager >nul 2>nul
if not errorlevel 1 set "PYM=pymanager"
if defined PYM exit /b 0
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pymanager.exe" set "PYM=%LOCALAPPDATA%\Microsoft\WindowsApps\pymanager.exe"
exit /b 0

:note_older_python
echo        Python 3.15 is the version the bot is optimized for; this one still works.
echo        To use 3.15 later: winget install 9NQ7512CXL7T --accept-package-agreements,
echo        then py install 3.15, delete the venv folder and run this file again.
exit /b 0
