# 📋 Changelog — TTMediaBot

All notable updates to this fork are documented here, in reverse chronological order.

---

## 🔧 Version 4.1.2 — Bug hunt, TeamTalk SDK 5.23a installer and Python 3.15 *(10/16/2026)*

The version number stays 4.1.2: no command or option was added or removed.

### 🐛 Fixed: a different song was played after a failed stream (the "typed one song, got another" report)
- **🔎 Symptom:** the chat said `Playing Bersenja Gurau`, but another song was heard. On 13 Oct at 10:00 the stream of the requested track answered `HTTP error 403 Forbidden` twice within 0.5 s; the player then treated the error as the end of the track and started the next recommendation (`Dunia Yang Nanti`) without a word. The same double 403 appears for `iqro` (14:41) and `Reain lode iqro` (21:27).
- **🚀 Fix (`bot/player/__init__.py`):** a failed YouTube / YouTube Music stream is retried up to three times: at once (this repairs an expired URL), then after 3 s and after 5 s (`STREAM_RETRY_DELAYS`). Delayed retries run on a timer and are dropped when the user started or stopped something else meanwhile (`_play_token`). When every retry failed, the chat gets a message (`Could not play "…": the audio stream could not be loaded …`). A song the user asked for stops instead of being replaced; a following list or autoplay track is skipped, with the same message.
- **ℹ️ About the cause of the 403:** all eight 403 warnings in the log are `c=MWEB`, `itag=251` URLs with `pot=` present. The yt-dlp issues #16768 and #17395 (2026) report the same intermittent 403 for `mweb` and describe YouTube holding the media URL back for a few seconds (a pre-roll ad wait) which yt-dlp sleeps through. That fits the log (403 within 0.15 s of the request, the same track works a minute later) but it could not be reproduced here, so the timing is a hypothesis; the fix does not depend on it.

### 🐛 Fixed: autoplay recommendations were added to the queue two or three times
- The search and the "few tracks left" check start an autoplay fetch at the same moment; each merged the same 15 recommendations. The log shows `Adding 15 continuous recommendations (total: 16)` twice and then `(total: 46)`. `_fetch_autoplay_sync` (`yt.py`, `ytm.py`) now skips a fetch that is already running for the same video and merges one fetch at a time. A test proves the duplicates appear without the lock.

### 🐛 Fixed: a search for one song could play a FULL ALBUM
- `p vata morgana,simpatik musik` played `… SIMPATIK MUSIK FULL ALBUM TERBARU 2026`. With one result wanted, a top result that is a multi-song upload (full album, non stop, playlist, N hours / jam, compilation, megamix) now makes the bot look at the next eight results and take the first real song (`bot/services/result_filter.py`). A query that itself asks for an album is left alone. This only costs a second search when the top result looks like a collection.
- `YtService.search` no longer turns every failure (bridge down, timeout) into "nothing found"; it raises a service error that says what failed. "Nothing found" is reported only when nothing was found.

### 🔍 Added: stutter and stalls are now visible in `TTMediaBot.log` ("it stutters but nothing is logged")
- `bot/player/ffmpeg_engine.py`: `Audio underrun #N: no decoded audio for X s at Y s into the track`, `Audio is reaching the sink late: N late frames (worst M ms)`, `Stream notice:` for ffmpeg's own reconnect / reset / timeout messages (they used to be kept in memory only), a per-track `Stall summary`, and a count of frames dropped by the TeamTalk sink in the existing warning.
- After an underrun the pump refills its prebuffer (at most 2 s) before playing on. Before, it resumed with a single frame in hand, so a connection that delivers barely enough data stalled again on every frame.

### 🧰 Added: `tools/setup_deps.py`, used by `install_windows.bat` and `install.sh`
- **FFmpeg:** checked in the bot folder and on `PATH`; when missing it is installed with winget (`Gyan.FFmpeg`), Chocolatey or Scoop on Windows, Homebrew on macOS, and apt, dnf (with an `ffmpeg-free` fallback for Fedora), yum, pacman, zypper, apk, xbps or Portage on Linux. When nothing works the manual steps are printed.
- **TeamTalk SDK:** the newest stable release is read from the official page <https://bearware.dk/?page_id=419> (v5.23a, 8 April 2026, at the time of writing), with the alternative page addresses, the release directory and the known file names as fallbacks. The archive is downloaded with retries, checked to be a real 7z file, unpacked (py7zr, 7-Zip or bsdtar; 7-Zip is installed when none is present), the library is loaded in a separate process and asked for its version, and only then copied into place. The previous library is kept as `.bak`; a library that does not load is never installed; on an old Linux the build for an older Ubuntu is tried. If anything fails the user is told what to do by hand. BearWare offers the SDK download as a 30 day trial.
- `install.sh` no longer lists `ffmpeg` and `p7zip` in the distribution package line (one missing package, for example `ffmpeg` on Fedora without RPM Fusion, aborted the whole install), and no longer downgrades `httpx` to 0.27.0: `google-genai` requires `httpx>=0.28.1`.
- `bot/ffmpeg_locator.py` also finds the `ffmpeg.exe` that winget, Chocolatey or Scoop installed, so a Command Prompt opened before the install does not report FFmpeg as missing.

### 🐍 Python 3.15 (released 9 October 2026)
- The main change for this code base is PEP 686, UTF-8 as the default text encoding. Every text-mode `open()` now names its encoding (`bot/config/__init__.py`, `bot/TeamTalk/__init__.py`), the installer tool decodes subprocess output with `errors="replace"`, and the console log no longer fails on a character the Windows code page cannot show (`bot/logger.py`). Running the test suite with `-X warn_default_encoding -W default` shows no warning from the bot's own code.
- The compiled dependencies publish Python 3.15 wheels (`pydantic-core` 2.48 / 2.49 on PyPI; `numpy` 2.5 according to a downstream release note). The pure Python ones were not checked one by one. The tests in this change were run on Python 3.12; please run them once on 3.15.

### 📚 Docs
- New `README_DEVELOPERS_AI.md`: how to develop and debug the bot with an AI assistant (give the chronology and evidence, one bug per session, prompt templates, a code map).
- Corrected contradicting requirements: `README_WINDOWS.md` said both "Python 3.14.7" and "Python 3.1.4.7" while the installer wants 3.10; the SDK minimum was given as 5.2.3.0, 5.23, 5.11 and 5.8.1 in different places. The minimum is 5.11 (the virtual sound device functions are in the 5.11A API documentation), the target is 5.23a.

### ✅ Tests
- 280 tests pass (189 before). New: `test_playback_failure_handling.py`, `test_autoplay_race.py`, `test_result_filter.py`, `test_ffmpeg_stall_logging.py`, `test_setup_deps.py`, `test_ffmpeg_locator_windows.py`.

### ⚠️ Known limits and things found but not changed
- **Docker:** the image is based on Debian 11 (`python:3.10.12-slim-bullseye`) and `install_git_clone.sh` / `update.sh` still download a third-party TeamTalk build of unknown version. The Linux SDK 5.23a is built for Ubuntu 26 and may not load on that glibc, so Docker was not switched; use `tools/setup_deps.py sdk` on a native install, and rebuild the image on a newer base before using 5.23a there.
- **Earlier changelog entry:** "Windows Port — YouTube 403 Forbidden Protection" (10/08/2026) describes `MAX_CONSECUTIVE_STREAM_FAILURES`, the provider autostart in `bridge_launcher.py` and `test_youtube_403_protection.py`. None of them is in this repository (the installer starts the provider in a second window instead). The v2.8.0 entry says the search cache lasts 10 minutes; `youtube_bridge/server.mjs` sets `SEARCH_CACHE_TTL_MS` to 24 hours.
- Not found to be wrong, so not changed: `uSampleIndex = 0` in `TT_InsertAudioBlock` (the SDK documentation says it is ignored); the default model `gemini-3.8-flash` and `google-genai>=2.16.0` (both exist).

---

## 🔧 Unreleased — FFmpeg Audio Engine & Windows Support

- Replaced `mpv`/`libmpv` and PulseAudio with an FFmpeg based player: FFmpeg decodes to PCM and the bot sends it to TeamTalk through the virtual sound device (`TT_InsertAudioBlock`). No sound card, sound server or virtual cable is required.
- The bot now runs on Windows as well as Linux. FFmpeg is taken from `player.ffmpeg_path`, then from the bot folder (beside `TTMediaBot.py`), then from the system `PATH`.
- TeamTalk SDK library loading searches the bot folder and `TeamTalk_DLL/` (absolute path) on both platforms instead of relying on the working directory / `LD_LIBRARY_PATH`.
- The YouTube.js bridge is started automatically (Node.js) outside Docker; fixed its Windows path handling (`fileURLToPath`).
- Added `install_windows.bat` and `TTMediaBot.bat`; removed `mpv.py`, the PulseAudio systemd units and the PulseAudio setup in `entrypoint.sh`; removed `libmpv`/`pulseaudio` from `install.sh` and the Dockerfile.
- Download folders no longer use hard-coded `/home/ttbot/...` paths; file names are sanitised for Windows; restarting works on Windows.
- New `player` options: `ffmpeg_path`, `buffer_seconds`, `network_timeout`, `volume_curve`. After a stream error a refreshed YouTube stream now resumes at the position reached.
- Added tests for the FFmpeg engine; updated the player tests for the new API.

## 🔧 Unreleased — Generic Stream Resolver

- Added an extensible page-to-media resolver registry for the `u` command.
- Added GETEM player-page support by extracting embedded audio URLs and forwarding required HTTP headers to mpv.
- Stopped sending unrelated non-YouTube URLs through the YouTube.js fallback service.
- Reset per-track HTTP headers when playback moves back to a plain direct URL.
- Added regression tests for GETEM HTML/JavaScript extraction, direct URL fallback, and mpv header cleanup.

## 🆕 v2.8.0 — "Unified Music Discovery & Expiry-Aware Playback" *(08/31/2026)*

### 🎵 Unified YouTube.js Discovery
- **🧹 Removed `ytmusicapi`:**
  Migrated YouTube Music song search and authenticated Up Next radio to the shared YouTube.js bridge, removing the per-bot Python client, cookie-authentication duplication, HTTP/2 pool, and runtime dependency.
- **🔎 Native Music Catalog Search:**
  Added a bridge Music-search mode that preserves song, artist, duration, video ID, and playable URL metadata expected by the existing `ytm` service.
- **📻 Authenticated Shared Recommendations:**
  Added cookie-isolated Music Up Next retrieval with bounded caching and pending-request deduplication for both YTM autoplay and the YT recommendation fallback.

### ⚡ Bounded Search and Stream Caching
- **🔁 Shared Search Cache:**
  Added normalized, public catalog caches for WEB and YTMUSIC searches with a 10-minute TTL, 512-entry LRU bound, and in-flight deduplication.
- **⏳ Expiry-Aware Stream Reuse:**
  Replaced the fixed five-minute stream cache with a lifetime derived from each signed URL's `expire` value, a two-minute safety margin, and a one-hour maximum.
- **🐍 Local Stream Reuse:**
  Added a per-bot Python cache that uses the bridge-provided safe deadline to avoid repeated local HTTP requests for the same valid stream.
- **🧯 One-Shot Recovery:**
  When `mpv` rejects a YouTube stream, the player now invalidates Python and bridge caches, resolves a fresh URL, and retries once without duplicating recent history.

### 📊 Resolution Diagnostics and Tests
- **🔬 Stage-Level Timings:**
  Added safe timing logs for PO-token generation, Player API requests, format selection, signature deciphering, cache lifetime, and total client resolution without logging token or cookie values.
- **✅ Regression Coverage:**
  Added Node tests for TTL/LRU behavior, pending-request deduplication, media mapping, and URL-expiry calculations, plus Python tests for bridge contracts, YTM migration, stream refresh, and one-shot player recovery.

### 🧪 Clean-Rebuild Verification
- **🩹 Legacy Update Recovery:**
  Fixed upgrades from pre-shared-service releases that could rebuild and restart bot containers without starting `ttmediabot-youtube`. The updater now reloads deployment logic after replacing itself, reconciles a missing or unhealthy shared service even when no rebuild is pending, and lets the auto-updater trigger recovery when port 4417 is unavailable.
- **📦 Runtime Dependency Removal:**
  Confirmed after an option **3** rebuild that `ytmusicapi` is absent from the generated image and that the shared YouTube service and bot container start healthy.
- **✅ Automated Validation:**
  Executed all 18 migration tests successfully: nine Node.js tests for bridge primitives and nine Python tests for service and playback contracts.
- **⚡ Integration Measurements:**
  Verified YouTube video search, YouTube Music song search, authenticated Up Next, stream invalidation, fresh resolution, and cache reuse. On the validation host, repeated searches fell from approximately 0.47–0.54 seconds to 3–4 milliseconds, and a forced fresh resolution fell from approximately 0.37 seconds to about 3 milliseconds on cache reuse.
