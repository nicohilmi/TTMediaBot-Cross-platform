# TTMediaBot — Windows Guide

**Hello! I am nicohilmi.** This is the complete Windows guide for **TTMediaBot-Cross-platform**, my Windows and Linux port of the TTMediaBot fork by João Almeida. The bot streams music from YouTube, YouTube Music, local files and URLs into a TeamTalk 5 channel.

> 🔗 **My Repository:** [https://github.com/nicohilmi/TTMediaBot-Cross-platform](https://github.com/nicohilmi/TTMediaBot-Cross-platform)

> **Note:** This project is a fork of [João Almeida's TTMediaBot](https://github.com/JoaoDEVWHADS/TTMediaBot), which is itself a fork of the [original TTMediaBot](https://github.com/gumerov-amir/TTMediaBot) by gumerov-amir.

The main [README.md](README.md) describes the Linux/Docker deployment. This file is its Windows counterpart: the commands, services and features are the same, but the installation, configuration, logs and troubleshooting are written for Windows without Docker.

## 📑 Contents

- [What Is Different on Windows](#-what-is-different-on-windows)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Running the Bot](#-running-the-bot)
- [YouTube Bridge and PO-Token Provider](#-youtube-bridge-and-po-token-provider)
- [YouTube Music, Autoplay and Downloads](#-youtube-music-autoplay-and-downloads)
- [AI (Gemini)](#-ai-gemini)
- [Commands](#-commands)
- [YouTube & YouTube Music Cookies](#-youtube--youtube-music-cookies)
- [Supported Languages](#-supported-languages)
- [Troubleshooting](#-troubleshooting)
- [FAQ](#-faq-frequently-asked-questions)
- [Logs and Monitoring](#-logs-and-monitoring)
- [Updating](#-updating)
- [Uninstalling](#-uninstalling)
- [Legal Disclaimer & Terms of Use](#-legal-disclaimer--terms-of-use)

---

## 📋 What Is Different on Windows

- **No Docker, no PulseAudio, no mpv.** FFmpeg decodes every file and stream, and the audio goes straight to TeamTalk through its *virtual sound device*. No sound card, sound server or virtual audio cable is needed.
- **One folder holds everything.** The configuration, logs, cache and downloads all live in the bot folder.
- **`install_windows.bat`** creates the Python environment and installs the requirements, the YouTube.js bridge and the PO-token provider.
- **`TTMediaBot.bat`** starts the bot. The YouTube.js bridge is started automatically with the bot and stopped when the bot exits.
- **The PO-token provider runs in a second window** (port `4416`) that must stay open while the bot runs.
- **Windows-safe behavior:** download folders no longer use hard-coded Linux paths, file names are sanitised for Windows, and restarting the bot with `rs` works.

---

## 📦 Requirements

| Component | Needed version | Used for |
| :--- | :--- | :--- |
| **Python** | **3.15 recommended** (the bot is optimized for it); 3.10 or newer still works. **64-bit** | The bot itself |
| **Node.js** | LTS | The YouTube.js bridge and the PO-token provider |
| **Git** | Any recent version | Downloading the bot and installing the bridge and provider from GitHub |
| **FFmpeg** | Any recent build (`install_windows.bat` installs it when it is missing) | Decoding audio |
| **TeamTalk 5 SDK library** | `TeamTalk5.dll`, **64-bit**, SDK **5.11 or newer** (5.23a is the newest stable release; `install_windows.bat` downloads it) | Connecting to the TeamTalk server |
| **A TeamTalk account** | — | The login the bot uses on your server |
| **A Google account cookie file** | — | Recommended for reliable YouTube playback (see [cookies](#-youtube--youtube-music-cookies)) |

---

## 🚀 Installation

Run every command below from PowerShell or Command Prompt opened in the bot folder.

### Step 1 — Install the prerequisites

1. Install **Python 3.15, 64-bit** (3.10 or newer still works). Python for Windows is now installed through the *Python install manager*:
   ```powershell
   winget install 9NQ7512CXL7T --accept-package-agreements
   py install 3.15
   ```
   You can skip this step: `install_windows.bat` runs the same two commands when it finds no suitable Python. The manager is also on <https://www.python.org/downloads/> and in the Microsoft Store.
2. Install Node.js LTS, Git and FFmpeg:
   ```powershell
   winget install OpenJS.NodeJS.LTS
   winget install Git.Git
   winget install --id Gyan.FFmpeg -e
   ```
3. **Close and reopen the terminal** so the new `PATH` is picked up.

If you prefer not to install FFmpeg system-wide, download a build from <https://www.gyan.dev/ffmpeg/builds/> or <https://github.com/BtbN/FFmpeg-Builds> and copy `ffmpeg.exe` right beside `TTMediaBot.py`.

### Step 2 — Download the bot

```powershell
git clone https://github.com/nicohilmi/TTMediaBot-Cross-platform.git
cd TTMediaBot-Cross-platform
```

You can also use **Code → Download ZIP** on GitHub and extract it. Keep the folder somewhere your user account can write to (for example `D:\TTMediaBot`), not inside `Program Files`.

### Step 3 — Add the TeamTalk library

`install_windows.bat` downloads the newest stable TeamTalk 5 SDK from the official BearWare page <https://bearware.dk/?page_id=419> and puts the files the bot needs into the **`TeamTalk_DLL` folder inside the bot folder** (for example `D:\root\TTMediaBot\TeamTalk_DLL`), exactly three files and nothing beside `TTMediaBot.py`:

```text
TeamTalk_DLL\
├── TeamTalk5.dll    64-bit library (the bot loads this one)
├── TeamTalk5.lib    import library of the SDK
└── TeamTalk.h       C header of the SDK
```

The DLL is test-loaded from the temporary folder first and again from `TeamTalk_DLL`; when it does not load there, your previous files are put back and nothing half-installed stays. The archive and the unpacked SDK live in a temporary folder inside your Windows `Temp` folder and are deleted afterwards, with every other file of the SDK (documentation, examples, other languages). **Coming from 4.2.0:** that version copied `TeamTalk5.dll` beside `TTMediaBot.py`. The next run of the installer (or `venv\Scripts\python.exe tools\setup_deps.py sdk`) moves that DLL into `TeamTalk_DLL` without a download, completes the folder with the `.lib` and the header, and deletes the old copy (a stale one beside the bot could be found before the new one). The bot only needs the DLL; the `.lib` and the header are for C/C++ developers. SDK 5.11 or newer is required for the virtual sound device. BearWare distributes the SDK download as a 30 day trial.

**7-Zip.** The SDK is a `.7z` archive. The installer opens it with 7-Zip when it is installed, then with `tar.exe` of Windows 10/11. When nothing can open it, it installs 7-Zip with `winget install --id 7zip.7zip` and, when winget is missing or fails, downloads the portable `7zr.exe` from 7-zip.org into the temporary folder (nothing is installed and the file is deleted with the folder).

**Downloads.** The installer identifies itself as a browser, chosen at random from `tools\user_agents.txt` (one per line); when a site answers `403`, `406` or `429` it asks again with the next one. Add or remove lines in that file as you like.

If the installer cannot do it (no internet, the page changed), it prints the manual steps: download the *Standard Edition* for *Windows 10/11 x64*, then in a command window:
```bat
7z x -y -o"%TEMP%\ttsdk" tt5sdk_*_win64.7z
if not exist "D:\TTMediaBot-master\TeamTalk_DLL" mkdir "D:\TTMediaBot-master\TeamTalk_DLL"
copy "%TEMP%\ttsdk\Library\TeamTalk_DLL\TeamTalk5.dll" "D:\TTMediaBot-master\TeamTalk_DLL"
copy "%TEMP%\ttsdk\Library\TeamTalk_DLL\TeamTalk5.lib" "D:\TTMediaBot-master\TeamTalk_DLL"
copy "%TEMP%\ttsdk\Library\TeamTalk_DLL\TeamTalk.h" "D:\TTMediaBot-master\TeamTalk_DLL"
rmdir /s /q "%TEMP%\ttsdk"
```
(use your own bot folder in the `mkdir` and `copy` lines; if the file is not at that path, find it with `dir /s /b "%TEMP%\ttsdk\TeamTalk5.dll"`). Run only this step again with `venv\Scripts\python.exe tools\setup_deps.py sdk` (`--force` fetches it again).

**When the download fails** (the message lists every attempt, for example `HTTP Error 454` from the site's bot filter): the installer asks the site again with other browser identities and then with the programs of Windows itself (`curl.exe`, then PowerShell), and finally tries the file name of the newest release it knows directly, for example <https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z>. If all of that is refused, download the Standard Edition for Windows 10/11 x64 from <https://bearware.dk/?page_id=419> in your browser and let the installer do the unpacking, test-loading and copying: `venv\Scripts\python.exe tools\setup_deps.py sdk --sdk-file "C:\Users\you\Downloads\tt5sdk_v5.23a_win64.7z"`. SDK 5.11 or newer is required for the virtual sound device. BearWare distributes the SDK download as a 30 day trial. The bot also looks in a `TeamTalk_DLL\` folder inside the bot folder.

### Step 4 — Run the installer

```powershell
.\install_windows.bat
```

You can also double-click the file. The installer prints a message for each step:

| Step | What it does |
| :--- | :--- |
| 1 | Looks for Python 3.15 first, then any 64-bit Python 3.10 or newer (`py -V:3.15`, `py -3`, `python`). When there is none it installs Python 3.15 with `winget install 9NQ7512CXL7T --accept-package-agreements` and `py install 3.15`. Then it creates the `venv` virtual environment. |
| 2 | Upgrades `pip` and installs `requirements.txt` into the environment. |
| 3 | Installs the YouTube.js bridge in `youtube_bridge\` with `npm install --omit=dev`. Needs Node.js and Git. |
| 4 | **Asks whether to install the PO-token provider** (`Y` or `N`, then Enter). On `Y` it clones the provider into `bgutil-provider\` and builds it (`npm ci`, `npx tsc`); this can take a few minutes. On `N`, steps 4 and 5 are skipped. |
| 5 | Starts the PO-token provider in a **second window** on port `4416`. Keep that window open while the bot runs. Skipped when you answered `N`. |
| 6 | Checks that FFmpeg and `TeamTalk5.dll` are available and installs what is missing: FFmpeg through winget, the SDK from BearWare (unpacked in `%TEMP%`, with 7-Zip installed or a portable `7zr.exe` when nothing else can open the `.7z`; `TeamTalk5.dll`, `TeamTalk5.lib` and `TeamTalk.h` go into the bot's `TeamTalk_DLL` folder). A warning is printed for each piece that could not be set up. |

**Why step 4 asks.** One PO-token provider listening on port `4416` is enough for every bot on the computer. If you already installed or started it for another bot, answer `N`: nothing is installed again and no new window is opened. When something already answers on port `4416` the installer says so and `N` is the default (just press Enter); otherwise `Y` is the default. For a run without questions use `install_windows.bat --pot` (install and start) or `install_windows.bat --no-pot` (skip steps 4 and 5).

If a step prints `[WARNING]`, fix the problem it names and run `install_windows.bat` again. Existing work is reused: the `venv` is kept and a PO-token provider that is already built or already running is not touched.

### Step 5 — Configure the bot

Edit `config.json` with a text editor (Notepad is fine). At minimum set the TeamTalk server address, the bot login, the channel and the administrators. See [Configuration](#-configuration).

### Step 6 — Check the setup

```powershell
.\TTMediaBot.bat --check
```

This prints which FFmpeg the bot will use.

### Step 7 — Start the bot

```powershell
.\TTMediaBot.bat
```

You can also double-click `TTMediaBot.bat`. Make sure the **PO-token provider window** from step 5 is open (see [Starting the PO-token provider again](#starting-the-po-token-provider-again)).

### Folder layout after installation

```text
TTMediaBot-Cross-platform\
├── TTMediaBot.py            the bot
├── TTMediaBot.bat           starts the bot
├── install_windows.bat      installer
├── config.json              your settings
├── TeamTalk_DLL\            TeamTalk5.dll, TeamTalk5.lib, TeamTalk.h (installed by install_windows.bat, step 3)
├── ffmpeg.exe               optional, if not installed system-wide
├── venv\                    Python environment (created by the installer)
├── youtube_bridge\          YouTube.js bridge (node_modules\ is created by the installer)
├── bgutil-provider\         PO-token provider (cloned and built by the installer)
├── data\                    downloads and the bridge's cookie copy
├── TTMediaBot.log           bot log
├── youtube_bridge.log       bridge log
└── TTMediaBotCache.dat      recents and favorites
```

---

## 📝 Configuration

All settings are in `config.json`. If you want the complete list of options, `config_default.json` holds every key with its default value.

### Minimal TeamTalk settings

```json
"teamtalk": {
    "hostname": "tt.example.com",
    "tcp_port": 10333,
    "udp_port": 10333,
    "encrypted": false,
    "nickname": "TTMediaBot",
    "username": "mediabot",
    "password": "your-password",
    "channel": "/",
    "users": {
        "admins": ["your-tt-username"],
        "banned_users": []
    }
}
```

### Most used options

| Option | Default | Meaning |
| :--- | :--- | :--- |
| `general.language` | `"en"` | Interface language. See [Supported Languages](#-supported-languages). |
| `general.send_channel_messages` | `true` | Whether the bot sends messages to the channel. |
| `general.blocked_commands` | `[]` | Commands nobody can use. |
| `general.delete_uploaded_files_after` | `300` | Seconds after which files the bot uploaded to the channel are deleted. `0` keeps them. |
| `general.start_commands` | `[]` | Commands the bot runs by itself at startup. |
| `general.cache_file_name` | `"TTMediaBotCache.dat"` | File that stores recents and favorites. |
| `player.default_volume` | `50` | Volume at startup. |
| `player.max_volume` | `100` | Highest volume that can be set. |
| `player.volume_fading` | `true` | Fade the volume when stopping or changing track. |
| `player.fade_out_on_stop` | `true` | `s` lowers the volume to silence before it stops. Admins can switch it with `fo`. |
| `player.fade_out_duration` | `3.0` | Length of that fade-out in seconds. `fo 5` sets it to 5. |
| `player.seek_step` | `5` | Default seconds for `sb` and `sf`. |
| `player.ffmpeg_path` | `""` | Force a specific FFmpeg. Empty means auto-detect. |
| `player.buffer_seconds` | `5.0` | Seconds of decoded audio kept ahead of playback to ride out network jitter. |
| `player.network_timeout` | `30.0` | Seconds without network data before a stream is treated as dead. |
| `player.volume_curve` | `"cubic"` | `cubic` keeps the loudness of the former mpv volume scale (50 stays 50). `linear` is a plain percentage. |
| `teamtalk.encrypted` | `false` | Set `true` if the server uses encryption. |
| `teamtalk.channel` | `"/"` | Channel the bot joins. |
| `teamtalk.reconnection_attempts` | `-1` | How many times the bot retries after losing the server. `-1` means forever. |
| `teamtalk.reconnection_timeout` | `10` | Seconds between reconnection attempts. |
| `teamtalk.users.admins` | `["admin"]` | TeamTalk usernames allowed to use admin commands. |
| `updater.enabled` | `true` | Check GitHub for new commits in the background and announce them in the channel. |
| `updater.check_interval_minutes` | `60` | Minutes between checks (1 or more). |
| `updater.remote` | `"origin"` | Git remote to watch. The branch is the one the bot folder is on. |
| `teamtalk.users.banned_users` | `[]` | Usernames that cannot use the bot. |
| `services.default_service` | `"yt"` | Service used at startup: `yt` or `ytm`. |
| `services.yt.cookiefile_path` | `""` | Path to your `cookies.txt`. See [cookies](#-youtube--youtube-music-cookies). |
| `services.yt.search_results` / `services.ytm.search_results` | `1` | How many results a search returns. |
| `logger.level` | `"INFO"` | Log detail: `DEBUG`, `INFO`, `WARNING` or `ERROR`. |

The older `sound_devices` and `player_options` sections are ignored.

### Windows paths in JSON

A backslash is an escape character in JSON, so a path written as `D:\TTMediaBot\cookies.txt` makes the file invalid. Use **forward slashes** or **doubled backslashes**:

```json
"cookiefile_path": "D:/data/TTMediaBot/cookies.txt"
"cookiefile_path": "D:\\data\\TTMediaBot\\cookies.txt"
```

### Command-line options

`TTMediaBot.bat` passes its arguments to `TTMediaBot.py`.

| Option | Meaning |
| :--- | :--- |
| `-c`, `--config` | Path to the configuration file. Default is `config.json` in the bot folder. |
| `-C`, `--cache` | Path to the cache file. |
| `-l`, `--log` | Path to the log file. |
| `--check` (also `--devices`) | Prints which FFmpeg will be used. |
| `--default-config` | Saves the default configuration to `config_default.json` and exits. |

### Things to know about `config.json`

- The bot **locks** the file while it runs. Starting a second bot with the same file fails with `PermissionError`.
- A missing file or a wrong `-c` path stops the bot with `Incorrect configuration file path`.
- A JSON mistake stops the bot with `Syntax error in configuration file`, followed by the position of the error. The usual causes are unescaped backslashes, a missing comma and a trailing comma.
- When an update adds new settings, the bot adds them to your `config.json` by itself the next time it starts. Your own values are never changed and the file is never reset; the old file is first copied to `config.json.bak`. See [Updating](#-updating).
- `config.json` is part of the repository. If you update with `git pull` and have edited it, Git may report a conflict. See [Updating](#-updating) for a simple way to avoid this.

---

## 🏃 Running the Bot

| Action | How |
| :--- | :--- |
| **Start** | `.\TTMediaBot.bat` |
| **Check FFmpeg** | `.\TTMediaBot.bat --check` |
| **Stop** | Send `q` to the bot as a private message (admin), or close its window. |
| **Restart** | Send `rs` to the bot as a private message (admin). |
| **Use another config file** | `.\TTMediaBot.bat -c my-config.json` |

If the bot stops with an error, `TTMediaBot.bat` keeps the window open and points you to `TTMediaBot.log`.

### Warm-up after starting

Starting the bot also starts the YouTube bridge, which needs a moment before the first search. In the author's logs the bridge became ready about 18 seconds after the bot started, and the first search added about 4 more seconds. A `p` command typed during those first seconds is slow; after that the bot answers quickly. These are reference measurements from one PC, not guarantees.

### Starting the PO-token provider again

The provider window from the installer closes when you restart the PC or close the window. Start it again before the bot:

```powershell
cd bgutil-provider\server
node build\main.js --port 4416
```

Leave that window open. Running `install_windows.bat` again does the same when you answer `Y` at step 4: it skips everything that is already done and starts the provider if nothing answers on port `4416`. Answer `N` when another bot already runs it.

To check that it is running:

```powershell
curl.exe -s http://127.0.0.1:4416/ping
```

---

## 🌐 YouTube Bridge and PO-Token Provider

YouTube playback needs two small Node.js programs, both running on your own PC:

| Program | Address | Started by |
| :--- | :--- | :--- |
| **YouTube.js bridge** (`youtube_bridge\server.mjs`) | `http://127.0.0.1:4417` | The bot, automatically. Log: `youtube_bridge.log`. |
| **PO-token provider** (`bgutil-provider`) | `http://127.0.0.1:4416` | You, in its own window (installer step 5). |

The bot sends search and stream requests to the bridge, which resolves a playable audio stream that FFmpeg then plays. The PO-token provider supplies the Proof of Origin tokens that YouTube may require. The bridge answers only on `127.0.0.1`, so nothing is reachable from outside your PC.

Check the bridge:

```powershell
curl.exe -s http://127.0.0.1:4417/health
```

Use `curl.exe`, not `curl`: in Windows PowerShell `curl` is an alias for another command.

Set the environment variable `YOUTUBE_BRIDGE_AUTOSTART=0` to start and manage the bridge yourself instead of letting the bot do it.

### Timeouts for unstable connections

Requests to YouTube that hang are abandoned after a short time and repeated on a fresh connection. Only hangs are repeated; real errors are reported immediately. Each time it happens the bridge writes a `[youtube-bridge-stall]` line to `youtube_bridge.log`. You can change the limits with environment variables (values in milliseconds):

| Variable | Default | Applies to |
| :--- | :--- | :--- |
| `YOUTUBE_BRIDGE_STALL_TIMEOUT_MS` | `5000` | Searches (up to 3 attempts). |
| `YOUTUBE_BRIDGE_PLAYER_TIMEOUT_MS` | `8000` | Player requests that resolve a stream (up to 2 attempts). |
| `YOUTUBE_BRIDGE_POT_TIMEOUT_MS` | `8000` | Requests to the PO-token provider. |

---

## 🎵 YouTube Music, Autoplay and Downloads

These features work exactly as described in [README.md](README.md). A short summary for Windows:

- **Switch service:** `sv yt` for YouTube and `sv ytm` for YouTube Music.
- **Autoplay:** when the last track of the queue is playing, the bot appends related tracks so the music keeps going. Recommendations use your configured cookies.
- **Playlists and albums:** `dlp [url]` downloads a whole playlist or album, zips it and uploads it to the channel.
- **Link lists:** `aad`, `ad`, `ld`, `rd`, `ldd` and `ads` manage and download a personal list of links.
- **Local download mode:** `adsc` toggles saving files on your PC instead of uploading them. Tracks are stored in `data\Downloads\music\` and ZIP archives in `data\Downloads\zips\`, inside the bot folder. Files saved locally are never deleted automatically.

---

## 🤖 AI (Gemini)

The bot can answer questions with Google's Gemini models, through the official `google-genai` library. Answers can use **Grounding with Google Search**, so questions about the weather, the news or a match get current information instead of old knowledge.

### Turn it on

1. Create an API key at <https://aistudio.google.com/apikey>.
2. Put it in `config.json` under `ai` → `gemini` → `api_key`. (Or leave it empty and set the `GEMINI_API_KEY` environment variable.)
3. Install the packages (`install_windows.bat` does it) and restart the bot with `rs`. The `google-genai` library is part of `requirements.txt` and needs Python 3.10 or newer.

### Using it

| Command | What it does |
| :--- | :--- |
| `ai QUESTION` | Asks one question, for example `ai bagaimana cuaca di blora saat ini`. Nothing is remembered afterwards. |
| `chat` | Starts a conversation. From then on **everything you send is a message to the AI**, and the AI remembers what was said. Commands inside a chat: `/clear` forgets the conversation and starts a new topic, `/c` ends the chat. `chat QUESTION` starts a chat and asks at once. |

The answers are plain text (no Markdown symbols), are cut at `max_answer_length` characters and are sent as several messages when they are long. When the answer was found with Google Search, the names of the websites are added at the end.

### Settings (`config.json` → `ai`)

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `enabled` | `true` | Turns the `ai` and `chat` commands on or off. An administrator can also block one with `bc +ai`. |
| `provider` | `"gemini"` | The service that answers. Only Gemini exists for now. |
| `cooldown_seconds` | `2.0` | Seconds a user has to wait between two questions. |
| `max_question_length` | `2000` | Longest question in characters (`0` = no limit). |
| `max_answer_length` | `1500` | Longest answer in characters (`0` = no limit). |
| `show_sources` | `true` | Names the websites a searched answer is based on. |
| `chat_idle_minutes` | `30` | A chat ends by itself after this many minutes without a message (`0` = never). |
| `max_concurrent_requests` | `3` | Questions answered at the same time, for all users together. |
| `gemini.api_key` | `""` | Your key. Empty uses `GEMINI_API_KEY` or `GOOGLE_API_KEY`. |
| `gemini.model` | `"gemini-3.8-flash"` | The model. Google renames and retires models now and then; the current names are at <https://ai.google.dev/gemini-api/docs/models>. |
| `gemini.google_search` | `true` | Grounding with Google Search. |
| `gemini.thinking_level` | `"low"` | `"low"` (fastest), `"medium"` or `"high"`; empty uses the model's default. |
| `gemini.timeout_seconds` | `60` | Seconds to wait for Google before one request is given up. |
| `gemini.max_retries` | `2` | How often a request is repeated when Google is busy or the network fails. |
| `gemini.system_instruction` | `""` | Extra instructions for every answer. Empty uses the built-in ones. |

Things to know:

- A single question is sent without being stored. A chat is kept by Google, as part of the Interactions API, so that the bot only has to send the newest message; `/clear` and `/c` forget it on the bot's side, and Google deletes it after its own retention time.
- Google's free tier has limits, and a key with billing turned on is charged by Google. When a limit is reached the bot says so.
- Questions and answers go through Google. Do not enable the AI on a server where that is not acceptable.
- Google has terms for Grounding with Google Search, including how its "Search Suggestions" are shown. A text bot cannot show that widget, so read the terms before you use it publicly.

---

## 🎮 Commands

Send these commands to the bot via private message (PM) or in the channel (if enabled).

### User Commands
| Command | Arguments | Description |
| :--- | :--- | :--- |
| **h** | | Shows command help. |
| **p** | `[query]` | Plays tracks found for query. If no query, pauses/resumes. |
| **u** | `[url]` | Plays a stream/file from a direct URL. |
| **s** | | Stops playback. The volume fades out first (see `fo`). |
| **n** | `[number/?]` | Plays the next track, jumps to a positive or negative track index, or reports the current position with `?`. |
| **b** | | Plays the previous track. |
| **v** | `[0-100]` | Sets volume. No arg shows current volume. |
| **sb** | `[seconds]` | Seeks backward. Default step if no arg. |
| **sf** | `[seconds]` | Seeks forward. Default step if no arg. |
| **c** | `[number/?]` | Selects a positive or negative track index; without an argument or with `?`, reports the current position. |
| **m** | `[mode]` | Sets playback mode: `SingleTrack`, `RepeatTrack`, `TrackList`, `RepeatTrackList`, `Random`. |
| **sp** | `[0.25-4]` | Sets playback speed. |
| **sv** | `[service]` | Switches service (e.g., `sv yt`, `sv ytm`). |
| **f** | `[+/-][num]` | Favorites management. `f` lists. `f +` adds current. `f -` removes. `f [num]` plays. |
| **gl** | | Gets a direct link to the current track. |
| **dl** | | Downloads current track and uploads to channel. |
| **dlv** | | Downloads current track as video and uploads it to channel. |
| **dlp** | `[url]` | Downloads all tracks from a playlist/album URL, zips them, and uploads to the channel. |
| **aad** | `[link]` | Adds a single link/URL to your custom download list. |
| **ad** | `[links]` | Adds multiple space-separated links to the download list. |
| **ld** | | Lists all links currently in the download list. |
| **rd** | `[number/link]` | Removes a link from the download list by its index or URL. |
| **ldd** | `[link]` | Downloads a link directly and uploads to the TeamTalk channel. |
| **ads** | `[1/2]` | Downloads list: Option 1 (Normal sequentially) or Option 2 (ZIP compressed). |
| **adsc** | | Toggles local download mode: saves files on this PC (in `data\Downloads\`) instead of uploading. |
| **r** | `[number]` | Plays from Recents. `r` lists recents. |
| **jc** | | Makes the bot join your current channel. |
| **qa** | `[query]` | Adds a track to the queue. |
| **ql** | | Lists all tracks currently in the queue. |
| **qr** | `[number]` | Removes a specific track from the queue. |
| **qc** | | Clears the entire queue. |
| **qs** | | Skips current track and plays the next one from the queue. |
| **sr** | `[on/off]` | Toggles Search Results Mode. When active, `p QUERY` shows a numbered list instead of playing immediately. Save with `sc`. |
| **sl** | `[number]` | Selects and plays result NUMBER from the last `sr` search list. |
| **slc** | `[number]` | Sets how many results are shown in `sr` mode. The volatile count defaults to 1 after every restart; no argument shows the current count. |
| **ai** | `question` | Asks the AI (Gemini). It searches Google when the answer needs current information, such as the weather. |
| **chat** | `[question]` | Starts a conversation with the AI. Inside a chat everything you send goes to the AI; `/clear` starts a new topic and `/c` ends the chat. |
| **a** | | Shows about info. |

### Admin Commands
*Requires admin privileges defined in `config.json`.*

| Command | Arguments | Description |
| :--- | :--- | :--- |
| **cg** | `[n/m/f]` | Changes bot gender. |
| **cl** | `[code]` | Changes language (e.g., `en`, `ru`, `pt_BR`). |
| **cn** | `[name]` | Changes bot nickname. |
| **cs** | `[text]` | Changes bot status text. |
| **cc** | `[r/f]` | Clears cache (`r`=recents, `f`=favorites). |
| **cm** | | Toggles sending channel messages. |
| **ajc** | `[id] [pass]` | Force join channel by ID. |
| **bc** | `[+/-cmd]` | Blocks/Unblocks a command. |
| **l** | | Locks/Unlocks the bot (only admins can use it). |
| **ua** | `[+/-user]` | Adds/Removes admin users. |
| **ub** | `[+/-user]` | Adds/Removes banned users. |
| **eh** | | Toggles internal event handling. |
| **sc** | | Saves current configuration to file. |
| **va** | | Toggles voice transmission. |
| **rs** | | Restarts the bot. |
| **q** | | Quits the bot. |
| **gcid** | | Gets the current channel ID. |
| **fo** | `[on/off/seconds]` | Turns the fade-out of `s` on or off (no option switches it), or sets its length in seconds. |
| **install** | | Installs the latest update from GitHub (`git pull`), then restarts the bot. |

---

## 🍪 YouTube & YouTube Music Cookies

Cookies from a logged-in Google account let the bot play YouTube and YouTube Music reliably and personalise autoplay.

### How to obtain cookies

1. **Log in to your Google account** in your browser (Chrome, Edge or Firefox).
2. **Install a cookies.txt exporter:**
   - Chrome/Edge: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid)
   - Firefox: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
3. **Open `youtube.com`.**
4. **Export:** click the extension icon, choose **Export All Cookies** and save the file. If your browser does not ask where to save it, it is in your **Downloads** folder.
5. **Move the file** to a folder you will keep, for example `D:\TTMediaBot\cookies.txt`.

### Tell the bot where the file is

Set the path in `config.json`, using forward slashes or doubled backslashes (see [Windows paths in JSON](#windows-paths-in-json)):

```json
"services": {
    "yt": {
        "cookiefile_path": "D:/TTMediaBot/cookies.txt"
    }
}
```

At startup the bot copies this file to `data\bots\local\cookies.txt`, which is the copy the bridge reads. Restart the bot after changing the path.

> [!IMPORTANT]
> The bridge reads Netscape-format `cookies.txt` files and forwards only YouTube and Google cookies to YouTube. Keep the file limited to those domains, and never share it: it gives access to your Google account.

### Updating expired cookies

Cookies expire from time to time. When playback stops working:

1. Export a new `cookies.txt` with the steps above.
2. Replace the old file at the same path.
3. Restart the bot (send `rs`, or close it and run `TTMediaBot.bat` again).

---

## 🌍 Supported Languages

Change the language with the `cl` admin command, or set `general.language` in `config.json`.

- `ar` - Arabic
- `en` - English
- `es` - Spanish
- `hu` - Hungarian
- `id` - Indonesian
- `pt_BR` - Brazilian Portuguese
- `ru` - Russian
- `tr` - Turkish

**Example:** send `cl id` to switch to Indonesian.

---

## 🔧 Troubleshooting

### The installer says Python was not found

No 64-bit Python 3.10 or newer was found, and winget could not install one. Run `winget install 9NQ7512CXL7T --accept-package-agreements` and then `py install 3.15`, **open a new terminal** (Windows updates the search path only for windows opened afterwards) and run `install_windows.bat` again. If `py` still opens the wrong program, open *Manage app execution aliases* in Windows settings and refresh the *Python install manager* aliases, or use `pymanager install 3.15`.

An existing `venv` keeps the Python it was created with. To move the bot to Python 3.15, install it as above, delete the `venv` folder and run `install_windows.bat` again; your `config.json` is not touched.

### The installer says the YouTube bridge or PO-token provider was not installed

Node.js LTS or Git is missing. Install both and run the installer again:

```powershell
winget install OpenJS.NodeJS.LTS
winget install Git.Git
```

If the build itself fails, run the commands the warning prints inside the bot folder to see the full error.

### The bot stops right after starting

Read the message in the window, then `TTMediaBot.log`.

- `Incorrect configuration file path` — `config.json` is missing or the `-c` path is wrong.
- `Syntax error in configuration file` — the JSON is invalid. See [Windows paths in JSON](#windows-paths-in-json).
- `PermissionError` — another bot is already running with the same `config.json`. Close it first (look for `python.exe` in Task Manager).
- A TeamTalk library error — `TeamTalk5.dll` is missing, is not the 64-bit build, or is older than SDK 5.11.

### The bot does not appear online

1. Check `hostname`, `tcp_port` and `udp_port` in `config.json`, and that the PC can reach the server.
2. Check that the bot account exists on the TeamTalk server and that the username and password are correct.
3. If the server uses encryption, set `"encrypted": true`. If no local certificate `data\ttservercert.pem` is provided, the bot fetches and trusts the server's certificate automatically.
4. Read `TTMediaBot.log`.

### Connected, but no sound

1. Run `.\TTMediaBot.bat --check` to see which FFmpeg is used. If none is found, put `ffmpeg.exe` beside `TTMediaBot.py` or set `player.ffmpeg_path`.
2. The bot needs the right to transmit voice in its channel.
3. Send `v` to see the volume and `v 50` to set it.
4. Restart the bot with `rs`.

### YouTube or YouTube Music does not play

1. **Is the PO-token provider window open?** Check with `curl.exe -s http://127.0.0.1:4416/ping`. If `youtube_bridge.log` contains `POT provider unavailable`, the provider is not running. Start it again (see [Starting the PO-token provider again](#starting-the-po-token-provider-again)).
2. **Is the bridge answering?** `curl.exe -s http://127.0.0.1:4417/health`
3. **Are the cookies still valid?** Export new ones (see [cookies](#-youtube--youtube-music-cookies)). The log line `Cookie file NOT FOUND` means the path in `cookiefile_path` is wrong.
4. **Read `youtube_bridge.log`.** Lines such as `No valid URL to decipher` mean YouTube did not return a playable stream for that video through one client. The bridge then tries its other clients, and trying again usually works.
5. **Update the components** if the problem started suddenly (see [Updating](#-updating)).

### The `p` command is slow

- **Right after starting the bot:** wait about 25 seconds (see [Warm-up after starting](#warm-up-after-starting)).
- **PO-token provider closed:** see the section above.
- **Unstable network:** look for `[youtube-bridge-stall]` in `youtube_bridge.log`. Each such line is a request that hung and was repeated.
- **Still slow:** compare the timestamps in both logs (see [Logs and Monitoring](#-logs-and-monitoring)) to find out whether the time is spent in the bot, in the bridge or on the network.

### The bot keeps disconnecting from the server

Check your network and the server status, read `TTMediaBot.log`, and consider raising `teamtalk.reconnection_timeout`. The bot keeps retrying by default (`reconnection_attempts` is `-1`). A line such as `Server lost` in the log is the bot noticing a dropped connection.

---

## ❓ FAQ (Frequently Asked Questions)

### Q: Can I run multiple bots on the same PC?
**A:** This guide covers one bot per installation. For hosting several bots, the Docker workflow in [README.md](README.md) shares one YouTube backend between all bots.

### Q: How do I add more administrators?
**A:** Two ways:
- **Via command:** send `ua +username` to the bot (requires existing admin privileges).
- **Via config:** add the username to the `teamtalk.users.admins` list in `config.json`, then restart.

### Q: How do I back up my bot?
**A:** Copy `config.json`, your `cookies.txt`, `TTMediaBotCache.dat` (recents and favorites) and the `data\` folder.

### Q: How do I change the bot's nickname?
**A:** Send `cn NewNickname` (admin only), or edit `teamtalk.nickname` in `config.json` and restart.

### Q: Do I have to keep the PO-token provider window open?
**A:** Yes, while the bot is running. Without it YouTube can answer `403 Forbidden` for some videos.

### Q: Can the bot start automatically with Windows?
**A:** This guide does not set that up. You would need to start the PO-token provider and `TTMediaBot.bat` yourself, for example with Windows Task Scheduler.

### Q: What happens to my settings when I update?
**A:** They are kept. When an update brings new settings, the bot adds only those to your configuration file the next time it starts (the old file is saved as `config.json.bak`), the way an app or Windows keeps your settings through an update. If you follow the steps in [Updating](#-updating), `git pull` does not touch your own file either.

---

## 📊 Logs and Monitoring

### Log files

| File | Written by | Content |
| :--- | :--- | :--- |
| `TTMediaBot.log` | The bot | Commands, TeamTalk events, playback and errors. |
| `youtube_bridge.log` | The YouTube bridge | Searches, stream resolution timings, PO-token status and warnings. |

Both are in the bot folder, and every line starts with a local timestamp in the same format, so the two logs can be read side by side.

### Viewing a log live

```powershell
Get-Content TTMediaBot.log -Wait -Tail 50
Get-Content youtube_bridge.log -Wait -Tail 50
```

### Log configuration

Edit the log settings in `config.json`:

```json
"logger": {
    "log": true,
    "level": "INFO",
    "mode": "FILE",
    "file_name": "TTMediaBot.log",
    "max_file_size": 0,
    "backup_count": 0
}
```

**Log levels:** `DEBUG` (detailed, for diagnosing problems), `INFO` (default), `WARNING`, `ERROR`. To debug, change `"level": "INFO"` to `"level": "DEBUG"` and restart the bot.

### Playback latency diagnostics

Search the bot log for `[PlaybackTiming]` to follow one request through command handling, search, stream resolution, FFmpeg loading and playback start:

```powershell
Select-String -Path TTMediaBot.log -Pattern '\[PlaybackTiming\]'
```

### Bridge log lines

| Line starts with | Meaning |
| :--- | :--- |
| `[youtube-bridge-timing]` | Time spent in one stage of resolving a video: `po-token`, `player`, `choose-format` or `decipher`. |
| `[youtube-bridge-http]` | A request reached the bridge (`->`) or was finished (`<-`) with its status and `handled_ms`. |
| `[youtube-bridge-stall]` | A request to YouTube hung and was abandoned. Shows the attempt number and whether it will retry. |
| `[youtube-bridge-lag]` | The whole bridge process was frozen for more than one second. |
| `POT provider unavailable` | The PO-token provider on port `4416` did not answer. |

### Finding where a slow command lost its time

1. Note the time of the command in `TTMediaBot.log`.
2. Find the same time in `youtube_bridge.log`.
3. Compare the `->` and `<-` lines: if the bridge handled the request quickly but the bot waited much longer, the delay was outside the bridge. If `handled_ms` is large, look at the `[youtube-bridge-timing]` and `[youtube-bridge-stall]` lines just before it.

### Checking resource use

Open Task Manager and look at `python.exe` (the bot) and `node.exe` (the bridge and the PO-token provider), or run:

```powershell
Get-Process python, node
```

---

## 🔄 Updating

### The bot

Because `config.json` is part of the repository, keep your own settings in a separate file so that updates never conflict with it:

1. Copy `config.json` to `my-config.json` and edit that copy.
2. Always start the bot with `.\TTMediaBot.bat -c my-config.json`.

Then update with:

```powershell
git pull
.\install_windows.bat
```

If you downloaded a ZIP instead, download the new ZIP, extract it over the folder and keep your `my-config.json`, `cookies.txt` and `data\` folder.

### Update notices from GitHub

When the bot folder is a Git clone (you installed with `git clone`), the bot looks on GitHub by itself every `updater.check_interval_minutes` minutes. When your repository has a new commit it posts a notice in the channel, for example:

```text
Update available
A new version of TTMediaBot is ready to install.
Installed version: 4.1.2 (85402d3)
Available version: 4.2.0 (9f3c2ab)
Latest change: Fix the reconnect loop (Nico Hilmi, 2026-10-11 14:05)
To install it, an administrator can send: install
The bot will restart automatically to finish the update.
```

An administrator sends `install`. The bot runs `git pull --ff-only`, tells the channel that it is restarting and starts again by itself. Each new commit is announced once.

- Git must be installed and in the `PATH`. A bot that was installed from a ZIP file is not a Git clone and cannot update itself this way; the log says so once.
- `git pull --ff-only` refuses to overwrite files you edited by hand when the update changes the same files, and it refuses when the folder has commits that are not on GitHub. The bot then answers with the reason and changes nothing. Keep your own settings in `my-config.json`, as described above.
- If an update changes `requirements.txt`, the bot restarts and installs the packages while it starts, before it loads them, in the way an operating system finishes an update during a restart. This can take a few minutes. If it fails (no internet, for example) the bot still starts and tells the channel; then run `venv\Scripts\python.exe -m pip install -U -r requirements.txt` and send `rs`.
- After the restart the bot says which version it updated from and to, and how many new settings it added to your configuration.
- Set `updater.enabled` to `false` to stop the background checks. `install` still works when you send it.

### Your settings in `config.json`

An update that needs new settings only **adds** them. At the next start the bot compares your `config.json` with the settings the new version knows, adds what is missing with its default value and leaves everything you set as it is: values, lists and extra keys. Nothing is reset. Before the file is changed it is copied to `config.json.bak`, the number of added settings is reported in the channel after the restart, and the log has a line starting with `[Config]`.

If a later version has to rename or change a setting, it does so with a small step of its own (see `bot/migrators/config_migrator.py`) and raises `config_version`. A `config.json` whose `config_version` is higher than the bot knows (for instance after you went back to an older version) stops the bot with a clear message instead of being damaged; restore `config.json.bak` or update the bot.

### Python packages

```powershell
venv\Scripts\python.exe -m pip install -U -r requirements.txt
```

`requirements.txt` does not pin versions, so this installs the newest releases. If the bot stops working afterwards, delete the `venv` folder and run `install_windows.bat` again.

### The YouTube.js library

The bridge uses the [YouTube.js](https://github.com/LuanRT/YouTube.js) library. Check the installed version and update it:

```powershell
cd youtube_bridge
npm ls youtubei.js
npm update youtubei.js
npm ls youtubei.js
cd ..
```

If the version number does not change, there is no newer release. The bridge was written for YouTube.js 18.x, so read the library's release notes before moving to a new major version. Restart the bot afterwards.

### The PO-token provider

The installer does not update a provider that is already installed. Close its window, then:

```powershell
cd bgutil-provider
git pull
cd server
npm ci
npx tsc
cd ..\..
```

Start it again (see [Starting the PO-token provider again](#starting-the-po-token-provider-again)). This only works when the folder was created by the installer's `git clone`.

---

### Running the tests

**Run this before every `git commit`.** From the bot folder:

```powershell
run_tests.bat
```

It runs every test in the `tests` folder (about 370) and the Node.js tests of the YouTube bridge (`youtube_bridge\test`, when Node.js is installed) and ends with one line: `ALL TESTS PASSED - it is safe to commit.` or `TESTS FAILED - do not commit yet.` (the exit code is 0 only when everything passed). `run_tests.bat -v` prints one line per test, `run_tests.bat -k fade` runs only the tests whose name contains `fade`, `run_tests.bat -f` stops at the first failure. If packages are missing it says which and how to install them.

The tests do not need the internet, a TeamTalk server or `TeamTalk5.dll`: they load the bot with a stand-in for the native library (`tests\__init__.py`; set `TTBOT_TEST_REAL_SDK=1` to load the real DLL instead). Lines that start with `WARNING:` or `ERROR:` while the tests run are log messages of tests that exercise failure paths on purpose; only the result at the end counts. Tests that cannot run on Windows are listed at the end as skipped with their reason (the bash scripts of the Linux deployment, and the real `curl`/PowerShell download tests only where those programs exist). The same as plain `unittest`:

```powershell
venv\Scripts\python.exe -m unittest discover -s tests -t . -v
venv\Scripts\python.exe -m unittest tests.test_ai_manager -v
```

The first line runs everything, the second a single file. Some tests need Git (the update tests) and FFmpeg (the audio tests), and skip themselves when it is missing.

---

## 🧹 Uninstalling

1. Stop the bot and close the PO-token provider window.
2. Delete the bot folder. The Python environment (`venv`), the bridge's `node_modules`, `bgutil-provider` and all logs are inside it.
3. If you no longer need them, remove Node.js, Git, FFmpeg and Python from *Settings → Apps*.

Back up `config.json`, `cookies.txt` and `TTMediaBotCache.dat` first if you want to keep them.

---

## 📜 Legal Disclaimer & Terms of Use

This software and the Windows scripts (`install_windows.bat`, `TTMediaBot.bat`) are provided "AS IS", without warranty of any kind. The Legal Disclaimer & Terms of Use in [README.md](README.md) applies to this guide and to this port in the same way. Using the bot is at your own risk, and you are responsible for following the terms of the services it plays from.
