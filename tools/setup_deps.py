#!/usr/bin/env python3
"""Check and install the two programs TTMediaBot needs from outside Python.

* FFmpeg: looked for in the bot folder and on PATH. When it is missing it is
  installed through the system package manager (winget, Chocolatey or Scoop on
  Windows; apt, dnf, yum, pacman, zypper, apk, xbps or emerge on Linux; Homebrew
  on macOS).
* The TeamTalk 5 SDK library (TeamTalk5.dll / libTeamTalk5.so): the newest stable
  release is found on the official BearWare download page, downloaded, unpacked,
  test-loaded and only then copied into place. The download and the unpacked SDK
  live in a temporary folder (on Windows the user's Temp folder) that is deleted
  afterwards. On Windows the bot folder gets a TeamTalk_DLL folder with exactly three
  files of the SDK (TeamTalk5.dll, TeamTalk5.lib, TeamTalk.h), nothing is copied
  beside TTMediaBot.py; on Linux only libTeamTalk5.so goes into TeamTalk_DLL. The .7z archive is opened
  with 7-Zip (installed through winget or, on Windows, a portable 7zr.exe fetched
  from 7-zip.org when nothing else can open it), py7zr or bsdtar.

This file uses the standard library only, so it also runs before the Python
requirements are installed. Every download of a "latest" version is read from the
vendor's page at run time; nothing here pins an old release.

    python tools/setup_deps.py all            # FFmpeg and the SDK
    python tools/setup_deps.py ffmpeg         # only FFmpeg
    python tools/setup_deps.py sdk --force    # fetch the SDK even if one is installed
    python tools/setup_deps.py all --check    # report only, install nothing
    python tools/setup_deps.py sdk --sdk-file tt5sdk_v5.23a_win64.7z
                                              # install the SDK from a .7z you downloaded yourself

The exit code is 0 when everything is in place and 1 when something is missing or
failed; the reason and the manual steps are printed.
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------- constants

# The official download page, with the alternative addresses of the same page.
SDK_PAGES = (
    "https://bearware.dk/?page_id=419",
    "https://www.bearware.dk/?page_id=419",
    "https://bearware.dk/?p=419",
)
# Directory that holds every release; read when the download page cannot be parsed.
SDK_DIRECTORY = "https://www.bearware.dk/teamtalksdk/"
SDK_DOWNLOAD_BASE = "https://www.bearware.dk/teamtalksdk"
# Newest release on the official page when this file was last checked (19 October 2026:
# v5.23a, released 8 April 2026, direct links of the form
# https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z).
# It is only used to probe file names when the page and the directory cannot be read.
LAST_SEEN_VERSION = "5.23a"
SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
# The folder of the bot that holds the SDK on every system: <bot folder>/TeamTalk_DLL
# (TeamTalkPy/TeamTalk5.py adds it to the DLL search path). On Windows it holds exactly
# these three files of the SDK's Library/TeamTalk_DLL folder and nothing else.
SDK_FOLDER = "TeamTalk_DLL"
WINDOWS_SDK_FILES = ("TeamTalk5.dll", "TeamTalk5.lib", "TeamTalk.h")
# What earlier versions of this script left in the bot folder itself, beside TTMediaBot.py.
LEGACY_ROOT_FILES = ("TeamTalk5.dll", "TeamTalk5.dll.bak", "TeamTalk5.dll.new")
MIN_ARCHIVE_BYTES = 1_000_000

# Browser identities the download sites accept, one per line (tools/user_agents.txt).
USER_AGENTS_FILE = Path(__file__).with_name("user_agents.txt")
# Used only when that file is missing or empty.
FALLBACK_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
)
# Answers that mean "the file is not there". Every other 4xx answer (403, 406, 429 and the
# non-standard 454 that a bot filter in front of bearware.dk gave to this script) means
# "this client is not welcome" and is answered with another identity and another program.
NOT_FOUND_STATUS = (404, 410)
MAX_AGENT_TRIES = 6
# Pause between two identities, so a filter that counts requests is not hammered.
REFUSAL_PAUSE = 0.5
# When Python itself is refused, curl (curl.exe ships with Windows 10 since 1803) and
# Windows PowerShell are asked to fetch the same URL: they look different to a filter
# (another TLS and HTTP fingerprint) and they use the system's own certificate store.
EXTERNAL_AGENT_TRIES = 3
EXTERNAL_PAGE_TIMEOUT = 60.0
EXTERNAL_DOWNLOAD_TIMEOUT = 900.0

# 7-Zip's own console program for .7z files (the "7zr.exe" of the 7-Zip download page).
# It is fetched only on Windows, only when nothing else can open the archive, and only
# into the temporary folder.
SEVEN_ZIP_PORTABLE_URLS = (
    "https://www.7-zip.org/a/7zr.exe",
    "https://d.7-zip.org/a/7zr.exe",
    "https://github.com/ip7z/7zip/releases/latest/download/7zr.exe",
)
PORTABLE_MIN_BYTES = 100_000
PORTABLE_MAX_BYTES = 8_000_000

IS_WINDOWS = os.name == "nt"

_ASSET_RE = re.compile(
    r"https?://(?:www\.)?bearware\.dk/teamtalksdk/v(?P<ver>\d+\.\d+[a-z]?)/"
    r"(?P<file>(?P<kind>tt5(?:pro)?sdk)_v(?P=ver)_(?P<tag>[a-z0-9_]+?)\.7z)",
    re.IGNORECASE,
)
_DIR_VERSION_RE = re.compile(r'href="(?:[^"]*/)?v(\d+\.\d+[a-z]?)/?"', re.IGNORECASE)
_DIR_FILE_RE = re.compile(
    r'href="(?:[^"]*/)?(tt5(?:pro)?sdk)_v(\d+\.\d+[a-z]?)_([a-z0-9_]+?)\.7z"', re.IGNORECASE
)
_VERSION_NUMBERS_RE = re.compile(r"(\d+)\.(\d+)")


def say(message: str = "") -> None:
    print(message, flush=True)


# ------------------------------------------------------------ small helpers


class SetupError(Exception):
    """A step failed; the message is meant for the person running the installer."""


def run_quiet(command: Sequence[str], timeout: float = 20.0) -> Tuple[int, str]:
    """Run a command, return (exit code, combined output). Never raises on failure."""
    try:
        result = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)
    return result.returncode, result.stdout or ""


def run_visible(command: Sequence[str], timeout: float = 1800.0) -> bool:
    """Run a command with its output shown, True when it exits with 0."""
    say("    $ " + " ".join(command))
    try:
        return subprocess.run(list(command), timeout=timeout, stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError) as error:
        say(f"    (could not run it: {error})")
        return False


def with_privileges(command: List[str]) -> Optional[List[str]]:
    """Put sudo in front of a Linux command when it is needed and available."""
    if IS_WINDOWS or not hasattr(os, "geteuid") or os.geteuid() == 0:
        return command
    if shutil.which("sudo"):
        return ["sudo"] + command
    return None


# ------------------------------------------------------------------- FFmpeg


def ffmpeg_works(path: str) -> bool:
    code, _ = run_quiet([path, "-hide_banner", "-version"], timeout=15)
    return code == 0


def windows_ffmpeg_locations() -> List[str]:
    """Where package managers put ffmpeg.exe, for the window that was open before the install."""
    found: List[str] = []
    local = os.environ.get("LOCALAPPDATA", "")
    program_data = os.environ.get("ProgramData", "")
    home = os.path.expanduser("~")
    if local:
        found.append(os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"))
        found += sorted(
            glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"), recursive=True)
        )
    program_files = os.environ.get("ProgramFiles", "")
    if program_files:
        found += sorted(
            glob.glob(os.path.join(program_files, "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"), recursive=True)
        )
    if program_data:
        found.append(os.path.join(program_data, "chocolatey", "bin", "ffmpeg.exe"))
    found.append(os.path.join(home, "scoop", "shims", "ffmpeg.exe"))
    return found


def find_ffmpeg(bot_dir: Path) -> Optional[Tuple[str, bool]]:
    """Return (path, reachable_through_PATH) of a working ffmpeg, or None."""
    name = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"
    local = bot_dir / name
    if local.is_file() and ffmpeg_works(str(local)):
        return str(local), True
    on_path = shutil.which("ffmpeg")
    if on_path and ffmpeg_works(on_path):
        return on_path, True
    if IS_WINDOWS:
        for candidate in windows_ffmpeg_locations():
            if os.path.isfile(candidate) and ffmpeg_works(candidate):
                return candidate, False
    return None


Plan = Tuple[str, List[List[str]]]


def detect_linux_manager(which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    for manager in ("apt-get", "dnf", "yum", "pacman", "zypper", "apk", "xbps-install", "emerge"):
        if which(manager):
            return manager
    return None


def ffmpeg_install_plans(
    system: str, which: Callable[[str], Optional[str]] = shutil.which
) -> List[Plan]:
    """Ordered install attempts as (label, [commands]); the first that works wins."""
    plans: List[Plan] = []
    if system == "windows":
        if which("winget"):
            plans.append(
                (
                    "Windows Package Manager (winget)",
                    [["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent",
                      "--accept-package-agreements", "--accept-source-agreements"]],
                )
            )
        if which("choco"):
            plans.append(("Chocolatey", [["choco", "install", "ffmpeg", "-y"]]))
        if which("scoop"):
            plans.append(("Scoop", [["scoop", "install", "ffmpeg"]]))
        return plans
    if system == "darwin":
        if which("brew"):
            plans.append(("Homebrew", [["brew", "install", "ffmpeg"]]))
        return plans

    manager = detect_linux_manager(which)
    commands: Dict[str, List[Plan]] = {
        "apt-get": [("APT", [["apt-get", "update"], ["apt-get", "install", "-y", "ffmpeg"]])],
        # Fedora ships "ffmpeg-free" itself; the full "ffmpeg" comes from RPM Fusion.
        "dnf": [
            ("dnf", [["dnf", "install", "-y", "ffmpeg"]]),
            ("dnf (ffmpeg-free)", [["dnf", "install", "-y", "ffmpeg-free"]]),
        ],
        "yum": [("yum", [["yum", "install", "-y", "ffmpeg"]])],
        "pacman": [("pacman", [["pacman", "-S", "--noconfirm", "--needed", "ffmpeg"]])],
        "zypper": [("zypper", [["zypper", "--non-interactive", "install", "ffmpeg"]])],
        "apk": [("apk", [["apk", "add", "ffmpeg"]])],
        "xbps-install": [("xbps", [["xbps-install", "-Sy", "ffmpeg"]])],
        "emerge": [("Portage", [["emerge", "--ask=n", "media-video/ffmpeg"]])],
    }
    for label, plan_commands in commands.get(manager or "", []):
        plans.append((label, plan_commands))
    if which("brew"):  # Linuxbrew as a last resort
        plans.append(("Homebrew", [["brew", "install", "ffmpeg"]]))
    return plans


def ffmpeg_manual_help(system: str) -> str:
    if system == "windows":
        return (
            "Install FFmpeg yourself, then run this again:\n"
            "  winget install --id Gyan.FFmpeg -e\n"
            "or download a build from https://www.gyan.dev/ffmpeg/builds/ and copy ffmpeg.exe\n"
            "into the bot folder, right beside TTMediaBot.py."
        )
    return (
        "Install FFmpeg with your package manager, then run this again, for example:\n"
        "  Debian/Ubuntu: sudo apt-get install ffmpeg\n"
        "  Fedora:        sudo dnf install ffmpeg-free   (full ffmpeg needs RPM Fusion)\n"
        "  RHEL/Alma:     enable EPEL and RPM Fusion first, then sudo dnf install ffmpeg\n"
        "  Arch:          sudo pacman -S ffmpeg\n"
        "  openSUSE:      sudo zypper install ffmpeg   (the full build is in the Packman repository)\n"
        "  Alpine:        sudo apk add ffmpeg"
    )


def setup_ffmpeg(bot_dir: Path, system: str, check_only: bool = False) -> bool:
    say("== FFmpeg ==")
    found = find_ffmpeg(bot_dir)
    if found:
        path, on_path = found
        say(f"  FFmpeg found: {path}")
        if not on_path:
            say(
                "  It is not on PATH in this window yet. Open a new terminal, or put the full path\n"
                '  in config.json under "player" -> "ffmpeg_path".'
            )
        return True
    say("  FFmpeg was not found.")
    if check_only:
        say(ffmpeg_manual_help(system))
        return False
    plans = ffmpeg_install_plans(system)
    if not plans:
        say("  No supported package manager was found.")
        say(ffmpeg_manual_help(system))
        return False
    for label, commands in plans:
        say(f"  Trying {label} ...")
        for index, command in enumerate(commands):
            if system == "linux":
                command = with_privileges(command)
                if command is None:
                    say("  This needs administrator rights and sudo is not installed. Run this as root.")
                    break
            ok = run_visible(command)
            # "apt-get update" may fail on a stale mirror; the install can still work.
            if not ok and index == len(commands) - 1:
                break
        found = find_ffmpeg(bot_dir)
        if found:
            path, on_path = found
            say(f"  FFmpeg installed: {path}")
            if not on_path:
                say("  Open a new terminal so PATH is refreshed, or set player.ffmpeg_path in config.json.")
            return True
    say("  Installing FFmpeg did not work.")
    say(ffmpeg_manual_help(system))
    return False


# ------------------------------------------------------------------- SDK page


@dataclass(frozen=True)
class SdkAsset:
    version: str  # e.g. "5.23a"
    edition: str  # "standard" or "professional"
    tag: str  # e.g. "win64", "ubuntu26_x86_64"
    url: str


def version_key(version: str) -> Tuple[int, int, str]:
    match = re.match(r"(\d+)\.(\d+)([a-z]?)", version, re.IGNORECASE)
    if not match:
        return (0, 0, "")
    return (int(match.group(1)), int(match.group(2)), match.group(3).lower())


def parse_assets(text: str) -> List[SdkAsset]:
    """All SDK archives named in a page of the official site."""
    seen: Dict[str, SdkAsset] = {}
    for raw in _ASSET_RE.finditer(html.unescape(text)):
        kind = raw.group("kind").lower()
        asset = SdkAsset(
            version=raw.group("ver").lower(),
            edition="professional" if kind == "tt5prosdk" else "standard",
            tag=raw.group("tag").lower(),
            url="https://www.bearware.dk/teamtalksdk/v{}/{}".format(raw.group("ver"), raw.group("file")),
        )
        seen.setdefault(asset.url.lower(), asset)
    return list(seen.values())


def parse_directory(listing: str, version: str) -> List[SdkAsset]:
    assets = []
    for kind, ver, tag in _DIR_FILE_RE.findall(html.unescape(listing)):
        file_name = f"{kind}_v{ver}_{tag}.7z"
        assets.append(
            SdkAsset(
                version=ver.lower(),
                edition="professional" if kind.lower() == "tt5prosdk" else "standard",
                tag=tag.lower(),
                url=f"{SDK_DOWNLOAD_BASE}/v{version}/{file_name}",
            )
        )
    return assets


def tag_matches(tag: str, system: str, machine: str) -> bool:
    machine = machine.lower()
    if system == "windows":
        return tag == "win64" and machine in ("amd64", "x86_64", "x64")
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return re.fullmatch(r"ubuntu\d+_x86_64", tag) is not None
        if machine in ("aarch64", "arm64"):
            return tag == "raspbian_arm64"
        return False
    if system == "darwin":
        return tag == "macos_universal"
    return False


def _tag_rank(tag: str) -> int:
    match = re.match(r"ubuntu(\d+)", tag)
    return int(match.group(1)) if match else 0


def choose_asset(assets: Sequence[SdkAsset], system: str, machine: str) -> Optional[SdkAsset]:
    """Newest Standard Edition archive for this system (the bot does not need Professional)."""
    fitting = [a for a in assets if a.edition == "standard" and tag_matches(a.tag, system, machine)]
    if not fitting:
        return None
    return max(fitting, key=lambda a: (version_key(a.version), _tag_rank(a.tag)))


Fetcher = Callable[[str], bytes]


def load_user_agents(path: Path = USER_AGENTS_FILE) -> List[str]:
    """The browser identities in a text file: one per line, blank lines and # comments skipped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    agents: List[str] = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and line not in agents:
            agents.append(line)
    return agents or list(FALLBACK_USER_AGENTS)


