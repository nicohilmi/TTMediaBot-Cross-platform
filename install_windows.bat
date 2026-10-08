@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TTMediaBot - Windows setup

echo ==============================================================
echo  TTMediaBot - Windows setup
echo ==============================================================
echo.

rem ---- Python ---------------------------------------------------
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto have_python
echo [ERROR] Python 3.9 or newer was not found.
echo         Install the 64-bit version from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH", then run this file again.
goto fail

:have_python
echo [1/4] Creating the virtual environment...
if exist "venv\Scripts\python.exe" goto venv_ready
%PY% -m venv venv
if errorlevel 1 goto fail
:venv_ready

echo [2/4] Installing the Python requirements...
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

echo [4/6] Installing the PO token provider (bgutil). It needs Node.js and Git.
echo           YouTube answers "403 Forbidden" without it. This step can take a few minutes.
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

echo [6/6] Checking FFmpeg and the TeamTalk library...
set "FF_OK="
if exist "ffmpeg.exe" set "FF_OK=1"
where ffmpeg >nul 2>nul
if not errorlevel 1 set "FF_OK=1"
if defined FF_OK goto ffmpeg_found
echo [WARNING] FFmpeg was not found. Either install it system-wide with:
echo             winget install ffmpeg
echo           or download a build from https://www.gyan.dev/ffmpeg/builds/ and copy
echo           ffmpeg.exe into this folder, right beside TTMediaBot.py.
goto check_teamtalk
:ffmpeg_found
echo     FFmpeg: found.

:check_teamtalk
if exist "TeamTalk5.dll" goto teamtalk_found
echo [WARNING] TeamTalk5.dll is missing. Copy the 64-bit TeamTalk 5 SDK library
echo           into this folder, right beside TTMediaBot.py. SDK 5.11 or newer is needed.
goto finish
:teamtalk_found
echo     TeamTalk5.dll: found.

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