- **🎧 Long-Media Compatibility:**
  Resolved a 36,107-second video through the YTMUSIC client while retaining the established long-media `mpv` configuration and the bounded one-shot stale-stream recovery path.

---

## 🆕 v2.7.0 — "Shared YouTube Service, Playback Diagnostics & Queue Reliability" *(08/31/2026)*

### 🏗️ Shared Multi-Bot YouTube Architecture
- **🌐 One Backend for Every Bot:**
  Replaced the per-bot Node.js bridge and PO-token provider with one managed `ttmediabot-youtube` container. Bot containers are now Python-only and connect through their host network to the bridge published exclusively on `127.0.0.1:4417`.
- **🍪 Per-Bot Authentication Isolation:**
  Added validated `bot_id` routing so each request uses only its corresponding `bots/<name>/cookies.txt`. Cookie-backed YouTube.js sessions are isolated and retained in a bounded 64-entry least-recently-used cache.
- **⚡ Shared Resolution and Request Caches:**
  Added bounded stream-resolution caching, in-flight request deduplication, and session reuse to avoid repeating expensive extraction work across searches and track transitions.
- **🔁 Resilient Bridge Connections:**
  Added five bounded connection attempts with exponential backoff when the shared service is starting or restarting.
- **🔒 Reduced Service Exposure:**
  Bound the bridge to `127.0.0.1:4417` on the host and kept the PO-token provider on port `4416` internal to the shared container.
- **🧩 Shared Service Supervisor:**
  Added `youtube_services.sh` to supervise both Node.js processes and propagate shutdown cleanly.

### 🐳 Docker Lifecycle and Management
- **🎛️ Dedicated Server Controls:**
  Added main-menu option **8** and `youtube_server_manager.sh` with Start, Stop, Restart, and Return actions. Start and restart wait for a successful bridge health check.
- **🔄 Rebuild and Migration Support:**
  Updated `ttbotdocker.sh` to create, health-check, and reuse the shared service, remove obsolete per-bot service processes, and migrate installations built from the legacy image layout.
- **⬆️ Updater Integration:**
  Updated `update.sh` to deploy and validate the shared service before recreating bot containers while preserving their previous running state.
- **🗑️ Uninstaller Integration:**
  Updated safe and full uninstall paths to remove the shared YouTube container and network resources in scope.
- **🧹 Bot Cache Cleanup:**
  Added Manage Bots option **12** to delete `*.cache` and `*.dat` files strictly below managed directories in `bots/`, with confirmation and per-bot reporting. Return moved to option **13**.

### ⏱️ Playback Performance and Observability
- **📊 End-to-End Timing Logs:**
  Added correlated measurements for typed search commands, result selection, next-track transitions, URL resolution, `mpv` handoff, and actual playback start across all media services.
- **🔎 Startup and Service Timings:**
  Added timing logs for service initialization and background warm-up so first-request behavior can be compared with long-running behavior.
- **🔥 Background Pre-Warming:**
  Moved YouTube session/search warm-up out of the blocking startup path and retained a fast health endpoint so bot startup is not delayed by external requests.
- **💾 Stream Resolution Cache:**
  Cached reusable resolved streams and removed repeated URL-resolution work from the hot playback path.
- **🚦 Bounded Prefetch:**
  Limited background prefetch work and pending requests to prevent queue growth and progressive playback slowdown during long sessions.
- **📝 Reduced Hot-Path Log Noise:**
  Removed repeated stream-URL logging while preserving structured latency and failure diagnostics.
- **🎧 MPV Buffer Tuning:**
  Increased playback buffer and read-ahead settings, and standardized PulseAudio/MPV output to 48 kHz stereo for more stable playback handoff.

### 🛡️ YouTube Playback and PO-Token Fixes
- **🔑 Video-Bound PO Tokens:**
  Corrected GVS PO-token generation so tokens are bound to the target video ID, resolving authenticated stream failures and intermittent HTTP 403 responses.
- **🧍 Isolated Shared Token Provider:**
  Separated token-provider state from bot sessions while retaining per-bot cookie selection in the shared bridge.
- **🧯 Playback State Hardening:**
  Fixed missing bot assignment and protected recent-track access from `IndexError` during asynchronous playback transitions.

### 📻 Queue, Playlist, and Autoplay Improvements
- **♾️ Continuous Recommendations:**
  Added continuous autoplay replenishment with multiple recommendation candidates, greater radio variety, and automatic skipping of unavailable suggestions.
- **📚 Complete Playlist Pagination:**
  Added YouTube playlist continuation support, including desktop `WEB` continuations, progress reporting, and final loaded-track totals.
- **🔀 Full-Playlist Random Mode:**
  Random playback now covers the complete playlist, starts with a randomized first track, reshuffles endlessly, and keeps the internal index list synchronized.
- **🔗 Channel URL Recognition:**
  YouTube and YouTube Music channel URLs are now treated as playlist-style collections where supported.
- **⏹️ Playlist Boundary Rules:**
  Continuous autoplay is disabled for explicit playlists and end-of-list behavior now respects the selected playback mode.

### 🎮 Playback Commands and Localization
- **🔢 Direct Next Selection:**
  Extended `n` with an optional track number for direct queue navigation.
- **📍 Position Queries:**
  Added `n ?` and `c ?` queries to report the current queue/search position without changing playback.
- **🌍 Complete Translation Coverage:**
  Added the new command and playback messages to all seven maintained locale catalogs and recompiled GNU MO files with UTF-8 metadata.

### 🧰 Maintenance
- **🗑️ Legacy Workflow Removal:**
  Removed the obsolete nightly update workflow after the backend migration.
- **🙈 Diagnostic Artifact Ignore Rule:**
  Added the local `fast_forensics.py` utility to `.gitignore` so server diagnostics cannot be committed accidentally.

---

## 🆕 v2.6.0 — "YouTube.js Bridge Architecture & Native Stream Resolution" *(08/29/2026)*

### 🚀 YouTube.js Bridge Architecture (Goodbye `yt-dlp` & `py-yt-search`)
- **⚡ Persistent Node.js Bridge (`youtube_bridge`):**
  Replaced `yt-dlp` stream extraction with a dedicated, persistent HTTP bridge powered by `YouTube.js` (`youtubei.js`). This eliminates external subprocess overhead, decreases latency, and enables native YouTube stream extraction directly compatible with `mpv`.
- **🔍 Native YouTube Search:**
  Migrated YouTube searches from `py-yt-search` directly to the `YouTube.js` bridge. Removed `py-yt-search` and `yt-dlp` from Python dependencies (`requirements.txt`).
- **🛡️ MPV Compatibility & Client Isolation:**
  Configured client separation (`YTMUSIC` and `WEB`) within the bridge for optimal stream extraction while keeping `ytmusicapi` responsible for rich catalog discovery and personalized autoplay.

### ⏱️ Session Pre-Warming & Startup Acceleration
- **🔥 Handshake Warmup:**
  Implemented automatic session pre-warming during bot startup (`_pre_warm()`). Initializes the Innertube session and warms stream resolution to reduce initial search and playback latency.
- **🔒 Dedicated Web Session Isolation:**
  Separated the persistent search session from authenticated playback sessions to avoid cross-contamination between search and stream-resolution state.

### 🛡️ Stream, Cookie, and Deployment Reliability
- **🎧 MPV-Compatible Stream Selection:**
  Corrected YouTube and YouTube Music client selection and audio-format resolution so the bridge returns deciphered URLs that `mpv` can consume directly.
- **🔑 Authenticated PO-Token Sessions:**
  Bound PO-token generation to the authenticated Innertube session used for stream extraction, improving protected-video reliability.
- **🍪 Robust Netscape Cookie Parsing:**
  Added support for spaced cookie configuration, selected the latest duplicate cookie value, and isolated cookie-backed bridge sessions per bot instance.
- **📥 Exact Download Selection:**
  Restricted download commands to the YouTube item explicitly requested by the user instead of accidentally expanding unrelated entries.
- **⏭️ Rapid-Skip Protection:**
  Prevented repeated tracks when users skip quickly while asynchronous resolution is still completing.
- **🔐 Preserved Bot Ownership:**
  Corrected rebuild and update flows so rewritten bot configurations retain the expected container user ownership.

### 🔥 Warm-Up and Build Refinements
- **♻️ Single Warm-Up Lifecycle:**
  Avoided repeated session warm-ups and coordinated search and stream-resolution readiness with bot startup.
- **📦 Reproducible Bridge Dependency Layer:**
  Cached the selected upstream YouTube.js source and its package metadata in dedicated Docker build layers for faster, more consistent rebuilds.

### 🌐 Multi-Instance Dynamic Port Isolation
- **🔀 Seed-Based Port Allocation:**
  Added automatic dynamic port offset calculations in `entrypoint.sh` based on container hostname or `TTBOT_INSTANCE` (`PORT_BASE`, `POT_PROVIDER_PORT`, `YOUTUBE_BRIDGE_PORT`).
  Eliminates port binding collisions when running multiple bot instances on host networking mode.
- **🍪 Isolated Cookie Sessions:**
  Improved cookie parser to isolate Netscape `cookies.txt` sessions per instance and prefer latest duplicate cookie entries with support for spaced cookie configuration.

### 📦 System Dependencies & Build Modernization
- **🎥 FFmpeg Core Requirement:**
  Added `ffmpeg` as a standard system dependency across all Linux package managers in `install.sh` and `Dockerfile`.
- **📦 Layered Dependency Caching:**
  Modernized Docker build caching by isolating `youtube_bridge/package.json` and running `npm install --omit=dev` in a dedicated cache layer.

---

## 🆕 v2.5.2 — "Dedicated Uninstaller & Legal Protection" *(08/17/2026)*