class _AgentPool:
    """The identities of this run, shuffled once, and the one that worked last."""

    def __init__(self) -> None:
        self.agents: List[str] = []
        self.index = 0


_POOL = _AgentPool()


def user_agent_pool() -> _AgentPool:
    if not _POOL.agents:
        _POOL.agents = load_user_agents()
        random.shuffle(_POOL.agents)
        _POOL.index = 0
    return _POOL


def reset_user_agents() -> None:
    """Forget the pool; the next request reads the file and shuffles again."""
    _POOL.agents = []
    _POOL.index = 0


def is_refusal(code: int) -> bool:
    """True for a 4xx answer that says "not you" and not "not here"."""
    return 400 <= code < 500 and code not in NOT_FOUND_STATUS


def is_missing(error: Optional[BaseException]) -> bool:
    """True when the server said that the file is not there (nothing else can help then)."""
    return isinstance(error, urllib.error.HTTPError) and error.code in NOT_FOUND_STATUS


def request_headers(agent: str, referer: Optional[str] = None) -> Dict[str, str]:
    headers = {"User-Agent": agent, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    return headers


def open_url(
    url: str,
    opener: Callable[..., object] = urllib.request.urlopen,
    timeout: float = 30.0,
    method: str = "GET",
    referer: Optional[str] = None,
    sleep: Callable[[float], None] = time.sleep,
):
    """Open a URL the way a browser would.

    A site that turns a browser identity away (any 4xx answer except 404 and 410: 403,
    406, 429, the non-standard 454 ...) is asked again with the next identity of the
    pool; the one that worked is used first from then on. Any other error, including
    404 and 5xx, is raised as it is.
    """
    pool = user_agent_pool()
    tries = min(len(pool.agents), MAX_AGENT_TRIES)
    last: Optional[urllib.error.HTTPError] = None
    for step in range(tries):
        index = (pool.index + step) % len(pool.agents)
        request = urllib.request.Request(
            url, headers=request_headers(pool.agents[index], referer), method=method
        )
        try:
            response = opener(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if not is_refusal(error.code):
                raise
            last = error
            try:
                error.close()  # the answer is not needed; do not leave its connection open
            except (OSError, AttributeError):
                pass
            if step + 1 < tries:
                sleep(REFUSAL_PAUSE)
            continue
        pool.index = index
        return response
    assert last is not None
    raise last


def temporary_directory(prefix: str) -> "tempfile.TemporaryDirectory[str]":
    """A temporary folder (on Windows inside the user's Temp folder) that is removed afterwards.

    A file that antivirus software still holds when the folder is removed must not make
    the setup fail; Python 3.10 can be told to ignore that, older versions cannot.
    """
    if sys.version_info >= (3, 10):
        return tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True)
    return tempfile.TemporaryDirectory(prefix=prefix)


# ------------------------------------------------- other programs as a second chance

POWERSHELL_FETCH = """param([string]$Uri, [string]$Destination, [string]$Identity, [int]$Seconds = 600)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
try {
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination -UserAgent $Identity -MaximumRedirection 8 -TimeoutSec $Seconds
    Write-Output 'HTTP 200'
} catch {
    $code = 0
    try { if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode } } catch {}
    Write-Output ('HTTP ' + $code + ' ' + $_.Exception.Message)
    exit 2
}
"""
_STATUS_RE = re.compile(r"HTTP (\d{3})")


@dataclass(frozen=True)
class ExternalClient:
    name: str  # "curl" or "powershell"
    path: str


def external_clients(which: Callable[[str], Optional[str]] = shutil.which) -> List[ExternalClient]:
    """The programs on this computer that can fetch a URL, other than Python."""
    found: List[ExternalClient] = []
    if IS_WINDOWS:
        root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
        system32 = Path(root) / "System32"
        curl = system32 / "curl.exe"
        curl_path = str(curl) if curl.is_file() else (which("curl.exe") or which("curl"))
        if curl_path:
            found.append(ExternalClient("curl", curl_path))
        powershell = system32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        powershell_path = (
            str(powershell)
            if powershell.is_file()
            else (which("powershell.exe") or which("powershell") or which("pwsh"))
        )
        if powershell_path:
            found.append(ExternalClient("powershell", powershell_path))
    else:
        curl_path = which("curl")
        if curl_path:
            found.append(ExternalClient("curl", curl_path))
    return found


def external_command(
    client: ExternalClient,
    url: str,
    target: Path,
    agent: str,
    referer: Optional[str],
    timeout: float,
    no_revoke: bool = False,
    script: Optional[Path] = None,
) -> List[str]:
    """The command line (never a shell string) that saves ``url`` as ``target``."""
    seconds = str(int(timeout))
    if client.name == "powershell":
        assert script is not None
        return [
            client.path, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-Uri", url, "-Destination", str(target),
            "-Identity", agent, "-Seconds", seconds,
        ]
    command = [
        client.path, "--location", "--silent", "--show-error",
        "--connect-timeout", "30", "--max-time", seconds,
        "--user-agent", agent, "--header", "Accept: */*",
    ]
    if referer:
        command += ["--referer", referer]
    if no_revoke:
        # Windows' curl asks the certificate's revocation server; some networks and
        # antivirus programs block that question. The certificate chain is still checked.
        command.append("--ssl-no-revoke")
    return command + ["--output", str(target), "--write-out", "HTTP %{http_code}", url]


def run_external_fetch(
    client: ExternalClient,
    url: str,
    target: Path,
    agent: str,
    referer: Optional[str],
    timeout: float,
    run: Callable[[Sequence[str], float], Tuple[int, str]] = run_quiet,
) -> Tuple[Optional[str], Optional[int]]:
    """Fetch with an outside program. Returns (problem or None, HTTP status when known)."""
    script: Optional[Path] = None
    if client.name == "powershell":
        script = target.parent / "ttbot_fetch.ps1"
        script.write_text(POWERSHELL_FETCH, encoding="ascii")
    retry_without_revocation = client.name == "curl" and IS_WINDOWS
    status: Optional[int] = None
    output = ""
    code = 1
    for no_revoke in (False, True):
        if target.exists():
            target.unlink()
        command = external_command(client, url, target, agent, referer, timeout, no_revoke, script)
        code, output = run(command, timeout + 60)
        statuses = _STATUS_RE.findall(output)
        status = int(statuses[-1]) if statuses else None
        if code == 0 and status in (None, 200) and target.is_file() and target.stat().st_size > 0:
            return None, 200
        revocation = "revocation" in output.lower() or "0x80092012" in output
        if no_revoke or not (retry_without_revocation and revocation):
            break
    if status not in (None, 200):
        return f"{client.name}: HTTP {status}", status
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    detail = lines[-1][:200] if lines else f"exit code {code}"
    return f"{client.name}: {detail}", status


def fetch_external(
    url: str,
    target: Path,
    referer: Optional[str] = None,
    timeout: float = EXTERNAL_PAGE_TIMEOUT,
    clients: Optional[Sequence[ExternalClient]] = None,
    run: Callable[[Sequence[str], float], Tuple[int, str]] = run_quiet,
) -> List[str]:
    """Save ``url`` as ``target`` with curl or PowerShell. [] means it worked; otherwise
    one short problem per attempt."""
    available = list(external_clients() if clients is None else clients)
    if not available:
        return ["no curl or PowerShell was found to try instead of Python"]
    pool = user_agent_pool()
    problems: List[str] = []
    for client in available:
        for step in range(EXTERNAL_AGENT_TRIES):
            agent = pool.agents[(pool.index + step) % len(pool.agents)]
            problem, status = run_external_fetch(client, url, target, agent, referer, timeout, run)
            if problem is None:
                return []
            problems.append(problem)
            if status is None or not is_refusal(status):
                break  # only a refusal is worth asking again with another identity
            time.sleep(REFUSAL_PAUSE)
    return problems


def external_get(
    url: str,
    referer: Optional[str] = None,
    timeout: float = EXTERNAL_PAGE_TIMEOUT,
) -> Tuple[Optional[bytes], List[str]]:
    with temporary_directory("ttfetch_") as work:
        target = Path(work) / "page.bin"
        problems = fetch_external(url, target, referer, timeout)
        if problems:
            return None, problems
        return target.read_bytes(), []


def http_get(
    url: str,
    timeout: float = 30.0,
    retries: int = 3,
    opener: Callable[..., object] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    method: str = "GET",
    referer: Optional[str] = None,
    external: Optional[bool] = None,
) -> bytes:
    """Fetch a URL with retries.

    A 4xx answer ends the retries of Python (asking again would not change it) and so
    does 404. Network errors and 5xx are retried. When Python is refused or cannot connect,
    curl and PowerShell get one go at it (``external``: None means "only with the real
    urlopen"); a file that is simply not there (404) is not asked for again.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            with open_url(url, opener, timeout, method, referer) as response:  # type: ignore[attr-defined]
                return response.read()
        except urllib.error.HTTPError as error:
            last_error = error
            if 400 <= error.code < 500:
                break
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            last_error = error
        if attempt < retries:
            sleep(2.0 * attempt)
    problems = [str(last_error)]
    use_external = (opener is urllib.request.urlopen and method == "GET") if external is None else external
    if use_external and not is_missing(last_error):
        data, more = external_get(url, referer, max(timeout, EXTERNAL_PAGE_TIMEOUT))
        if data is not None:
            return data
        problems += more
    raise SetupError(f"could not read {url}: " + "; ".join(problems))


def _single_try(fetch: Fetcher) -> Fetcher:
    """The real fetcher without retries and without the outside programs (the first
    address already had them); an injected one (tests) is used as it is."""
    if fetch is http_get:
        return lambda url: http_get(url, retries=1, external=False)
    return fetch


def discover_assets(fetch: Fetcher = http_get) -> Tuple[List[SdkAsset], List[str]]:
    """Find the SDK archives on the official site. Returns (assets, notes about what failed)."""
    notes: List[str] = []
    for position, page in enumerate(SDK_PAGES):
        # Only the first address gets the full retry treatment; when the site is
        # unreachable the other addresses fail fast instead of adding minutes.
        try:
            reader = fetch if position == 0 else _single_try(fetch)
            assets = parse_assets(reader(page).decode("utf-8", errors="replace"))
        except SetupError as error:
            notes.append(str(error))
            continue
        if assets:
            return assets, notes
        notes.append(f"{page} has no SDK links (the page layout may have changed)")
    fetch = _single_try(fetch)
    try:
        listing = fetch(SDK_DIRECTORY).decode("utf-8", errors="replace")
        versions = sorted(set(_DIR_VERSION_RE.findall(listing)), key=version_key, reverse=True)
        collected: List[SdkAsset] = []
        for version in versions[:3]:
            try:
                page = fetch(f"{SDK_DOWNLOAD_BASE}/v{version}/").decode("utf-8", errors="replace")
            except SetupError as error:
                notes.append(str(error))
                continue
            collected += parse_directory(page, version)
        if collected:
            return collected, notes
        notes.append(f"{SDK_DIRECTORY} could not be listed")
    except SetupError as error:
        notes.append(str(error))
    return [], notes


def known_asset(system: str, machine: str) -> Optional[SdkAsset]:
    """Last resort when the page cannot be read: the file of the newest release this script
    has seen on the official site. No request is made here (a HEAD request is often
    refused by the filters that refuse scripts); the download itself finds out whether the
    file is still there."""
    tags: Sequence[str]
    if system == "windows" and machine.lower() in ("amd64", "x86_64", "x64"):
        tags = ("win64",)
    elif system == "linux" and machine.lower() in ("x86_64", "amd64"):
        tags = ("ubuntu26_x86_64", "ubuntu24_x86_64", "ubuntu22_x86_64")
    elif system == "linux" and machine.lower() in ("aarch64", "arm64"):
        tags = ("raspbian_arm64",)
    elif system == "darwin":
        tags = ("macos_universal",)
    else:
        return None
    tag = tags[0]
    url = f"{SDK_DOWNLOAD_BASE}/v{LAST_SEEN_VERSION}/tt5sdk_v{LAST_SEEN_VERSION}_{tag}.7z"
    return SdkAsset(LAST_SEEN_VERSION, "standard", tag, url)


# ----------------------------------------------------------- SDK download


def _verify_archive(part: Path, expected: Optional[str]) -> int:
    """Raise SetupError unless ``part`` is a complete 7z archive of a sensible size."""
    written = part.stat().st_size
    if expected and expected.isdigit() and written != int(expected):
        raise SetupError(f"incomplete download ({written} of {expected} bytes)")
    with open(part, "rb") as check:
        if check.read(len(SEVEN_ZIP_MAGIC)) != SEVEN_ZIP_MAGIC:
            raise SetupError("the server did not send a 7z archive (an error page?)")
    if written < MIN_ARCHIVE_BYTES:
        raise SetupError(f"the file is only {written} bytes, too small for the SDK")
    return written


def download_archive(
    url: str,
    destination: Path,
    opener: Callable[..., object] = urllib.request.urlopen,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    referer: Optional[str] = SDK_PAGES[0],
    external: Optional[bool] = None,
) -> None:
    """Download with retries, a size check and a check that the file really is a 7z archive.

    When Python is refused or fails, curl and PowerShell try the same URL (``external``:
    None means "only with the real urlopen").
    """
    last_error: Optional[Exception] = None
    problems: List[str] = []
    part = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            written = 0
            with open_url(url, opener, 60, "GET", referer) as response, open(part, "wb") as out:  # type: ignore[attr-defined]
                expected = response.headers.get("Content-Length")
                next_report = 25
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    if expected and expected.isdigit() and int(expected) > 0:
                        percent = written * 100 // int(expected)
                        if percent >= next_report:
                            say(f"    {percent}%")
                            next_report += 25
            _verify_archive(part, expected)
            os.replace(part, destination)
            return
        except urllib.error.HTTPError as error:
            last_error = error
            if 400 <= error.code < 500:
                break
        except (SetupError, urllib.error.URLError, OSError, TimeoutError) as error:
            last_error = error
        if attempt < retries:
            say(f"    download failed ({last_error}); retrying ...")
            sleep(2.0 * attempt)
    problems.append(str(last_error))
    use_external = (opener is urllib.request.urlopen) if external is None else external
    if use_external and not is_missing(last_error):
        say("    Python could not download it; trying curl / PowerShell ...")
        more = fetch_external(url, part, referer, EXTERNAL_DOWNLOAD_TIMEOUT)
        if not more:
            try:
                _verify_archive(part, None)
                os.replace(part, destination)
                return
            except (SetupError, OSError) as error:
                problems.append(str(error))
        else:
            problems += more
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass
    raise SetupError(f"download of {url} failed: " + "; ".join(problems))


# -------------------------------------------------------------- extraction


def seven_zip_executables() -> List[str]:
    names = ["7z", "7zz", "7za", "7zr"]
    found = [path for path in (shutil.which(name) for name in names) if path]
    if IS_WINDOWS:
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidate = os.path.join(root, "7-Zip", "7z.exe")
                if os.path.isfile(candidate):
                    found.append(candidate)
    return found


def _extract_with_py7zr(archive: Path, target: Path) -> Optional[str]:
    try:
        import py7zr  # type: ignore[import-not-found]
    except ImportError:
        return "py7zr is not installed"
    try:
        with py7zr.SevenZipFile(archive) as bundle:
            bundle.extractall(target)
        return None
    except Exception as error:  # py7zr raises many kinds of errors
        return f"py7zr failed: {error}"


def _extract_with_binary(command: Sequence[str]) -> Optional[str]:
    code, output = run_quiet(command, timeout=600)
    return None if code == 0 else f"{command[0]} failed: {output.strip()[-300:]}"


def seven_zip_install_plans(
    system: str, which: Callable[[str], Optional[str]] = shutil.which
) -> List[List[str]]:
    if system == "windows":
        return [["winget", "install", "--id", "7zip.7zip", "-e", "--silent",
                 "--accept-package-agreements", "--accept-source-agreements"]] if which("winget") else []
    if system == "darwin":
        return [["brew", "install", "p7zip"]] if which("brew") else []
    manager = detect_linux_manager(which)
    table = {
        "apt-get": [["apt-get", "install", "-y", "p7zip-full"]],
        "dnf": [["dnf", "install", "-y", "p7zip", "p7zip-plugins"]],
        "yum": [["yum", "install", "-y", "p7zip", "p7zip-plugins"]],
        "pacman": [["pacman", "-S", "--noconfirm", "--needed", "p7zip"]],
        "zypper": [["zypper", "--non-interactive", "install", "p7zip"]],
        "apk": [["apk", "add", "7zip"]],
        "xbps-install": [["xbps-install", "-Sy", "p7zip"]],
        "emerge": [["emerge", "--ask=n", "app-arch/p7zip"]],
    }
    return table.get(manager or "", [])


def looks_like_seven_zip(path: Path) -> bool:
    """True when the file is a Windows program of a plausible size that says it is 7-Zip."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            header = handle.read(2)
    except OSError:
        return False
    if header != b"MZ" or not PORTABLE_MIN_BYTES <= size <= PORTABLE_MAX_BYTES:
        return False
    _code, output = run_quiet([str(path)], timeout=20)
    return "7-zip" in output.lower()


def download_portable_seven_zip(
    folder: Path,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> Optional[Path]:
    """Fetch 7zr.exe, 7-Zip's console program for .7z files, into ``folder`` (Windows only).

    Nothing is installed: the file lives in the temporary folder of the setup and is
    deleted with it. Every address is tried in turn; a file that is not a program of
    the right size that identifies itself as 7-Zip is thrown away.
    """
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "7zr.exe"
    for url in SEVEN_ZIP_PORTABLE_URLS:
        try:
            with open_url(url, opener, 60) as response:  # type: ignore[attr-defined]
                data = response.read(PORTABLE_MAX_BYTES + 1)
            if not PORTABLE_MIN_BYTES <= len(data) <= PORTABLE_MAX_BYTES:
                continue
            target.write_bytes(data)
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
        if looks_like_seven_zip(target):
            return target
        try:
            target.unlink()
        except OSError:
            pass
    return None


def extract_archive(archive: Path, target: Path, system: str, allow_install: bool = True) -> None:
    """Unpack a .7z with py7zr, a 7-Zip binary or bsdtar.

    When none of them can, 7-Zip is installed through the system package manager and,
    on Windows, a portable 7zr.exe is fetched into the folder that holds ``target``.
    """
    target.mkdir(parents=True, exist_ok=True)
    problems: List[str] = []

    def attempt() -> bool:
        error = _extract_with_py7zr(archive, target)
        if error is None:
            return True
        problems.append(error)
        for exe in seven_zip_executables():
            error = _extract_with_binary([exe, "x", "-y", f"-o{target}", str(archive)])
            if error is None:
                return True
            problems.append(error)
        tar = shutil.which("tar")
        if tar:
            code, output = run_quiet([tar, "--version"], timeout=10)
            if code == 0 and ("bsdtar" in output.lower() or "libarchive" in output.lower()):
                error = _extract_with_binary([tar, "-xf", str(archive), "-C", str(target)])
                if error is None:
                    return True
                problems.append(error)
        return False

    if attempt():
        return
    if allow_install:
        for command in seven_zip_install_plans(system):
            if system == "linux":
                command = with_privileges(command) or command
            say("  No tool to open .7z files was found; installing 7-Zip ...")
            if run_visible(command) and attempt():
                return
    if allow_install and system == "windows":
        say("  Downloading 7-Zip's portable console program (7zr.exe) from 7-zip.org ...")
        portable = download_portable_seven_zip(target.parent)
        if portable is not None:
            error = _extract_with_binary([str(portable), "x", "-y", f"-o{target}", str(archive)])
            if error is None:
                return
            problems.append(error)
        else:
            problems.append("7zr.exe could not be downloaded from 7-zip.org")
    raise SetupError("could not unpack the .7z archive. " + "; ".join(problems[-3:]))


def find_library(root: Path, system: str) -> Optional[Path]:
    """Locate the SDK library inside an unpacked archive."""
    name = {"windows": "TeamTalk5.dll", "darwin": "libTeamTalk5.dylib"}.get(system, "libTeamTalk5.so")
    matches = [p for p in root.rglob("*") if p.is_file() and p.name.lower() == name.lower()]
    if not matches:
        return None

    def rank(path: Path) -> Tuple[int, int, str]:
        parts = [part.lower() for part in path.parts]
        return (
            0 if "teamtalk_dll" in parts else 1,
            1 if any(token in parts for token in ("x86", "win32", "32bit")) else 0,
            str(path),
        )

    return sorted(matches, key=rank)[0]


# ------------------------------------------------------------ verification

_PROBE_SCRIPT = r"""
import ctypes, os, sys
path = sys.argv[1]
if sys.platform == "win32":
    os.add_dll_directory(os.path.dirname(path))
    library = ctypes.CDLL(path)
    library.TT_GetVersion.restype = ctypes.c_wchar_p
else:
    library = ctypes.CDLL(path)
    library.TT_GetVersion.restype = ctypes.c_char_p
version = library.TT_GetVersion()
if isinstance(version, bytes):
    version = version.decode("utf-8", "replace")
print("VERSION=" + str(version))
"""


@dataclass
class LibraryCheck:
    ok: bool
    version: str = ""
    problem: str = ""
    glibc_too_old: bool = False


def check_library(path: Path) -> LibraryCheck:
    """Load the library in a separate process and ask it for its version."""
    code, output = run_quiet([sys.executable, "-c", _PROBE_SCRIPT, str(path)], timeout=60)
    match = re.search(r"VERSION=(\S+)", output)
    if code == 0 and match:
        return LibraryCheck(True, version=match.group(1))
    lowered = output.lower()
    glibc = "glibc" in lowered or "libstdc++" in lowered and "version" in lowered
    if "winerror 193" in lowered or "not a valid win32" in lowered:
        problem = "the library is for a different architecture (a 64-bit Python needs the 64-bit DLL)"
    elif glibc:
        problem = "this Linux is older than the one the library was built for (system libraries too old)"
    elif "cannot open shared object" in lowered or "winerror 126" in lowered:
        problem = "a library it depends on is missing: " + output.strip().splitlines()[-1][:200]
    else:
        problem = output.strip()[-300:] or "the library could not be loaded"
    return LibraryCheck(False, problem=problem, glibc_too_old=glibc)


def version_numbers(version: str) -> Tuple[int, int]:
    match = _VERSION_NUMBERS_RE.search(version)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def sdk_destination(bot_dir: Path, system: str) -> Path:
    if system == "windows":
        return bot_dir / SDK_FOLDER / "TeamTalk5.dll"
    if system == "darwin":
        return bot_dir / SDK_FOLDER / "libTeamTalk5.dylib"
    return bot_dir / SDK_FOLDER / "libTeamTalk5.so"


def install_library(source: Path, destination: Path) -> None:
    """Copy the verified library into place, keeping the previous one as .bak."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + ".new")
    shutil.copy2(source, staged)
    try:
        if destination.exists():
            backup = destination.with_name(destination.name + ".bak")
            if backup.exists():
                backup.unlink()
            os.replace(destination, backup)
        os.replace(staged, destination)
    except PermissionError as error:
        if staged.exists():
            staged.unlink()
        raise SetupError(
            f"{destination.name} is in use. Stop the bot (and anything else using it), then run this again."
        ) from error


def restore_previous(destination: Path, had_previous: bool) -> None:
    """Undo install_library: put the previous file back, or remove the new one when there was none."""
    backup = destination.with_name(destination.name + ".bak")
    try:
        if had_previous and backup.exists():
            os.replace(backup, destination)
        elif destination.exists():
            destination.unlink()
    except OSError:
        pass


def sdk_extra_files(library: Path, system: str) -> List[Path]:
    """The files that are installed next to the library (Windows only).

    The SDK's Library/TeamTalk_DLL folder holds three files: TeamTalk5.dll, the import
    library TeamTalk5.lib and the C header TeamTalk.h. The bot folder gets exactly those
    three in its own TeamTalk_DLL folder, so this returns the .lib and the .h that the
    SDK folder has. Any other file of that folder is left behind.
    """
    if system != "windows":
        return []
    present = {path.name.lower(): path for path in library.parent.iterdir() if path.is_file()}
    return [
        present[name.lower()]
        for name in WINDOWS_SDK_FILES
        if name.lower() != library.name.lower() and name.lower() in present
    ]


def missing_sdk_files(destination: Path, system: str) -> List[str]:
    """Names of the files of the SDK folder that are not in the bot's TeamTalk_DLL folder yet."""
    if system != "windows":
        return []
    return [name for name in WINDOWS_SDK_FILES if not (destination.parent / name).is_file()]


def move_legacy_library(bot_dir: Path, destination: Path, system: str) -> bool:
    """Move a TeamTalk5.dll that an earlier version put beside TTMediaBot.py into TeamTalk_DLL.

    Only done when the SDK folder has no library yet; it needs no download.
    """
    old = bot_dir / "TeamTalk5.dll"
    if system != "windows" or destination.exists() or not old.is_file():
        return False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old, destination)
    except OSError as error:
        say(f"  Could not move {old} into {destination.parent}: {error}")
        return False
    say(f"  Moved {old.name} from {bot_dir} into {destination.parent} (the SDK folder).")
    return True


def remove_legacy_files(bot_dir: Path, system: str) -> None:
    """Delete the old copy beside TTMediaBot.py once the SDK folder holds a working library.

    A stale TeamTalk5.dll there could be found before the new one, because the binding
    also adds the current folder to the DLL search path.
    """
    if system != "windows":
        return
    for name in LEGACY_ROOT_FILES:
        path = bot_dir / name
        if not path.is_file():
            continue
        try:
            path.unlink()
            say(f"  Removed the old {name} from {bot_dir}; the bot reads {bot_dir / SDK_FOLDER}.")
        except OSError as error:
            say(f"  Could not remove {path}: {error}. Delete it by hand while the bot is stopped.")


def discard_backups(paths: Sequence[Path]) -> None:
    """Delete the .bak copies that install_library made, so the folder holds only the SDK files."""
    for path in paths:
        backup = path.with_name(path.name + ".bak")
        try:
            if backup.exists():
                backup.unlink()
        except OSError:
            pass


def manual_sdk_help(system: str, bot_dir: Path, reason: str) -> str:
    destination = sdk_destination(bot_dir, system)
    kind = {
        "windows": "Windows 10/11 x64",
        "darwin": "Mac OS X",
    }.get(system, "Linux (the build for your distribution) or Raspbian for ARM")
    if system == "windows":
        steps = (
            "    2. Unpack it into a temporary folder with 7-Zip (https://www.7-zip.org; the\n"
            "       command below needs 7z.exe on the PATH, or give its full path):\n"
            '         7z x -y -o"%TEMP%\\ttsdk" tt5sdk_*_win64.7z\n'
            f"    3. Copy the three files of Library\\TeamTalk_DLL into the TeamTalk_DLL folder of the bot\n"
            "       (the DLL does not go beside TTMediaBot.py):\n"
            f'         if not exist "{destination.parent}" mkdir "{destination.parent}"\n'
            + "".join(
                f'         copy "%TEMP%\\ttsdk\\Library\\TeamTalk_DLL\\{name}" "{destination.parent}"\n'
                for name in WINDOWS_SDK_FILES
            )
            + '       (if that folder is not there, find the file with: dir /s /b "%TEMP%\\ttsdk\\TeamTalk5.dll")\n'
            "    4. Delete the temporary folder:\n"
            '         rmdir /s /q "%TEMP%\\ttsdk"\n'
        )
    else:
        steps = (
            "    2. Unpack the .7z file with 7-Zip (https://www.7-zip.org).\n"
            f"    3. Copy {destination.name} (inside Library/TeamTalk_DLL) to {destination.parent}\n"
        )
    direct = known_asset(system, platform.machine())
    link = f"    Direct link of the release this script knows: {direct.url}\n" if direct else ""
    python = "venv\\Scripts\\python.exe" if system == "windows" else "python3"
    script = "tools\\setup_deps.py" if system == "windows" else "tools/setup_deps.py"
    return (
        f"  The TeamTalk 5 SDK could not be set up automatically: {reason}\n"
        "  Do it by hand:\n"
        f"    1. Open {SDK_PAGES[0]} and download the Standard Edition for {kind}.\n"
        + link
        + steps
        + "    Or let this script do steps 2 to 4 with the file you downloaded in your browser:\n"
        f'         {python} {script} sdk --sdk-file "<the downloaded .7z file>"\n'
        "  BearWare distributes this download as a 30 day trial; a license is needed to keep using it."
    )


def setup_sdk(
    bot_dir: Path,
    system: str,
    machine: str,
    force: bool = False,
    check_only: bool = False,
    fetch: Fetcher = http_get,
    download: Callable[[str, Path], None] = download_archive,
    archive: Optional[Path] = None,
) -> bool:
    say("== TeamTalk 5 SDK library ==")
    destination = sdk_destination(bot_dir, system)
    legacy = system == "windows" and (bot_dir / "TeamTalk5.dll").is_file()
    if legacy and not check_only:
        # An earlier version of this script copied the DLL beside TTMediaBot.py.
        move_legacy_library(bot_dir, destination, system)
    installed: Optional[LibraryCheck] = None
    if destination.exists():
        installed = check_library(destination)
        if installed.ok:
            say(f"  Installed: {destination} (version {installed.version})")
        else:
            say(f"  {destination} exists but cannot be used: {installed.problem}")
    else:
        say(f"  {destination.name} is not installed in {destination.parent}.")
    if check_only:
        if legacy and not destination.exists():
            say(
                f"  TeamTalk5.dll lies beside TTMediaBot.py (the old place). Run this without --check "
                f"to move it into {destination.parent}."
            )
        return bool(installed and installed.ok)
    missing = missing_sdk_files(destination, system) if installed and installed.ok else []
    if missing:
        say(f"  Not yet in {destination.parent}: {', '.join(missing)}.")

    local = archive is not None
    if archive is not None:
        if not archive.is_file():
            say(manual_sdk_help(system, bot_dir, f"the file {archive} does not exist"))
            return bool(installed and installed.ok)
        asset = SdkAsset("local", "standard", "local", str(archive))
        force = True  # the person gave this file on purpose
        download = lambda url, destination: shutil.copyfile(archive, destination)  # noqa: E731
        say(f"  Using the archive you gave: {archive}")
    else:
        assets, notes = discover_assets(fetch)
        found = choose_asset(assets, system, machine)
        if found is None:
            found = known_asset(system, machine)
            if found is not None:
                if notes:
                    say("  The download page could not be read:")
                    for note in notes:
                        say(f"    - {note}")
                say(
                    f"  Trying the file of the newest release this script knows (v{found.version}) "
                    "directly on the official site."
                )
        if found is None:
            reason = "no download for this system was found on the official site"
            if notes:
                reason += " (" + "; ".join(notes) + ")"
            say(manual_sdk_help(system, bot_dir, reason))
            return bool(installed and installed.ok)
        asset = found
        say(f"  Newest stable release on the official site: v{asset.version} ({asset.tag})")
    if installed and installed.ok and not force:
        have, latest = version_numbers(installed.version), version_numbers(asset.version)
        if have >= latest and not missing:
            say("  The installed library is already the newest release.")
            remove_legacy_files(bot_dir, system)
            return True
        if have >= latest:
            say("  The library is the newest release; the SDK is downloaded again only to complete the folder.")

    with temporary_directory("ttsdk_") as work:
        work_dir = Path(work)
        attempts = [asset]
        if system == "linux" and machine.lower() in ("x86_64", "amd64") and not local:
            # An older distribution may not run the newest build; the same release is
            # sometimes published for older Ubuntu versions as well.
            for tag in ("ubuntu24_x86_64", "ubuntu22_x86_64"):
                if tag != asset.tag:
                    attempts.append(
                        SdkAsset(asset.version, "standard", tag,
                                 f"{SDK_DOWNLOAD_BASE}/v{asset.version}/tt5sdk_v{asset.version}_{tag}.7z")
                    )
        last_problem = ""
        for index, candidate in enumerate(attempts):
            archive_path = work_dir / f"sdk_{index}.7z"
            unpacked = work_dir / f"unpacked_{index}"
            try:
                if not local:
                    say(f"  Downloading {candidate.url}")
                download(candidate.url, archive_path)
                say("  Unpacking ...")
                extract_archive(archive_path, unpacked, system)
            except SetupError as error:
                last_problem = str(error)
                if index == 0:
                    say(f"  {error}")
                    if len(attempts) == 1:
                        break
                continue
            library = find_library(unpacked, system)
            if library is None:
                last_problem = f"{destination.name} was not found inside the archive"
                continue
            result = check_library(library)
            if not result.ok:
                last_problem = result.problem
                say(f"  The downloaded library does not load: {result.problem}")
                if result.glibc_too_old and index + 1 < len(attempts):
                    say("  Trying the build for an older Ubuntu ...")
                continue
            placed: List[Tuple[Path, bool]] = []  # (file in the bot folder, was there something before)
            try:
                placed.append((destination, destination.exists()))
                install_library(library, destination)
                extras = sdk_extra_files(library, system)
                for extra in extras:
                    target = destination.with_name(extra.name)
                    placed.append((target, target.exists()))
                    install_library(extra, target)
                    say(f"  Also installed {extra.name} (it ships next to {library.name}).")
                if system == "windows":
                    absent = [
                        name for name in WINDOWS_SDK_FILES
                        if name.lower() not in {library.name.lower(), *(e.name.lower() for e in extras)}
                    ]
                    if absent:
                        say(f"  Note: {', '.join(absent)} was not in the SDK folder of this release.")
            except SetupError as error:
                say(manual_sdk_help(system, bot_dir, str(error)))
                return False
            if system == "windows":
                # The test above ran inside the temporary folder, where every file of the
                # SDK folder was at hand; the bot folder must be able to load it alone.
                final = check_library(destination)
                if not final.ok:
                    for path, had_previous in reversed(placed):
                        restore_previous(path, had_previous)
                    try:
                        destination.parent.rmdir()  # only succeeds when nothing is left in it
                    except OSError:
                        pass
                    say(f"  {destination.name} does not load from {destination.parent}: {final.problem}")
                    say("  The previous files were put back." if placed[0][1] else "  Nothing was installed.")
                    say(manual_sdk_help(system, bot_dir, final.problem))
                    return False
                # Verified: the previous copies are not needed any more, so the folder holds
                # only the SDK files, and the old copy beside TTMediaBot.py goes away.
                discard_backups([path for path, _ in placed])
                remove_legacy_files(bot_dir, system)
            say(f"  Installed {destination} (version {result.version}).")
            if system == "windows":
                kept = [name for name in WINDOWS_SDK_FILES if (destination.parent / name).is_file()]
                say(f"  {destination.parent} holds: {', '.join(kept)}.")
            say("  Note: BearWare distributes this SDK download as a 30 day trial.")
            return True
        say(manual_sdk_help(system, bot_dir, last_problem or "the download failed"))
        return bool(installed and installed.ok)


# ----------------------------------------------------------------------- CLI


def current_system() -> str:
    name = platform.system().lower()
    return {"windows": "windows", "linux": "linux", "darwin": "darwin"}.get(name, name)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check and install FFmpeg and the TeamTalk 5 SDK library.")
    parser.add_argument("what", choices=("all", "ffmpeg", "sdk"), help="what to set up")
    parser.add_argument("--bot-dir", default=str(Path(__file__).resolve().parent.parent), help="the bot folder")
    parser.add_argument("--force", action="store_true", help="download the SDK even if the newest one is installed")
    parser.add_argument("--check", action="store_true", help="only report, install nothing")
    parser.add_argument(
        "--sdk-file",
        metavar="ARCHIVE",
        help="install the TeamTalk SDK from this .7z file (downloaded in a browser) instead of downloading it",
    )
    args = parser.parse_args(argv)

    bot_dir = Path(args.bot_dir).resolve()
    system, machine = current_system(), platform.machine()
    ok = True
    if args.what in ("all", "ffmpeg"):
        ok = setup_ffmpeg(bot_dir, system, check_only=args.check) and ok
    if args.what in ("all", "sdk"):
        archive = Path(args.sdk_file).expanduser().resolve() if args.sdk_file else None
        ok = setup_sdk(bot_dir, system, machine, force=args.force, check_only=args.check, archive=archive) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