### 🛡️ Dedicated Uninstaller Submenu (`uninstall.sh`)
- **📜 Standalone Uninstaller:**
  Extracted and refactored the uninstallation logic from `ttbotdocker.sh` into a standalone, fully English-localized script [`uninstall.sh`](file:///root/joao/TTMediaBot/uninstall.sh).
- **🟢 Option 1 — Standard Uninstall (Safe & Recommended):**
  Removes **ONLY** TTMediaBot containers (labeled `role=ttmediabot`), the `ttmediabot` Docker image, bot data folders (`bots/`), the auto-updater systemd service, and temporary lock files. Preserves Docker Engine, system packages (`git`, `curl`, `jq`), and any other Docker projects on the server.
- **🔴 Option 2 — Complete System Purge (DESTRUCTIVE):**
  Purges TTMediaBot along with Docker Engine, Docker volumes, networks, system firewall (`iptables`) rules, system packages (`git`, `curl`, `jq`, `gnupg`), and Docker system directories (`/var/lib/docker`).

### ⚖️ Legal Disclaimers & Explicit Confirmation
- **⚠️ Liability Disclaimer:**
  Added prominent legal disclaimers to Option 2 in `uninstall.sh` and `README.md`, stating that the developer/author assumes no responsibility or liability for data loss, server downtime, or system instability caused by executing full purges (especially on production or shared servers).
- **🔒 Explicit Confirmations:**
  Requires explicit confirmation prompts (`y/N` for Option 1, and typing `yes` to accept the disclaimer for Option 2). Option `0` cleanly exits the uninstaller without forcing a return loop to `ttbotdocker.sh`.

### 🎨 Clean Output & Documentation
- **🧹 UI Clean-up:**
  Cleaned up repetitive ASCII border lines (`====`) across `uninstall.sh`, `ttbotdocker.sh`, and `install_git_clone.sh` for a cleaner terminal output.
- **📖 README & Terms of Use:**
  Updated `README.md` with the new uninstaller options, explicit production warnings, and a dedicated **Legal Disclaimer & Terms of Use** section.

---

## 🆕 v2.5.1 — "Proof of Origin & Playback Rate Limit Bypass" *(07/11/2026)*

### 🔒 Automated PO Token Integration (Anti-Bot Bypass)
- **🤖 Built-in DroidGuard/PO Token Provider:**
  Integrated the `bgutil-ytdlp-pot-provider` Node.js server directly inside the bot's Docker container. The server starts automatically in the background on port `4416` via `entrypoint.sh`.
- **🔌 Global Plugin Integration:**
  Embedded the `bgutil-pot` python plugin directly into Python's global `site-packages/yt_dlp_plugins/` directory during Docker image build. This ensures that any `yt-dlp` execution (either Python imports or command-line runs) automatically intercepts YouTube requests to sign them with valid PO Tokens.

### ⏱️ Playback Rate Limit / 403 Forbidden Fix
- **⏳ Complying with YouTube Signature Delay:**
  Resolved a critical `HTTP 403 Forbidden` error caused by requesting signed `googlevideo.com` media streams too quickly after URL signature generation. Added a `1.5` seconds sleep delay in `_play` method inside `bot/player/__init__.py` (matching `yt-dlp`'s internal downloader delay).
- **🌐 Dynamic Header Injection:**
  Configured `mpv` player instance to dynamically inherit the exact `User-Agent` and HTTP header fields extracted by `yt-dlp` for each track to avoid query-header mismatches on YouTube CDN servers.

---

## 🆕 v2.5.0 — "Personalized Autoplay & Deadlock Fix" *(06/16/2026)*

### 📻 Personalized Autoplay & Recommendations (Cookies Integration)
- **🆕 YouTube (`yt`) Autoplay Implementation:**
  Fully implemented the Autoplay/Watch Playlist feature for the standard YouTube (`yt`) service from scratch (matching YTM behavior). This scrapes recommendations directly from YouTube watch pages and appends them to the queue when playing the last track or single videos.
- **🍪 Authenticated Scraper for YouTube (`yt`):**
  Added support for Netscape cookies (`cookies.txt`) inside the new `_get_recommendations` scraper by loading the cookie file using `http.cookiejar.MozillaCookieJar` and passing it to `requests.get()`. This enables personalized recommendation fetching for the standard YouTube service.
- **🍪 Authenticated YTM Autoplay:**
  Upgraded the YouTube Music (`ytm`) service to fetch autoplay playlists using the authenticated client `self.ytmusic` (initialized with cookies) instead of the public `self.ytmusic_public` client, enabling personalized suggestions and falling back dynamically to public requests if cookies are not present.

### 🛡️ Deadlock & Extraction Bug Fixes
- **🔒 Thread-Safe Lock Recursion Prevention:**
  Resolved a critical deadlock where resolving dynamic tracks inside the background queue processor (`Thread-3`) would recursively call `last_track.url` in the autoplay validator. Since `threading.Lock` is non-reentrant, this caused the thread to block indefinitely. Fixed by parsing the video ID directly from the private `last_track._url` property, bypassing dynamic property resolution and lock acquisition.
- **⚙️ Volatile Metadata Resolution Fix:**
  Fixed a `Failed to fetch stream data` bug where recommended tracks passed a raw scraper node dictionary as `extra_info` directly into `ydl.process_ie_result`, causing crash exceptions. The bot now checks if `extra_info` is a recommendation dictionary and dynamically resolves full yt-dlp metadata first.
- **🌀 Robust Recursive Parser:**
  Upgraded the recommendation HTML parser to recursively traverse JSON looking for both classic `compactVideoRenderer` and modern `lockupViewModel` structures, keeping recommendations resilient to YouTube web updates.

---

## 🆕 v2.4.9 — "Early Warning Update System" *(06/16/2026)*

### 📢 Pre-Update Notifications & i18n

- **🔔 Early Warning Notification:**
  Integrated a signaling mechanism using an `update_in_progress` trigger file. As soon as the VPS update or rebuild starts (when option `y` is selected in `update.sh`), the bot posts a warning message to the active TeamTalk channel: *"The bot is starting an update process and will restart shortly. It may go offline at any moment."*
- **🛑 Graceful Shutdown Alert:**
  Added signal handling for `SIGTERM`. When the container is stopping or restarting, the bot intercepts the termination signal and posts an immediate localized warning: *"The bot is restarting now to apply the update. See you in a moment!"* to the active TeamTalk channel before shutting down.
- **✅ Update Success Notification:**
  Integrated signaling logic where `update.sh` creates an `update_success` trigger file after a successful Docker container recreate. On boot, the bot checks for this file, announces: *"Update completed successfully! I am back online."*, and deletes the file.
- **🌍 100% Translated warning:**
  Fully translated and compiled the update starting, shutdown warning, and update success messages into all 8 supported languages (English, Portuguese, Spanish, Russian, Turkish, Arabic, Hungarian, Indonesian), ensuring native translation based on the bot's configured language.

---

## 🆕 v2.4.8 — "Documentation Restructuring" *(06/16/2026)*

### 📋 Documentation & Layout Simplify

- **🧹 Reverted Multi-Language Restructuring:**
  Removed the `docs/` directory and all translated READMEs. Restored the comprehensive root `README.md` to its original state. Moved `CHANGELOG.md` back to the root directory for simpler and cleaner navigation.
- **🗑️ Obsolete & Development Files Cleanup:**
  Removed unused scripts inside `tools/` (`vk_auth.py`, `yam_auth.py`, `libmpv_win_downloader.py`, `ttsdk_downloader.py`), development configuration files (`pyrightconfig.json`, `development-requirements.txt`), and IDE type stubs (`typestubs/`) to keep the codebase minimal and clean.

---

## 🆕 v2.4.7 — "Auto-Cleanup & DLL Management" *(06/14/2026)*

### 🐳 Docker & System Auto-Cleanup

- **🧹 Automatic Non-Interactive Pruning:**
  Added automatic Docker resources pruning to `update.sh` that executes immediately after the bot containers have successfully restarted and passed health checks.
  This runs `docker system prune -af --volumes` and `docker build/buildx prune -af` silently in the background, freeing up massive disk space (e.g. 1.3GB+) from older layers and build caches without requiring user interaction.

- **📜 System Journal Vacuuming:**
  Integrated journal logs vacuuming (`journalctl --vacuum-time=1d`) at the end of the update flow to prevent host log files from bloating the VPS storage.

### ⚙️ TeamTalk DLL Auto-Management

- **📥 Automated Architecture-Aware DLL Updates:**
  Added automatic downloading and extraction of TeamTalk DLL dependencies inside `update.sh`.
  The script automatically detects if the host is running on an ARM architecture (aarch64/arm) to download the matching `ttarm.zip` library, or falls back to the standard `TeamTalk_DLL.zip` for x86_64 systems, facilitating seamless cross-platform updates.

---

## 🆕 v2.4.6 — "Search Performance & Docker Optimization" *(06/13/2026)*

### ⚡ YouTube Music Search Speed Optimization

- **🔥 Persistent HTTP/2 Keep-Alive:**
  Configured `httpx.Limits(keepalive_expiry=30.0)` in `ytm.py` and reduced the background connection keeper sleep interval to `4 seconds`. This keeps the YTM session warm in the background and drops search response latency from ~1000ms to ~500ms.

- **⚡ HTTP/2 Support (YTM):**
  Integrated `httpx[http2]` inside `ytm.py` to enable HTTP/2 multiplexing, header compression, and connection persistence.

- **⏱️ YouTube Traditional (`yt.py`) Keep-Alive:**
  Added a background connection keeper to the standard YouTube service, dropping search pre-warming and query latencies from ~3.5 seconds to ~800ms.

### 🐳 Optimized Docker Rebuild Flow (Zero Downtime)

- **🚀 Rebuild Before Stop:**
  Modified `ttbotdocker.sh` and `update.sh` to run `docker build` first while the bot containers are still online. The containers are stopped and recreated ONLY after the build completes, reducing user downtime from 30+ seconds to just 2-3 seconds.

### 🔧 Permissions & Updater Polish

- **🛡️ Ignore File Permission Drifts in Git:**
  Added `git config core.fileMode false` dynamically in `update.sh`, `auto_updater.sh`, `install.sh`, and `install_git_clone.sh`. This ensures that recursive permission adjustments (`chmod`) performed by the installer or updater do not cause text or translation files (such as `docs/README.*.md`) to appear as unstaged mode changes (`new mode 100755`) on users' systems.

---

## 🆕 v2.4.5 — "Multi-Distribution Compatibility" *(06/13/2026)*

### 🖥️ Shell Scripts & Package Manager Abstraction

- **🌐 Dynamic Package Manager Detection:**
  Added the `install_packages` function in `install_git_clone.sh` and custom package manager mapping in `install.sh` to dynamically handle system packages for Debian/Ubuntu (APT), Fedora/RHEL/CentOS (DNF/YUM), Arch Linux (Pacman), openSUSE (Zypper), and Alpine (APK).

- **🐳 Docker Manager (`ttbotdocker.sh`) Generalization:**
  Upgraded dependency checks to install `jq` on Zypper and APK systems, wrapped all `systemctl` calls to avoid crashing on systemd-less environments, and replaced hardcoded `apt-get` calls in `uninstall_all` with appropriate commands for the detected package manager.

---

## 🆕 v2.4.4 — "Stability & Search Optimization" *(06/13/2026)*

### ⚡ Performance & Connectivity

- **🎵 YouTube Music Keep-Alive (Lag Reduction):**
  Added a background connection-warming thread in `ytm.py` that pings YouTube Music (`/generate_204`) every 15 seconds. This keeps the TCP/SSL connection warm, dropping latency by eliminating the TLS/SSL handshake penalty and lowering search times from ~1000ms to ~650ms.

- **🔍 Thread-Safe YT Search Event Loop:**
  Refactored `yt.py` to run async searches thread-safely on a persistent background event loop (`self._loop`) using `asyncio.run_coroutine_threadsafe(...).result()`. This resolves intermittent "Event loop is closed" errors during search execution.

### 🐛 Stability & Crash Prevention

- **🛡️ TaskProcessor Resilience:**
  Wrapped task execution inside `task_processor.py` in a `try-except` block. If resolving/playing a track fails, the worker thread no longer crashes, keeping the commands queue and playback system fully operational.

- **🚫 Unreleased / Private Video Loop Protection:**
  Added a `self._fetch_failed` state in `track.py` to prevent the bot from entering infinite resolution retries when trying to play private, deleted, or unreleased Premiere videos (such as videos that haven't premiered yet).

### 📋 Documentation & Metadata

- **🌐 Multi-Language Documentation Restructuring:**
  Moved `CHANGELOG.md` to `docs/CHANGELOG.md` and created 6 naturally translated versions of the README (`docs/README.en.md`, `docs/README.pt.md`, `docs/README.es.md`, `docs/README.es-419.md`, `docs/README.ar.md`, `docs/README.ru.md`).
  Replaced the root `README.md` with a clean, H1-level language entrypoint gateway to select the preferred documentation translation.

- **🏷️ Repository Metadata Update:**
  Updated the repository description on GitHub to: *"An enhanced music streaming bot for TeamTalk Servers with native YouTube Music support and Docker orchestration."*

---

## 🆕 v2.4.3 — "Node.js v22 Upgrade" *(06/11/2026)*

### 🐳 Docker & Dependencies Update

- **🟢 Node.js Upgrade to v22:**
  Upgraded the Node.js version installed in the Dockerfile from v20 to v22. This matches the new minimum JavaScript runtime requirements introduced in the latest `yt-dlp` (2026.06.09+), restoring YouTube signature solving (n-challenge) and resolving the "Requested format is not available" errors.

---

## 🆕 v2.4.2 — "Backup, Restore & Logs Cleanup" Update *(06/09/2026)*

### 🐳 Docker Manager (`ttbotdocker.sh`) Extensions

- **📦 Backup & Restore System (Portability):**
  Added a portable configuration and cache backup/restore system. Backups are saved as compressed `.tar.gz` files containing all bots configurations, cookies, and cache in a dedicated `backups/` directory. Restoring dynamically cleans old environments, extracts configs, and reconstructs Docker containers on any host machine.
  
- **🧹 Log Cleanup Option:**
  Added a quick-clear command that purges all `*.log` files within bot data folders in a single action, reclaiming storage space.

- **⚙️ Menu Rearrangement:**
  Reordered the "Manage Bots" submenu options: "Backup / Restore Bots" is now option **10**, "Clear All Bot Logs" is option **11**, and the "Return to Main Menu" (previously option 10) has been moved to option **12**.

---

## 🆕 v2.4.1 — "YTM Search Performance Fix" Update *(06/05/2026)*

### ⚡ Connection Pre-warming & Startup Polish

- **⏱️ Docker Container Startup Settling:**
  Added an initial `5 seconds` delay to the background pre-warming threads in both YouTube (`yt.py`) and YouTube Music (`ytm.py`) services. This allows the Docker container network interfaces and internal DNS resolvers to fully initialize before starting requests.
  
- **🔄 Robust Pre-warming Retry Mechanism:**
  Introduced a 3-attempt retry loop (with a 5-second interval) for the initial search request. This prevents the connection pools from failing permanently if the network takes a few extra seconds to boot.
  
- **📢 Improved Logging & Diagnostics:**
  Warmed-up connection attempts are now explicitly tracked via logs. If the pre-warming fails all retries, it raises a warning/error in the logs instead of failing silently at debug level.

- **⚙️ Default Service Config Update:**
  Changed the default search and stream service from YouTube (`yt`) to YouTube Music (`ytm`) in `config.json` and `config_default.json` templates to provide the music-oriented experience by default.

---

## 🆕 v2.4.0 — "Universal Docker & Configurable Search" Update *(06/05/2026)*

### 🖥️ Native ARM64 Compatibility & Code Cleanup

- **🤖 Platform Auto-detection:**
  Added system architecture auto-detection (`uname -m`) to `install_git_clone.sh`. The installer now automatically selects and downloads the appropriate TeamTalk library binary (`ttarm.zip` for ARM64 / ARM devices, or the standard `TeamTalk_DLL.zip` for x86_64 systems).

- **🐳 Docker & Host Dependencies for ARM:**
  Added the `libportaudio2` library dependency to `Dockerfile` and `install.sh`. This resolves the missing `libportaudio.so.2` runtime link errors when executing the ARM64 compiled TeamTalk SDK inside the Docker container or directly on the host system.

- **⚙️ Conditional Package Installation (Minimal Footprint):**
  Refactored dependency installation logic. The `libportaudio2` package is now conditionally installed ONLY when an ARM environment (`arm64`/`armhf`/`aarch64`) is detected. This ensures that `x86_64` environments remain minimal and untouched by ARM-specific runtime dependencies.

- **🧹 Code Cleanup:**
  Removed redundant Docker installation checks from `install_git_clone.sh`, delegating all environment dependencies verification and setup to `ttbotdocker.sh`.

### 🔍 Configurable Search Results Default

- **⚙️ Config-Driven Search Limits:**
  Added the `search_results: int = 1` option to both YouTube (`yt`) and YouTube Music (`ytm`) configuration models in `models.py`, defaulted in `config.json` and `config_default.json`.
  
- **🔄 Dynamic Fallback in Services:**
  Updated the base service search interface in `__init__.py` and implementations in `yt.py` and `ytm.py` to use the configuration-defined default search results limit (1) when the dynamic limit parameter is omitted.

- **🔢 Search Results Mode Command Updates:**
  Changed the default volatile search count for the `sr`/`slc`/`sl` commands from `5` to `1` in `__init__.py` and `user_commands.py`.

### 🐳 Universal Docker Setup

- **🚀 Support for Any Linux Distribution:**
  Upgraded the Docker environment checks in `ttbotdocker.sh` to use the official universal `get.docker.com` script. This enables automatic setup of Docker Engine across all major distributions (Ubuntu, Debian, CentOS, RHEL, Fedora, Rocky, Alma, Raspbian).
  
- **🧹 Installer Script Cleanup:**
  The downloaded `get-docker.sh` installer script is automatically deleted immediately after completion to keep the host directory clean.

- **📦 Multi-Distribution dependency installer:**
  Added fallback detection for package managers (`apt`, `dnf`, `yum`, `pacman`) to install the `jq` dependency dynamically on any supported Linux distribution.

---

## 🆕 v2.3.0 — "Dynamic SSL Trust" Update *(05/30/2026)*

### 🔒 Dynamic SSL Trust & Peer Verification Bypass

- **🛡️ Auto-fetching SSL Certificates:**
  When connecting to an encrypted TeamTalk server (`encrypted: true`), the bot now automatically attempts to fetch the server's certificate dynamically over the network if a local CA certificate (`ttservercert.pem`) is not configured.

- **✅ Local and Third-Party Server Support:**
  The dynamically fetched certificate is temporarily trusted via OpenSSL/ACE SSL verification, allowing seamless encrypted connections to self-signed or third-party servers without manual certificate management (mirroring the Windows client behavior).

- **🔧 Exposed `setEncryptionContext` in Wrapper:**
  Exposed the C-level `TT_SetEncryptionContext` function inside `TeamTalkPy` wrapper as `setEncryptionContext`, enabling programmatic control over SSL contexts directly from Python.

---

## 🆕 v2.2.0 — "Link-Based Downloading" Update *(05/23/2026)*

### 🔗 Link-Based Downloading Commands

- **➕ `aad LINK` Command — Add Link:**
  Adds a single media link/URL to the user's custom download list.

- **➕ `ad LINK1 LINK2 ...` Command — Add Multiple Links:**
  Adds multiple space-separated links to the download list at once.

- **📜 `ld` Command — List Links:**
  Displays a numbered list of all links currently in the user's download list.

- **🗑️ `rd NUMBER_OR_LINK` Command — Remove Link:**
  Removes a link from the download list by its index or URL string.

- **📥 `ldd LINK` Command — Download Direct:**
  Directly downloads a link asynchronously and uploads it to the TeamTalk channel.

- **⚡ `ads` Command — Download and Upload List:**
  Asynchronously downloads the user's link list. Prompts the user to choose between:
  1. Downloading individually (Normal sequential upload)
  2. Compressing all resolved tracks into a single ZIP archive and uploading it.

- **💾 `adsc` Command — Toggle Local VPS Download Mode:**
  Toggles local download mode for the `ads` command (volatile, resets on bot restart).
  When active, downloads are saved locally to the VPS filesystem under `data/Downloads/music/` (Option 1) or `data/Downloads/zips/` (Option 2) instead of uploaded to TeamTalk, and are excluded from auto-deletion. Outputs a final translated status report.

### 🌍 100% Localization & Translations

- Fully translated and compiled all 27 new strings (commands, prompts, errors, success reports) across all 7 supported languages: Arabic (`ar`), Spanish (`es`), Hungarian (`hu`), Indonesian (`id`), Portuguese-Brazil (`pt_BR`), Russian (`ru`), and Turkish (`tr`).

### 🐛 Core Uploader & Stability Fixes

- **⏱️ Non-blocking Deletion Timer:**
  Changed the file deletion timer in the uploader to run in a background daemon thread, preventing batch downloads from blocking.

- **🛡️ Server Error Infinite Loop Fix:**
  Fixed a major bug where unhandled server error codes (e.g. `FileAlreadyExists`) would lock the uploader in an infinite loop. It now breaks and handles errors gracefully.

---

## 🆕 v2.1.0 — "Smart Search & Docker Polish" Update *(05/21/2026)*

### 🔍 New Bot Commands — Search Results Mode

- **🔎 New `sr` Command — Search Results Mode Toggle:**
  When active, the `p QUERY` command no longer plays immediately — it instead shows a **numbered list** of results. Use `sr on`, `sr off`, or just `sr` to toggle. Use `sc` to save the setting permanently to `config.json`.

- **🎯 New `sl NUMBER` Command — Select from Search Results:**
  After a search (with `sr` mode active), pick exactly which track to play by its number. Results are stored **per user** and cleared after selection for a clean experience.

- **🔢 New `slc NUMBER` Command — Set Search Results Count:**
  Controls how many results are displayed per search when `sr` mode is active. Defaults to **5**. Use `slc` alone to check the current count. Resets to 5 on bot restart.

### 🐳 Docker Manager (`ttbotdocker.sh`) Improvements

- **⏱️ File Deletion Timer — Create Bot:**
  When creating a new bot, the script now reads `general.delete_uploaded_files_after` from `config.json` and offers to customize the value per bot. `0` = never delete. Supports any duration in seconds.

- **⏱️ File Deletion Timer — Bulk Update:**
  New **Option 6** in the Bulk Update Configuration menu allows changing `delete_uploaded_files_after` across bots without rebuilding. Option 7 ("Everything") now also includes the timer.

- **🎯 Selective Bot Update — Bulk Update now targets specific bots:**
  After choosing what to change, a new targeting menu appears:
  - **Option 1:** Apply to ALL bots
  - **Option 2:** Apply to a **single specific bot** (from a numbered list)
  - **Option 3:** Apply to a **custom subset** (space-separated numbers)

  Only selected bots are updated **and restarted** — other running bots are not touched.

### 📚 Documentation

- **📋 CHANGELOG extracted from README:**
  Full version history moved to a dedicated [`CHANGELOG.md`](CHANGELOG.md) file. The README now shows only the latest update with a link to the full history.

---

## 🆕 v2.0.0 — "The Video" Update *(05/14/2026)*


- **🎥 New `dlv` Command:** Download current track as **Video** (.mp4) directly to the channel.
- **🧠 Smart Uploader 2.0:** Rewritten uploader module with intelligent file discovery. If the expected format isn't found, it automatically searches for alternative extensions (.mkv, .webm, etc.) before failing.
- **🎞️ Forced MP4 Encoding:** Optimized video downloads to force MP4 merging, ensuring maximum compatibility with all media players.
- **🌍 Global Video Support:** Full localization for the `dlv` command across all 7 supported languages (PT-BR, ES, HU, ID, RU, TR, AR).
- **🛠️ Robustness Fix:** Resolved naming inconsistencies between `yt-dlp` output and uploader expectations.

---

## 🆕 v1.9.0 — "Performance & Cleanup" Update *(05/11/2026)*

- **🧹 Deep Docker Cleanup:** Added a powerful cleanup option (Option 7) to `ttbotdocker.sh` that wipes stopped containers, unused images, build cache, and even host system logs (`journalctl`) to reclaim maximum disk space.
- **📉 200MB+ Image Reduction:** Drastically reduced Docker image size (from ~1.6GB to ~1.4GB) by implementing:
  - **`.dockerignore`:** Prevents bloating the image with `.git`, `bots/` folders, and other host-only files.
  - **`--no-cache-dir`:** Optimized PIP installations to not store installer caches inside the container.
- **🚀 Faster Builds:** The new `.dockerignore` prevents uploading unnecessary files to the Docker daemon, making the build process more efficient.
- **📊 Real-time Disk Reclaim:** Cleanup process now includes `buildx prune` and system journal vacuuming for a truly "zero-clutter" environment.

---

## 🆕 v1.8.0 — "Universal Language" Update *(05/10/2026)*

- **🌍 Arabic Support Added:** Full native support for Arabic (`ar`) language, including right-to-left (RTL) considerations for messages.
- **💯 100% Localization:** Achieved 100% translation coverage across all supported languages (PT-BR, ES, HU, ID, RU, TR, AR).
- **🆕 Queue & Playlist i18n:** All new features (Queue system, Playlist downloads) are now fully localized in every language.
- **🧹 Systematic Audit:** Complete cleanup of all translation catalogs, resolving fuzzy strings and missing translations for a seamless global experience.

---

## 🆕 v1.7.0 — "Queue System" Update *(05/09/2026)*

> A huge shoutout and massive credits to **ericoamico** for his incredible dedication and a full week of hard work in developing this amazing feature! All credits for the new queue system go to him.

- **🗂️ Advanced Queue System:** You can now queue multiple tracks to play sequentially!
- **➕ Add to Queue:** Use the `qa` command to search for a track and seamlessly add it to your queue.
- **📜 View Queue:** Check what's playing next with the `ql` command to list all queued tracks.
- **🗑️ Queue Management:** Use `qr [number]` to remove a specific song, or `qc` to clear the entire queue at once.
- **⏭️ Smart Skip:** The new `qs` command skips the current track and instantly plays the next one from the queue.

---

## 🆕 v1.6.0 — "Playlist Power-Up" Update *(05/06/2026)*

- **📦 New `dlp` Command:** Download entire YouTube/YouTube Music playlists and albums as organized ZIP archives directly to the TeamTalk channel.
- **📂 Intelligent ZIP Structure:** Archives now wrap contents inside a subfolder named after the playlist/album, ensuring a clean extraction process.
- **🧠 Smart Naming Engine:** Automatically distinguishes between Official Albums (`Album - Artist.zip`) and personal Playlists (`Playlist Name.zip`) based on link patterns and metadata.
- **🕵️ PM Progress Reporting:** Live track-by-track download progress is sent via **Private Message (PV)** to keep the channel clean while keeping the user informed.
- **📊 Active Status Check:** Typing `dlp` without arguments during an active download returns the current real-time status of the process.
- **💾 Permanent Channel Storage:** Playlist ZIPs are stored permanently in the channel (not auto-deleted like `dl` files), building a community library.
- **🌍 Full Localization (i18n):** All new features and status messages fully localized for Portuguese, Spanish, Turkish, and Russian.
- **🛠️ Enhanced Metadata Scanning:** Aggressive multi-track scanning to extract correct artist and album names even from tricky direct links.

---

## 🆕 v1.5.0 — "Global Expansion" Update *(05/03/2026)*

- **🌍 Full i18n Localization:** Completed full translation and standardization for PT-BR, Turkish (TR), Spanish (ES), and Indonesian (ID). All core commands and system messages are now fully localized.
- **🎧 Studio Quality Audio (320kbps):** Upgraded audio streaming and transcoding to 320kbps MP3 by default for superior sound quality.
- **🔄 Bulletproof Auto-Updater:** Major overhaul of the update system. Resolved infinite loops, fixed remote detection issues, and ensured updates work even with local file changes.
- **⚡ Optimized Extraction:** Fixed YouTube signature errors and optimized ServiceManager for faster track loading and reduced latency.
- **🎮 Polling Optimization:** Reduced auto-updater polling interval to 20 seconds for near-instant synchronization with the repository.
- **🧹 Robust File Lifecycle:** Enhanced cleanup logic for temporary files and cookies, ensuring a zero-footprint operation after every request.

---

## 🆕 v1.3.1 — "Zero-Footprint" Update *(04/24/2026)*

- **🛡️ Auto-Cleanup for Cookies:** When pasting cookies, the temporary file created in `/tmp` is now automatically deleted immediately after use, ensuring zero disk footprint and maximum privacy.
- **🎮 Auto-Update Controller (`masc.sh`):** New dedicated menu (Main Menu option 6) to enable/disable automatic updates with systemd masking for 100% persistence.
- **🍪 Cookie Paste Option:** Paste cookies directly into the terminal; the script auto-normalizes formatting (spaces to tabs) and sets correct file permissions.
- **🛡️ Per-Request Cookie Lifecycle:** Each download or stream request now creates a unique, volatile copy of your `cookies.txt` in `/tmp`. These files are deleted immediately after use, ensuring 100% privacy and zero disk clutter.
- **🐳 Dockerfile Optimization:** Updated `httpx` to version `0.28.1+` and resolved dependency conflicts, ensuring a stable and compatible network stack.
- **🧵 Thread-Safe Authentication:** The temporary cookie mechanism is now fully thread-safe, allowing multiple bots to operate without file access conflicts.

---

## 🆕 v1.1 — "Reliability & Quality" Update *(04/23/2026)*

- **🚀 Automated Background Updates:** Systemd service monitors GitHub every 20 seconds.
- **🎵 High-Quality MP3:** Migrated to 192kbps MP3 by default.
- **✅ Improved Permissions:** Refined upload logic for non-privileged bots.

---

## 🆕 YouTube Music Support *(03/19/2026)*

- **YouTube Search API Integration:** Uses the YouTube Search API for fast and reliable music discovery
- **Optimized Libraries:**
  - YouTube uses `py-yt-search` — a fast and modern Python library for YouTube searches
  - YouTube Music uses `ytmusicapi` — the official YouTube Music API library
  - Both services use `yt-dlp` for audio extraction
- **Performance Focus:** Designed to run with minimal bottlenecks, ensuring smooth playback and quick search results
- **Unified Cookie System:** Both YouTube and YouTube Music use the same cookies configuration for authentication
- **📦 Playlist & Album Downloads:** Full support for downloading entire collections via the `dlp` command with metadata-aware naming
- **🕵️ Real-time PM Progress:** Stay updated on your downloads without cluttering the channel

---

## 🪟 Windows Port — Logging Overhaul *(10/08/2026)*

> **Maintained by:** [YOUR NAME] — [YOUR GITHUB URL]
>
> This section is appended at the **bottom** on purpose. This port follows the Linux upstream (`JoaoDEVWHADS/TTMediaBot`), which adds its own entries at the top, so pulling a new upstream release never conflicts with the entries below.

### 🐛 Fixed: `TTMediaBot.log` Stayed Empty While Errors Went to the Console
- **🔎 Root cause:** `Player.__init__` runs inside `Bot.__init__` and calls `ffmpeg_locator.get_ffmpeg()`, which logs with `logging.info()` (and `logging.warning()` for broken candidates) before `initialize_logger()` has run. A `logging.*()` call on a root logger without handlers triggers an implicit `logging.basicConfig()` that attaches a console handler and leaves the root level at `WARNING`; every later `basicConfig()` call is a silent no-op. The configured `RotatingFileHandler` was therefore never attached: the file stayed at 0 bytes, warnings and errors went to the console, and every `INFO` line (`New message …`, `Executing command …`, `[FFmpeg] Using …`) was recorded nowhere. The Linux upstream has the same flaw (there the python-mpv `log_handler` thread triggers it); in the FFmpeg port it happened on every start.
- **🪵 Early-Log Buffer:** `bot/logger.py` now installs a bounded buffer (1000 records) on the root logger the moment the `bot` package is imported (`install_bootstrap_logging()` at the top of `bot/__init__.py`). Nothing can trigger the implicit `basicConfig()` any more, and records emitted before the logger is configured are replayed into the real handlers instead of being lost.
- **⚙️ No More `basicConfig()`:** `initialize_logger()` configures the root logger directly: it removes stray handlers, attaches the file/console handlers, sets the level, then replays the buffered records. The `log`, `level`, `format`, `mode`, `file_name`, `max_file_size` and `backup_count` options and the `-l/--log` argument behave exactly as before.
- **🧭 Startup Line:** The first line of every run now reads `Logger initialized: level=…, mode=…, file=…`, so the real log location is always visible.

### 🛟 Hardened: Errors That Used to Disappear
- **💥 Uncaught Exceptions:** Errors raised in the main thread, in any worker thread, or as unraisable exceptions are now written to the log with a full traceback. In `FILE` mode an uncaught main-thread crash is still shown on the console as well, so a dead bot is never silent.
- **⚠️ Python Warnings:** `warnings` are captured into the log (`logging.captureWarnings`).
- **🎬 FFmpeg Detection:** Messages from `ffmpeg_locator` (`Using system ffmpeg …`, `could not be executed`, `chmod failed`) now reach the log file. If the bot stops before logging is configured (for example FFmpeg is not found), the waiting warnings are printed to the console on exit instead of being lost. With `--check`/`--devices` they appear immediately.
- **🧹 Stray `print()` Calls:** Event-handler errors in `bot/TeamTalk/thread.py` and download errors in `downloader.py` now go through `logging` with a traceback.
- **🔒 Safe Fallbacks:** If the log file cannot be opened the bot reports why and logs to the console instead of running blind. An invalid `level` or `mode` value exits with a clear message. With `"log": false` only warnings and errors are shown on the console, as Python does by default.

### ✅ Tests
- Added `test_logger_early_logging.py` (8 tests): records emitted before initialization (including the `[FFmpeg] Using …` line) reach the file, a stray root handler no longer hijacks the log, uncaught main/thread exceptions are logged, an unwritable log file falls back to the console, invalid `level`/`mode` exit cleanly, the `log: false` path replays warnings only, and warnings are not lost when the bot exits early. It loads `bot/logger.py` directly, so it needs neither the TeamTalk library nor FFmpeg.

### 📁 Files Changed
- `bot/logger.py` (rewritten), `bot/__init__.py`, `TTMediaBot.py`, `bot/TeamTalk/thread.py`, `downloader.py`, `test_logger_early_logging.py` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — Autoplay Isolation Fix *(10/08/2026)*

> **Maintained by:** [YOUR NAME] — [YOUR GITHUB URL]

### 🐛 Fixed: `n` Played YouTube (`yt`) Tracks While YouTube Music (`ytm`) Was Active
- **🔎 Root cause:** `YtService._pre_warm()` warmed the bridge with `self.search("test", limit=1)`. `YtService.search()` starts an autoplay fetch whenever it returns exactly one result, so the pre-warm of the *YT* service fetched recommendations for the throw-away "test" video. That fetch runs in a background thread and finished a few hundred milliseconds after the first `p QUERY` (log: `[YT] Fetching continuous recommendations for 6TWJaFD6R2s` at 10:32:43, `[YT] Adding 15 continuous recommendations … (total: 16)` at 10:32:44). It appended 15 `yt` tracks to the single shared `Player.track_list` of the `ytm` track that had just started, and the YTM recommendations were appended *after* them (`total: 31`). `n` walks that list in order, so it played the `yt` tracks first. The same could happen later whenever a failed pre-warm was retried by the periodic pre-warm.
- **🛡️ Guarded append:** Both services now hand their recommendations to the new `Player.add_autoplay_tracks()` instead of calling `track_list.extend()` themselves. Recommendations are accepted only while the seed video (the track they were fetched for) from the *same service* is still part of the current `track_list`; otherwise they are discarded and logged (`[Autoplay] Discarded …`). This also covers a stale fetch of a previous song finishing after a new `p QUERY`.
- **⏱️ Race handled:** `p QUERY` starts the autoplay fetch inside `search()` and calls `Player.play()` only afterwards, so a fast fetch can finish before the seed track is installed. The background path waits up to 5 s (`AUTOPLAY_SEED_WAIT_SECONDS`) for the seed track instead of dropping the result; the synchronous path used by `n` never waits.
- **🔥 Pre-warm:** `YtService._pre_warm()` now calls the bridge directly (`self._bridge.search("test", 1)`), exactly like `YtmService._pre_warm()`, so a warm-up can no longer start an autoplay fetch.
- **🧹 Legacy method:** `YtmService._fetch_and_queue_autoplay()` (unused) extended `track_list` without any check; it now delegates to the guarded path.
- **📝 Log lines:** `[YT]/[YTM] Adding N continuous recommendations …` is now `[Autoplay] Added N <service> recommendations for video_id … (total: …)`, and unique-check results are logged as `[Autoplay] No new unique …`.

### ✅ Tests
- Added `test_autoplay_isolation.py` (7 tests): a stale/foreign seed is discarded, the same video id on another service is not a match, recommendations are de-duplicated and limited to 15, a seed that appears late is waited for, a seed replaced by a newer `p QUERY` is discarded, the zero-wait path returns immediately, and `YtService._pre_warm()` no longer starts an autoplay fetch.

### 📁 Files Changed
- `bot/player/__init__.py`, `bot/services/yt.py`, `bot/services/ytm.py`, `test_autoplay_isolation.py` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — YouTube 403 Forbidden Protection *(10/08/2026)*

> **Maintained by:** [YOUR NAME] — [YOUR GITHUB URL]

### 🐛 Fixed: Every YouTube Stream Ended With `HTTP error 403 Forbidden`, and the Bot Skipped Through the Whole List
- **🔎 Symptom:** after `p QUERY` every `googlevideo.com` URL was refused (`[FFmpeg] Playback ended with an error … HTTP error 403 Forbidden`). The one allowed stream refresh failed too, so the bot jumped to the next track, which failed again, and went through about 65 tracks in 20 seconds. All failing URLs carry `c=MWEB`.
- **🔎 Most likely cause:** the bridge resolves streams with the MWEB client, and for that client YouTube requires a *PO token* on the media URL (yt-dlp's PO Token Guide lists `mweb` as needing a GVS PO token; YouTube.js only appends `pot=` to the URL when it was given a token). The bridge asks a PO token provider (the bgutil HTTP server on `127.0.0.1:4416`). On Linux/Docker `youtube_services.sh` starts it; **on Windows nothing ever started it**, so the bridge logged `POT provider unavailable` only in `youtube_bridge.log` and handed FFmpeg URLs without a token. YouTube rolls this enforcement out gradually, which is why the same setup could play earlier the same day. A missing token is not the only possible reason for a 403 (a PO token is not a guarantee), so the provider's presence is now reported in `TTMediaBot.log`.
- **🚀 Provider autostart (`bot/services/bridge_launcher.py`):** when the bgutil provider is installed in `bgutil-provider/` beside `TTMediaBot.py` (or in the folder named by `POT_PROVIDER_DIR`), the bot now starts it with Node.js next to the bridge (`node server/build/main.js --port 4416`, log in `pot_provider.log`), waits for `/ping` in the background so the bridge start-up is not delayed, and stops it on exit. If a provider already answers, it is left alone. Docker deployments are untouched (the shared container runs it). Opt out with `YOUTUBE_POT_AUTOSTART=0`; a custom address can be set with `POT_PROVIDER_URL`.
- **📣 Visible diagnosis:** if no provider is running and none is installed, `TTMediaBot.log` now says so once, with the 403 consequence and the install commands, instead of failing silently.
- **🛑 Failure cascade stopped (`bot/player/__init__.py`):** a track that cannot be played is still skipped (after its single stream refresh), but after `MAX_CONSECUTIVE_STREAM_FAILURES` (5) failing tracks in a row the player stops, logs `[Player] 5 tracks in a row could not be played …` and tells the channel, instead of sending dozens of failing requests to YouTube in seconds. The counter resets as soon as a track actually starts playing or a new `p`/`play` is issued.

### ✅ Tests
- Added `test_youtube_403_protection.py` (8 tests): a missing provider is reported once and never raises; an installed provider is started with `--port 4416` from its `server` folder; a running provider is left alone; Docker/opt-out/remote URL never start a local process; failing tracks are skipped until the limit and then playback stops; a track that starts playing resets the counter; a normal end of track is never counted.

### 📁 Files Changed
- `bot/services/bridge_launcher.py`, `bot/player/__init__.py`, `test_youtube_403_protection.py` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — YTM Recommendations Stay Music-Only *(10/08/2026)*

> **Maintained by:** [YOUR NAME] — [YOUR GITHUB URL]

### 🐛 Fixed: `n` on YouTube Music Played Ordinary YouTube Uploads
- **🔎 Cause:** YouTube Music's Up Next (the source of `ytm` autoplay) also lists regular YouTube videos such as covers and fan uploads. The bot queued them as `ytm` tracks, so `n` jumped from the music catalogue to "… | Cover by PI7U" uploads. Catalogue songs always carry an artist credit; these uploads only have a channel name.
- **🛡️ Fix:** `YtmService` keeps only recommendations that carry an artist credit (`YtmService._only_music_entries`). If that would leave nothing, the unfiltered list is used so autoplay never runs dry. Dropped items are logged as `[YTM] Dropped N non-music uploads from recommendations`.

### ✅ Tests
- Added `test_ytm_music_only.py` (3 tests).

### 📁 Files Changed
- `bot/services/ytm.py`, `test_ytm_music_only.py` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — PO Token Provider in the Windows Installer *(10/08/2026)*

> **Maintained by:** [YOUR NAME] — [YOUR GITHUB URL]

### 🛠️ Changed: `install_windows.bat` Installs the bgutil PO Token Provider
- **🔎 Why:** on Windows the bgutil PO token provider was never installed, so the YouTube.js bridge sent stream URLs without a PO token and YouTube answered `HTTP error 403 Forbidden`. Linux/Docker already build it; Windows did not.
- **📥 New step `[4/6]` (install):** the installer clones `Brainicism/bgutil-ytdlp-pot-provider` into `bgutil-provider\`, then runs `npm ci` and `npx tsc` inside `bgutil-provider\server` (Git and Node.js required). The result is `bgutil-provider\server\build\main.js`.
- **🪟 New step `[5/6]` (launch):** the installer opens a second command window titled "TTMediaBot PO token provider" and runs `node build\main.js --port 4416` in it, so the provider log stays visible. If something already answers on port 4416, nothing new is started.
- **♻️ Safe to re-run:** the clone is skipped when `bgutil-provider\.git` exists, and the build is skipped when `server\build\main.js` exists.
- **⚠️ Non-fatal:** a failed download or build prints a warning with the commands to retry, and the installer continues. A missing Git or Node.js prints the `winget` command to install it.
- Later steps were renumbered: the bridge step is `[3/6]` and the FFmpeg/TeamTalk check is `[6/6]`.

### 📁 Files Changed
- `install_windows.bat`, `CHANGELOG.md`.

---

## 🪟 Windows Port — Bot No Longer Freezes After Playing for a While *(10/09/2026)*

> **Maintained by:** [YOUR NAME] — [YOUR GITHUB URL]

### 🐛 Fixed: Bot Stopped Answering Commands While the Music Kept Playing
- **🔎 Symptom:** after the bot had been running for a while it stopped reacting to chat commands (`p`, `n`, `s`, …) while the queue kept playing on its own, until the bot was restarted.
- **🔎 Cause (from `TTMediaBot.log`):** `Unhandled exception in thread TeamTalkThread … ValueError: 1110 is not a valid EventType`, seen at 17:12:36 and again at 17:20:05. 1110 is `CLIENTEVENT_SOUNDDEVICE_REMOVED`, one of the sound-device notifications (1100–1160) that newer TeamTalk SDK builds post when Windows adds, removes or changes an audio device (they appear in the SDK 5.22A documentation, not in the older 5.11A one). `EventType` did not list them, so converting the event raised `ValueError`, which ended `TeamTalkThread`, the only reader of the TeamTalk message queue. The rest of the bot kept running (pre-warming and track changes continued for two more hours in the log) but could no longer hear the channel or the server, so it looked frozen.
- **🛡️ Fix 1 — known events (`bot/TeamTalk/structs.py`):** `EventType` now includes `CON_CRYPT_ERROR` (15), `USER_ACCOUNT_NEW` (410), `USER_ACCOUNT_REMOVE` (420) and the sound-device events `SOUND_DEVICE_ADDED`, `SOUND_DEVICE_REMOVED`, `SOUND_DEVICE_UNPLUGGED`, `SOUND_DEVICE_NEW_DEFAULT_INPUT`, `SOUND_DEVICE_NEW_DEFAULT_OUTPUT`, `SOUND_DEVICE_NEW_DEFAULT_INPUT_COMDEVICE` and `SOUND_DEVICE_NEW_DEFAULT_OUTPUT_COMDEVICE` (1100–1160). The numbers fall back to the SDK's published values when the `TeamTalk5.py` binding does not name them, so an older binding still imports. The bot plays through TeamTalk's virtual sound device, so these events only need to be recognised and ignored.
- **🛡️ Fix 2 — unknown events never raise (`bot/TeamTalk/__init__.py`):** the new `TeamTalk.get_event_type()` converts the event number and treats anything unknown as `EventType.NONE` (ignored). Each unknown number is logged once as `Ignoring unknown TeamTalk event number N …`, so a future SDK update cannot repeat this.
- **🛡️ Fix 3 — the event thread survives errors (`bot/TeamTalk/thread.py`):** the body of the loop moved into `TeamTalkThread.handle_event()` and every pass is wrapped. Any error while processing one event is logged as `Error while handling a TeamTalk event; the event thread keeps running (failure #N)` (full traceback for the first 5 in a row, then every 100th) and the thread carries on, with a short pause if the same error repeats. `sys.exit(1)` for fatal connection/login errors is a `SystemExit` and still ends the thread on purpose. Added the `TeamTalkThread.closing` property.
- **🐕 Fix 4 — watchdog (`bot/__init__.py`, `bot/TeamTalk/__init__.py`):** if the event thread does end by itself (for example a fatal `Connection error` once the configured `reconnection_attempts` is used up), the main loop now notices through `TeamTalk.event_thread_stopped()`, logs `The TeamTalk event thread stopped unexpectedly …`, closes the bot cleanly and exits with code 1 instead of idling silently. A normal shutdown is not affected.

### ✅ Tests
- Covered by 14 unit tests (run locally, not part of the repository): the sound-device, `CON_CRYPT_ERROR` and `USER_ACCOUNT_*` numbers map to `EventType`; an unknown number returns `NONE` and is reported only once; an error while reading an event, or several in a row, does not end the thread and the next chat message is still delivered; ignored events are skipped quietly; `sys.exit()` still ends the thread; the watchdog reports a thread that died by itself but not one that never started, is running, or is being closed.

### 📁 Files Changed
- `bot/TeamTalk/structs.py`, `bot/TeamTalk/__init__.py`, `bot/TeamTalk/thread.py`, `bot/__init__.py`, `bot/app_vars.py`, `CHANGELOG.md`.

---

## 🪟 Windows Port — YouTube Bridge Stall Protection *(10/10/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 🐛 Fixed: A YouTube Request That Hung Left `p` Waiting for About 15 Seconds
- **🔎 Symptom:** now and then a command waited far longer than normal. `TTMediaBot.log` recorded `YTM Search (Fast) finished in 15373…ms` for `p sial` and a next-track prefetch of about the same length (15.4 s), while the usual search takes about half a second and a stream resolution well under a second. The network of the host is unstable (`Server lost` appears in the log).
- **🔎 Cause:** not confirmed. The bot opens a new connection to the bridge for every call, and none of the bridge's own steps in six recorded bridge sessions lasted longer than 6.7 s, so these two waits could not be matched to a bridge step. The most likely place for a hang is a pooled connection to YouTube that died silently. The timestamped bridge log (see *Timestamped Bridge Log and Request Diagnostics*) is meant to show where such a wait happens if it comes back.
- **🛡️ Fix — hung requests are repeated on a fresh connection (`youtube_bridge/server.mjs`):** the new `retryOnStall()` abandons a call that does not answer within its limit and repeats it, so the repeat cannot reuse the busy connection. Searches wait 5 s and are tried up to three times, player (stream) requests wait 8 s and are tried up to twice, and the keep-alive Music search waits 5 s and is tried twice. Only hangs are repeated: an error from YouTube or "no streaming data" is reported at once without a retry.
- **⏱️ Fix — PO-token timeout:** a request to the bgutil provider now gives up after 8 s instead of waiting indefinitely; the bridge then continues without a token as it already did when the provider was down.
- **🎚️ Tunable limits:** `YOUTUBE_BRIDGE_STALL_TIMEOUT_MS` (searches, default `5000`), `YOUTUBE_BRIDGE_PLAYER_TIMEOUT_MS` (player requests, default `8000`) and `YOUTUBE_BRIDGE_POT_TIMEOUT_MS` (PO-token requests, default `8000`).

### ✅ Tests
- The 9 bridge unit tests (`node --test`) still pass.
- Checked locally with a stand-in for YouTube.js (not part of the repository): a search that hangs once is repeated after its limit and then answers; a player request that hangs once is repeated and resolves. Without the change the same hung search never answered.

### 📁 Files Changed
- `youtube_bridge/server.mjs`, `CHANGELOG.md`.

---

## 🪟 Windows Port — Third Fallback Client and More Video Link Formats *(10/10/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 🐛 Fixed: The `TV_EMBEDDED` Fallback Client Was Rejected as `Invalid client`
- **🔎 Symptom (from `youtube_bridge.log`):** `TVHTML5_SIMPLY_EMBEDDED_PLAYER: Invalid client` appeared whenever the first two clients failed. Three videos then failed on every client (`No valid URL to decipher` for the YouTube Music and mobile web clients, followed by the rejected third client).
- **🔎 Cause:** the bridge passed the enum value `ClientType.TV_EMBEDDED` (`TVHTML5_SIMPLY_EMBEDDED_PLAYER`) to `getBasicInfo()`. According to the YouTube.js documentation that option takes the client key `TV_EMBEDDED`, so the third fallback client could never run.
- **🛡️ Fix:** `youtube_bridge/server.mjs` now passes the key `TV_EMBEDDED` (constant `TV_EMBEDDED_CLIENT`) both when choosing the client list and when deciding that this client takes no PO token. Whether the client then returns a playable stream is up to YouTube; it now gets the chance to try.

### 🐛 Fixed: `u` Rejected `youtube.com/live/…` Links
- **🔎 Symptom:** `u https://www.youtube.com/live/…` failed with `Invalid YouTube URL or video ID`, because the bridge only recognised `youtu.be`, `?v=` and `/shorts/` links.
- **🛡️ Fix:** `extractVideoId()` now also accepts `/live/`, `/embed/` and `/v/` links. Path-style links must carry a valid 11-character video ID; anything else is still rejected.
- **ℹ️ Note:** a stream that is live right now may still fail to play, because the bridge selects regular audio formats and does not use the live (HLS) manifest.

### ✅ Tests
- Checked locally with a stand-in for YouTube.js (not part of the repository): the `TV_EMBEDDED` client is accepted and resolves when it is the only working client, whereas the previous code reproduced `Invalid client`; links in the `youtu.be`, `?v=`, `music.youtube.com`, `/shorts/`, `/live/` and `/embed/` forms return the right video ID, while a too-short ID and a channel URL are rejected.

### 📁 Files Changed
- `youtube_bridge/server.mjs`, `CHANGELOG.md`.

---

## 🪟 Windows Port — Timestamped Bridge Log and Request Diagnostics *(10/10/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 🛠️ Changed: `youtube_bridge.log` Can Now Be Lined Up With `TTMediaBot.log`
- **🔎 Why:** the bridge log had no timestamps, so a slow command recorded in `TTMediaBot.log` could not be matched with what the bridge was doing at that moment.
- **🕒 Timestamps:** every bridge log line now starts with a local timestamp in the same format as `TTMediaBot.log` (`YYYY-MM-DD HH:MM:SS,mmm`).
- **📥 Request log:** new `[youtube-bridge-http]` lines mark when a request reaches the bridge (`->`) and when it finishes (`<-`), with the status code and `handled_ms`. The health check is not logged. If the bot waited much longer than `handled_ms`, the delay happened outside the bridge.
- **🧊 Event-loop lag:** new `[youtube-bridge-lag]` lines appear when the whole bridge process was frozen for more than one second, which would delay every request even though no single step looks slow.
- **⏳ Stall lines:** `[youtube-bridge-stall]` lines show which request hung, which attempt it was and whether it will be repeated.

### ✅ Tests
- Checked locally with a stand-in for YouTube.js (not part of the repository): timestamps and the request lines appear, and the lag line appears when the process is blocked for about 1.5 s. The 9 bridge unit tests still pass.

### 📁 Files Changed
- `youtube_bridge/server.mjs`, `CHANGELOG.md`.

---

## 🪟 Windows Port — Complete Windows Guide (`README_WINDOWS.md`) *(10/10/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 📘 Added: Windows Documentation That Mirrors the Main README
- **📄 New file:** `README_WINDOWS.md` covers requirements, step-by-step installation with `install_windows.bat`, configuration (including JSON path escaping and the command-line options), running the bot and its start-up time, the YouTube bridge and PO-token provider, the full command list, cookies on Windows, supported languages, troubleshooting, FAQ, logs and monitoring, updating every component, and uninstalling.
- **🧭 Logs explained:** the guide describes every bridge log line (`[youtube-bridge-timing]`, `[youtube-bridge-http]`, `[youtube-bridge-stall]`, `[youtube-bridge-lag]`, `POT provider unavailable`) and how to find where a slow command lost its time.
- **📌 Unchanged:** `README.md` is not modified; it keeps describing the Linux and Docker deployment.

### 📁 Files Changed
- `README_WINDOWS.md` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — "Trial expired" Window Closes Itself *(10/11/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### ✨ Added: Automatic OK for the TeamTalk SDK Trial Message Box
- **🔎 Why:** the trial build of `TeamTalk5.dll` shows a modal Windows message box titled "Trial expired" and blocks the bot until OK is pressed, so every start and every `rs` restart needed a manual click.
- **🖱️ How:** the new `bot/tt_trial_dialog.py` starts a small background thread at the very top of `bot/__init__.py` (before `TeamTalk5.dll` is loaded). It looks for a message box with that title **that belongs to the bot's own process** and presses its OK button, just like a user would; if the box is still open after a few tries it is closed instead. Boxes of other programs or of other bots are never touched.
- **📌 Unchanged:** the SDK is not patched and its trial/licence state is not changed. Each bot process starts its own watcher, so `rs` (which starts a fresh process on Windows) is covered too.
- **🪟 Platforms:** active on Windows only; on Linux it does nothing.
- **⚙️ Switch off:** set the environment variable `TTMEDIABOT_KEEP_SDK_DIALOG=1` to keep the message box.
- **📝 Log:** one `INFO` line, "TeamTalk SDK 'Trial expired' window closed automatically", is written when it fires.

### 📁 Files Changed
- `bot/tt_trial_dialog.py` (new), `bot/__init__.py`, `CHANGELOG.md`.

---

## 🪟 Windows Port — Fade-Out When Stopping With `s` *(10/11/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### ✨ Added: `s` Lowers the Volume Slowly, Then Stops
- **🎚️ What you hear:** when a track is playing, `s` no longer cuts the sound. The volume falls to silence over `player.fade_out_duration` seconds (default `3.0`), then playback stops. The channel message "<nickname> stopped playback" is sent right away, so nobody waits for it.
- **📉 An even fade:** the level falls in a straight line on the dB scale (48 dB over the whole fade). Hearing is roughly logarithmic, so this sounds like a steady fade; a straight ramp of the amplitude seems to drop early and then linger.
- **🔒 Your volume is not touched:** the fade is a separate gain factor inside the FFmpeg engine, applied per 20 ms frame with no clicks. `v` still shows the same value afterwards, and the next track starts at full level.
- **🎛️ On and off:** new admin command `fo`. `fo` switches the fade-out on or off, `fo on` / `fo off` set it, and `fo 5` sets a length of 5 seconds (0.5 to 15) and turns it on. It is kept until the bot stops; `sc` saves it. The same two options exist in `config.json`: `player.fade_out_on_stop` and `player.fade_out_duration`.
- **🖐️ Interrupting the fade:** `s` again during the fade stops at once. `p` with a query, `u`, `n`, `b`, `c` or a seek during the fade cancels the stop and the new playback is heard at full level. A track that ends by itself during the fade does not start the next one. Paused playback is stopped without a fade.
- **📌 Unchanged:** `player.volume_fading` (the stepwise change made by `v`) and every other place that stops playback (the end of the playlist, the auto-return after `jc`, closing the bot) still stop at once.

### ✅ Tests
- New `test_fade_out.py`: the curve (straight in dB, silent at the end, stays silent), the engine with real FFmpeg (the level falls step by step, new playback or a stop ends the fade, a track that ends during it, paused or idle playback, full level afterwards) and the `Player` rules. The 13 existing engine tests still pass.

### 📁 Files Changed
- `bot/player/ffmpeg_engine.py`, `bot/player/__init__.py`, `bot/config/models.py`, `bot/commands/user_commands.py`, `bot/commands/admin_commands.py`, `bot/commands/__init__.py`, `config_default.json`, `README.md`, `README_WINDOWS.md`, `test_fade_out.py` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — Version 4.1: Update Notices From GitHub and `install` *(10/11/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 🏷️ Changed: The Bot Is Now Version 4.1
- `app_version` in `bot/app_vars.py` is `4.1`, so the TeamTalk client name (`TTMediaBot-V4.1`) and the `a` command show it.

### ✨ Added: The Bot Watches Your GitHub Repository
- **🔔 Notice in the channel:** every `updater.check_interval_minutes` minutes (default `60`, minimum `1`) the bot asks GitHub for the newest commit of the branch it runs on. When there is a new one, it posts a short notice in the TeamTalk channel: installed and available version (when the version number changed), the latest change with its author and time, how many changes the update contains, and how to install it. Each new commit is announced once; a bot that was offline announces at its next check.
- **⬇️ `install` (admin):** checks again, runs `git pull --ff-only`, tells the channel that it is restarting, restarts, and says "Update completed successfully! I am back online." when it is back (the same messages `update.sh` uses). It answers "TTMediaBot is up to date" when there is nothing to install.
- **🧪 Cheap and safe:** the check is `git ls-remote`, which downloads nothing and has no rate limit; `git fetch` only runs when the newest commit is new. Every git call has a time limit and can never ask for a password (no terminal prompt, no Git Credential Manager window, no ssh prompt), so a bad network or credential cannot freeze the bot. Credentials inside a remote URL are removed from messages and the log.
- **🛟 What it will not do:** it never overwrites files you edited by hand (`--ff-only`), never updates a copy that has commits that are not on GitHub, and never updates a folder that is not its own Git clone. It answers with the reason and changes nothing. When an update changes `requirements.txt`, the update is installed but the bot does not restart into missing packages: it asks you to run `pip install -r requirements.txt` and send `rs`.
- **⚙️ Settings:** new `updater` section in `config.json`: `enabled` (`true`), `check_interval_minutes` (`60`), `remote` (`"origin"`). With `enabled` set to `false` only the background checks stop; `install` still works.
- **📝 Log:** `[Updater]` lines for announcements, installations and the first occurrence of each problem.

### ✅ Tests
- New `test_updater.py` uses real Git: a bare "GitHub" repository, a developer clone and the bot folder. It covers an unchanged repository, one or several new commits, the new version number, one fetch per new commit, changed requirements, installing, local commits that are not on GitHub, a diverged copy, hand edits that clash, a folder that is not a clone or not the repository root, an unreachable remote, credentials in URLs, one announcement per update, an offline bot, and the `install` command (restart, no restart, errors, two installations at once).

### 📁 Files Changed
- `bot/updater.py` (new), `bot/__init__.py`, `bot/app_vars.py`, `bot/config/models.py`, `bot/commands/admin_commands.py`, `bot/commands/__init__.py`, `config_default.json`, `README.md`, `README_WINDOWS.md`, `test_updater.py` (new), `CHANGELOG.md`.

---

## 🪟 Windows Port — Refused Commands Are Logged, `ajc` Can No Longer Hang *(10/11/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 🔎 Fixed: A Command the Bot Refused Left No Trace in the Log
- **🔎 Why:** the log of a user typing `jn` showed "Executing command 'jn'" and then nothing. `jn` is not a command (the join command is `jc`; `ajc` for admins), and the reply to a refused or unknown command was never logged, so the log looked as if the command had hung.
- **📝 Now:** `Command 'x' from user NAME was refused: <reason>` (for example "You are not in bot's channel") and `Unknown command in message '...' from user NAME` are written at `INFO` level.

### 🛠️ Fixed: `ajc` Waited Forever for the Server
- **🔎 Why:** the admin join command looped until the server confirmed the join, with no exit. A lost confirmation left its thread spinning and the administrator without any reply.
- **✅ Now:** it waits at most 10 seconds and always answers: "Joined the channel", the server's error, or "No confirmation from the server, the bot may not have joined the channel" (also logged as a warning). The error text is now translated before it is filled in.

### 📁 Files Changed
- `bot/commands/__init__.py`, `bot/commands/admin_commands.py`, `CHANGELOG.md`.

---

## 🪟 Windows Port — Version 4.1.2: Gemini AI, Config Updates That Keep Your Settings, Packages Installed During the Restart, a Reviewed Indonesian Translation, Tests in One Folder *(10/13/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

### 🤖 New: Ask Gemini From TeamTalk (`ai` and `chat`)
- **💬 `ai QUESTION`:** one question, one answer, nothing remembered (for example `ai bagaimana cuaca di blora saat ini`). **`chat`** starts a conversation: everything the user sends is then a message to the AI, `/clear` forgets the conversation and starts a new topic, `/c` ends the chat (`chat QUESTION` starts a chat and asks at once). A chat also ends by itself after `chat_idle_minutes` without a message, and when the user leaves the bot's channel.
- **🔎 Grounding with Google Search:** answers use the `google_search` tool, so weather, news and results are current. The websites an answer was found on are named at its end (`show_sources`).
- **📦 Official SDK:** the new `google-genai` library (`google-genai>=2.16.0,<3` in `requirements.txt`, Python 3.10 or newer), through Google's Interactions API, the one Google's documentation now recommends. A single question is sent with `store=False`; a chat continues with `previous_interaction_id`. A conversation that has expired on Google's side is replaced by a new one, and the user is told.
- **🧱 Kept apart from the rest:** the code is in the new `bot/ai/` package (`gemini.py`, `manager.py`, `provider.py`, `text.py`, `errors.py`). The SDK is only imported when the first question arrives, so the bot starts even if the package is missing. Another service is added by writing one class and listing it in `PROVIDERS`; `ai.provider` selects it.
- **📝 Plain text:** Markdown symbols (`**`, `#`, code fences, `*` bullets) are removed from answers, and answers longer than `max_answer_length` are cut at a sentence end.
- **🛡️ Limits and errors:** a cooldown per user, one question at a time per user, a limit of simultaneous questions for the whole bot, a timeout, and retries with a growing pause for busy servers and network failures. Every failure is answered in words: not set up, wrong key, usage limit reached, model not found, no connection, took too long, region not supported.
- **⚙️ Settings:** new `ai` section in `config.json` (`enabled`, `provider`, `cooldown_seconds`, `max_question_length`, `max_answer_length`, `show_sources`, `chat_idle_minutes`, `max_concurrent_requests`) with a `gemini` part (`api_key`, `model`, `google_search`, `thinking_level`, `timeout_seconds`, `max_retries`, `system_instruction`). An empty `api_key` uses `GEMINI_API_KEY` or `GOOGLE_API_KEY`. The command can be blocked with `bc +ai`.

### 🛠️ Fixed: Long Messages Were Sent Empty
- **🔎 Why:** `split()` in `bot/TeamTalk/__init__.py` compared (`==`) instead of assigning, so every word of a line longer than one message was dropped and empty messages were sent. Any answer that is one long paragraph would have disappeared.
- **✅ Now:** a long line is cut on its spaces, a word longer than a message is cut inside the word, lines that fit are kept together, and no empty message is sent.

### 🔄 Improved: `config.json` Is Updated Like an App Keeps Your Settings
- **➕ Only adds:** at every start the bot compares `config.json` with the settings the running version knows and adds what is missing, at any depth, with its default value. Values, lists and extra keys of the user are never changed; nothing is reset.
- **💾 Safe:** the file is copied to `config.json.bak` before it is changed, it is written only when something was added, and a file that cannot be written does not stop the bot (the missing settings take their defaults anyway). A `config_version` that is higher than the bot knows, or invalid, stops the start with a clear message.
- **🔁 For changes that are not "add":** a setting that is renamed or changed gets a small function in `bot/migrators/config_migrator.py` (`migrate_functs`), and `CONFIG_VERSION` in `bot/config/models.py` is raised. Version 2 is this release. The missing `config_version` is no longer lost (the old code computed it and discarded it), and the circular import between the config and the migrator is gone.
- **📣 Reported:** a `[Config]` log line, and the channel is told how many settings were added after the restart.

### 🔄 Improved: The Restart After an Update Behaves Like an App or OS Update
- **📦 Packages are installed during the restart:** when an update changes `requirements.txt`, `install` now restarts the bot, and `tools/apply_update.py` runs `pip install -r requirements.txt` first thing in the new process, before the bot loads any package (on Windows a loaded package cannot be replaced). Before, the bot installed the update but did not restart and an administrator had to run pip. A failure (no internet, for instance) never stops the bot: it starts, tells the channel what went wrong and how to do it by hand, and the step is never repeated by itself.
- **📣 "What changed" message:** after the restart the bot says "TTMediaBot was updated from version X to version Y", and how many new settings were added to the configuration. The `update_success` file now carries the version that was running (the old text `ok` is still understood).
- **ℹ️** The very first jump from 4.1 to 4.1.2 is installed by the old code, which still asks for `pip install -r requirements.txt` and `rs` by hand (the new package `google-genai` is needed). From 4.1.2 on the update takes care of it.

### 🌍 Improved: Indonesian Translation (`id`)
- **📖 Rewritten as a whole,** with the wording of Android and One UI instead of word by word. One glossary is used everywhere: *saluran* (channel), *lagu* (track), *daftar putar* (playlist), *antrean* (queue), *tautan* (link), *unduh/unggah* (download/upload), *pasang* (install), *mulai ulang* (restart), *diblokir* (banned/blocked), *pengguna tamu* (guest). "Query" is now *kata kunci*, "event" is *peristiwa*, "voice transmission" is *transmisi suara*, "You are banned" no longer says *dilarang* (forbidden).
- **🐞 Defects removed:** the `GENDER` help text was two texts glued together, "aktifasi" and "fertikal" were misspelled, "Tampa" and "Bahasa ubah bahasa bot" were wrong, the translation of the mode list used `{mode}` instead of `{modes}` (the command failed with an error), and one entry was marked fuzzy and so was never used. All 244 messages are now translated, including the update, fade-out and AI messages.
- **🇭🇺 Hungarian:** "Playing {}" and "Unknown service.\n{}" had lost the `{}` and hid the track name and the service list; restored.
- **🔒 Guard:** `tests/test_locales.py` fails when a translation changes the placeholders of its source, when a `.mo` is older than its `.po`, or when Indonesian has an untranslated or fuzzy message. The other languages keep their translations; the new messages appear in English there until they are translated.

### 🧪 Tests: One Folder
- **📁 Moved:** all `test_*.py` files left the root of the repository and are in `tests/` (with the existing `tests/deployment/`). Two of them found the repository by their own location and were adjusted. Run them with `python -m unittest discover -s tests -t . -v`, or one file with `python -m unittest tests.test_updater -v`.
- **🧩 `test_updater.py`:** adapted to the new behavior (packages installed during the restart; the marker names the running version) and no longer depends on the version number written in the code.
- **🆕 New:** `test_ai_gemini.py` (requests, grounding sources, retries, timeouts, every error class, a rejected thinking level, a lost conversation; a fake client replaces the SDK), `test_ai_manager.py`, `test_ai_commands.py` (the commands and the routing of messages inside a chat), `test_ai_text.py`, `test_split_message.py`, `test_config_migrator.py`, `test_update_state.py` and `test_locales.py`.

### 🔖 Version
- Raised to **4.1.2** (`bot/app_vars.py`). `README.md` and `README_WINDOWS.md` describe the AI feature, its settings, the config update, the restart-time package installation and the tests; the minimum Python version is now 3.10 (`install_windows.bat`).

### 📁 Files Changed
- **New:** `bot/ai/` (`__init__.py`, `errors.py`, `gemini.py`, `manager.py`, `provider.py`, `text.py`), `bot/migrators/config_merge.py`, `bot/update_state.py`, `tools/apply_update.py`, `tests/__init__.py`, `tests/test_ai_commands.py`, `tests/test_ai_gemini.py`, `tests/test_ai_manager.py`, `tests/test_ai_text.py`, `tests/test_config_migrator.py`, `tests/test_locales.py`, `tests/test_split_message.py`, `tests/test_update_state.py`.
- **Moved to `tests/`:** `test_fade_out.py`, `test_ffmpeg_engine.py`, `test_logger_early_logging.py`, `test_player_http_headers.py`, `test_player_stream_retry.py`, `test_stream_resolvers.py`, `test_track_refresh.py`, `test_update_shared_youtube.py`, `test_updater.py`, `test_youtube_bridge.py`, `test_ytm_service.py`.
- **Changed:** `TTMediaBot.py`, `bot/__init__.py`, `bot/app_vars.py`, `bot/commands/__init__.py`, `bot/commands/user_commands.py`, `bot/commands/admin_commands.py`, `bot/config/__init__.py`, `bot/config/models.py`, `bot/migrators/config_migrator.py`, `bot/TeamTalk/__init__.py`, `bot/updater.py`, `config.json`, `config_default.json`, `requirements.txt`, `.gitignore`, `install_windows.bat`, `README.md`, `README_WINDOWS.md`, `locale/` (`TTMediaBot.pot`, and `.po`/`.mo` of every language), `CHANGELOG.md`.

---

## 🐍 Windows Port — Version 4.2.0: Python 3.15 Support, Python Installed Through winget, Optional PO-Token Provider Step, UTF-8 Everywhere *(10/17/2026)*

> **Maintained by:** nicohilmi — https://github.com/nicohilmi/TTMediaBot-Cross-platform

> A large update: the way the bot is installed and started changes for the new Python, and the SDK download becomes more robust. Python 3.15.0 was released on 9 October 2026. The bot is now optimized for it and still runs on Python 3.10 or newer. No feature was removed and the behavior of the features that already worked is unchanged.

### 🐍 New: Python 3.15
- **✅ Supported:** the bot, the installer and the helper tools run on Python 3.15 and keep running on 3.10, 3.11, 3.12, 3.13 and 3.14. The minimum stays Python 3.10 (`google-genai` and recent `pydantic` need it).
- **📦 Libraries:** `pydantic` (through `pydantic-core`) and `numpy` publish Windows wheels for Python 3.15, so `pip` installs them without a compiler. `requirements.txt` is unchanged and does not pin versions.
- **🔤 UTF-8 by default (PEP 686):** Python 3.15 reads and writes text as UTF-8 when no encoding is given; older versions on Windows used the code page. The bot already names `encoding="utf-8"` for every text file it opens, reads and writes, and for every program it runs; a new test (`tests/test_python_compat.py`) keeps it that way. `TTMediaBot.bat` and `install_windows.bat` also set `PYTHONUTF8=1` (unless you set it yourself), so Python 3.10 to 3.14 behave like 3.15 for song titles and for libraries that open files without naming an encoding.
- **🧩 Removed in 3.15: `load_module()`:** the event handlers (`event_handling`) were loaded with `SourceFileLoader(...).load_module()`, deprecated since Python 3.6 and on the removal list of Python 3.15. They are now loaded with `importlib.util.spec_from_file_location` and `exec_module` (the new `load_python_module()` in `bot/utils.py`), which works on every supported version. A single `.py` file and a folder with `__init__.py` are both loaded, a handler that raises an error does not stay half-loaded in `sys.modules`, and the bot's answer to a broken handler file (an empty module and an error in the log) is the same as before.
- **🧹 pydantic 2 without warnings:** the settings are written with `model_dump()` when the installed `pydantic` has it (the new `dump_model()` in `bot/config/__init__.py`) and with `dict()` on pydantic 1. The result is identical; the deprecation warning of pydantic 2 is gone.
- **⚡ Lazy imports (PEP 810):** `bot/modules/stream_resolvers.py` declares `__lazy_modules__ = ["bs4"]`, so Python 3.15 loads BeautifulSoup only when a web page has to be read. Older versions read the line as a plain list and import it at once, as before. The code never uses the `lazy` keyword, so every file still compiles on Python 3.10.
- **🛡️ Clear message on an old Python:** `TTMediaBot.py` checks the version first. Python 3.9 or older now gets "TTMediaBot needs Python 3.10 or newer (it is optimized for Python 3.15)…" instead of an error deep inside a library.

### 🪟 Changed: `install_windows.bat`
- **🐍 Python:** the installer looks for Python 3.15 first (`py -V:3.15`, `py -3.15`), then for any 64-bit Python 3.10 or newer (`py -3`, `python`). An old Python that works is kept. Before, only the existence of a command was checked, never its version or its bitness.
- **⬇️ Python 3.15 is installed when there is none:** through the Python install manager, the way Python for Windows is delivered now: `winget install 9NQ7512CXL7T --accept-package-agreements` (with `--accept-source-agreements`, so winget does not stop to ask), then `pymanager install --configure -y` and `pymanager install -y 3.15`. The Windows search path is updated only for windows opened afterwards, so when the new Python is not visible yet the installer says "close this window, open a new one and run it again" instead of failing in a confusing way. Without winget it prints the two commands to run by hand. The installer also prints the Python and the `venv` version it uses, and tells you how to move an older `venv` to 3.15.
- **❓ Step 4 asks first:** "Install and start the PO token provider for this bot? [Y/n]" (type the letter, then Enter). **`N` (or `no`) skips step 4 (install) and step 5 (the second window) completely.** One PO-token provider listening on port `4416` is enough for any number of bots on the same computer, so a second bot no longer installs and starts a provider again. When something already answers on port `4416` the installer says so and the default becomes `N` (Enter alone skips); otherwise Enter alone means `Y`. Any other answer is asked again.
- **🤖 Without questions:** `install_windows.bat --pot` installs and starts the provider, `install_windows.bat --no-pot` skips steps 4 and 5.
- **🔧 Fixes inside the script:** a first-run question of the Python launcher can no longer wait invisibly for a key press, and every Python one-liner was checked for batch escape characters that would reach Python.

### 📦 Changed: TeamTalk SDK download, 7-Zip and browser identities (`tools/setup_deps.py`)
- **🌐 Fresh browser identities:** the downloads used one fixed "TTMediaBot-setup" identity, and a `403` from the site ended the download at once. The identities now come from the new `tools/user_agents.txt` (62 current browser identities, one per line, `#` comments allowed; the built-in fallback list is used when the file is missing or empty). One is chosen at random per run; a site that answers `403`, `406` or `429` is asked again at once with the next one (at most 6), and the identity that worked is used first for the rest of the run. `404` and server errors behave as before.
- **🗜️ 7-Zip:** unchanged first: 7-Zip when installed, py7zr, `tar.exe`, then the installation of 7-Zip through the package manager (winget `7zip.7zip` on Windows). New last resort on Windows: when winget is missing or fails, the portable `7zr.exe` (7-Zip's console program for `.7z`, from 7-zip.org with the GitHub release as a second address) is downloaded into the temporary folder and used for the unpacking. It is only used when it is a Windows program of a plausible size that identifies itself as 7-Zip. Nothing is installed by that step.
- **🗂️ Temporary files only:** the `.7z` and the unpacked SDK live in a temporary folder in the user's Windows `Temp` folder and are deleted afterwards (even when a file is still held by antivirus software); only `TeamTalk5.dll` stays in the bot folder, the previous one as `TeamTalk5.dll.bak`. `Library\TeamTalk_DLL` of the SDK holds `TeamTalk5.dll`, `TeamTalk5.lib` and a C header; the documentation names the DLL as the only file needed at run time, so `.lib` and the header are not kept. Any other DLL found in that folder is copied with it.
- **✅ The copy is tested where it will live:** on Windows the DLL is test-loaded again from the bot folder after copying. When it does not load there (for example because a DLL it needs was left in the SDK folder), the previous files are put back, nothing half-installed stays, and the reason and the manual steps are printed.
- **📝 Manual steps with commands:** when the automatic setup cannot finish, the message now lists the exact commands: `7z x -y -o"%TEMP%\ttsdk" tt5sdk_*_win64.7z`, `copy ... TeamTalk5.dll <bot folder>`, `dir /s /b ...` to find the file, and `rmdir /s /q "%TEMP%\ttsdk"`.
- **🪟 `install_windows.bat` step 6** says what will happen with the SDK archive and 7-Zip.

### 📖 Documentation
- `README.md` and `README_WINDOWS.md`: Python 3.15 is the recommended version, the two winget/`py install` commands, the step 4 question and why it exists, `--pot` and `--no-pot`, how to move an existing `venv` to 3.15, the new troubleshooting text for "Python was not found", and the SDK / 7-Zip / `tools\user_agents.txt` description with the manual commands.

### 🧪 Tests
- **🆕 `tests/test_python_compat.py`** (27 tests): every project file parses as Python 3.10 syntax and the `lazy` keyword is not used; no module removed from the standard library is imported and no deprecated or removed call (`load_module`, `utcnow`, `getdefaultlocale`, `glob0`, `SetPointerType`, …) is used; every `open()`, `read_text()`, `write_text()` and text-mode `subprocess` call names its encoding; `__lazy_modules__` is well formed and comes before the imports it makes lazy; `load_python_module()` loads a file, a package, non-ASCII content, a missing file and a broken file; `dump_model()` prefers `model_dump()`; the Python version guard answers Python 3.9 and lets 3.10 to 3.15 pass; `install_windows.bat` and `TTMediaBot.bat` use Windows line endings only, every `goto` and `call` has its label, one-liners have no batch escapes, step 4 is a question whose `N` branch skips steps 4 and 5, and the winget command is the official one; the changelog names the running version.
- **🆕 `tests/test_setup_deps_downloads.py`** (42 tests): the identity list (shipped file, comments, fallback), rotation on `403`/`406`/`429` with a real local HTTP server and with fake openers, the remembered identity, `404`/`5xx` staying final, the portable 7zr.exe (addresses, size and name checks, nothing downloaded on Linux or in check-only runs, package manager first), companion DLLs, the roll-back, the temporary folder being deleted, and the exact manual commands.
- The suite now has 349 tests; run everything with `python -m unittest discover -s tests -t .`.

### 🔖 Version
- Raised to **4.2.0** (`bot/app_vars.py`). `config.json` needs no change: no setting was added, so `CONFIG_VERSION` stays 2.

### 📁 Files Changed
- **New:** `tests/test_python_compat.py`, `tests/test_setup_deps_downloads.py`, `tools/user_agents.txt`.
- **Changed:** `tools/setup_deps.py`, `bot/app_vars.py`, `bot/utils.py`, `bot/TeamTalk/thread.py`, `bot/config/__init__.py`, `bot/modules/stream_resolvers.py`, `TTMediaBot.py`, `TTMediaBot.bat`, `install_windows.bat`, `README.md`, `README_WINDOWS.md`, `README_DEVELOPERS_AI.md`, `CHANGELOG.md`.
