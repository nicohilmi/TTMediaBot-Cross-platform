"""Looks for new commits of the bot on GitHub and installs them.

The bot folder has to be a git clone. Looking for news is cheap: ``git ls-remote``
asks GitHub for the newest commit of the current branch without downloading
anything and without the rate limit of the REST API. Only when that commit is
new does the bot ``git fetch`` to read what changed. Installing is a fast-forward
``git pull`` followed by a restart (see ``InstallUpdateCommand``).

Every git call runs without any prompt and with a time limit, so a missing
credential or a dead network can never leave the bot waiting.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, TYPE_CHECKING

from bot import app_vars
from bot.ffmpeg_locator import hidden_process_kwargs

if TYPE_CHECKING:
    from bot import Bot

# Gives the bot time to connect and join its channel before the first check.
STARTUP_DELAY_SECONDS = 30
MIN_INTERVAL_MINUTES = 1
LOCAL_TIMEOUT = 20
LS_REMOTE_TIMEOUT = 45
FETCH_TIMEOUT = 120
PULL_TIMEOUT = 300
# Commits listed when describing an update; more are only counted.
MAX_COMMITS = 50
MAX_ERROR_LENGTH = 220

_VERSION_RE = re.compile(r"""^app_version\s*=\s*["']([^"']+)["']""", re.MULTILINE)
# user:password@ in a remote URL must never end up in a message or the log.
_CREDENTIALS_RE = re.compile(r"(?<=://)[^/@\s]+@")


class UpdateError(Exception):
    """A check or an installation failed. The text is meant for people."""


@dataclass
class Commit:
    sha: str
    author: str
    timestamp: int
    subject: str


@dataclass
class UpdateInfo:
    remote: str
    branch: str
    local_sha: str
    remote_sha: str
    commits: List[Commit]  # newest first
    current_version: str
    new_version: Optional[str]  # None while the version number stays the same
    requirements_changed: bool
    can_fast_forward: bool


def short_sha(sha: str) -> str:
    return sha[:7]


def _git_env() -> dict:
    env = os.environ.copy()
    # No prompt of any kind: terminal, Git Credential Manager window, askpass, ssh.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["SSH_ASKPASS_REQUIRE"] = "never"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=15")
    return env


def _short_message(text: str) -> str:
    """The useful first lines of a git error, on one line and without secrets."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    message = " ".join(lines[:3])
    message = _CREDENTIALS_RE.sub("", message)
    if len(message) > MAX_ERROR_LENGTH:
        message = message[: MAX_ERROR_LENGTH - 3].rstrip() + "..."
    return message


def _run_git(args: Sequence[str], timeout: float) -> Tuple[int, str, str]:
    git = shutil.which("git")
    if not git:
        raise UpdateError("Git is not installed or is not in the PATH")
    try:
        completed = subprocess.run(
            [git, *args],
            cwd=app_vars.directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=_git_env(),
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        raise UpdateError(
            "git {command} did not answer within {seconds} seconds".format(
                command=args[0], seconds=int(timeout)
            )
        )
    except OSError as error:
        raise UpdateError("Git could not be started: {error}".format(error=error))
    return (
        completed.returncode,
        completed.stdout.decode("utf-8", "replace").strip(),
        completed.stderr.decode("utf-8", "replace").strip(),
    )


def _git(args: Sequence[str], timeout: float = LOCAL_TIMEOUT) -> str:
    """Runs git and returns its output; a failure becomes an UpdateError."""
    code, out, err = _run_git(args, timeout)
    if code != 0:
        raise UpdateError(
            _short_message(err or out)
            or "git {command} failed (exit code {code})".format(command=args[0], code=code)
        )
    return out


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    code, out, err = _run_git(["merge-base", "--is-ancestor", ancestor, descendant], LOCAL_TIMEOUT)
    if code == 0:
        return True
    if code == 1:
        return False
    raise UpdateError(_short_message(err or out) or "git merge-base failed")


class UpdateChecker:
    """Background check for new commits, plus the steps the ``install`` command uses."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # One git operation at a time (the background check or an installation).
        self._git_lock = threading.RLock()
        # Held by an administrator's installation, so two cannot overlap.
        self.install_lock = threading.Lock()
        self.pending: Optional[UpdateInfo] = None
        self._cache: Optional[Tuple[str, str, Optional[UpdateInfo]]] = None
        self._announced_sha: Optional[str] = None
        self._last_error: Optional[str] = None

    @property
    def _config(self):
        return self._bot.config.updater

    # ------------------------------------------------------------ background

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="UpdateChecker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        if self._stop.wait(STARTUP_DELAY_SECONDS):
            return
        while not self._stop.is_set():
            try:
                if self._config.enabled:
                    self._cycle()
            except Exception:
                logging.error("[Updater] unexpected error during a check", exc_info=True)
            minutes = max(int(self._config.check_interval_minutes), MIN_INTERVAL_MINUTES)
            if self._stop.wait(minutes * 60):
                return

    def _cycle(self) -> None:
        try:
            info = self.check()
        except UpdateError as error:
            # The same problem is logged once, not at every check.
            if str(error) != self._last_error:
                self._last_error = str(error)
                logging.warning(f"[Updater] could not check for updates: {error}")
            return
        self._last_error = None
        if info is None or info.remote_sha == self._announced_sha:
            return
        if not self._can_announce():
            return  # the bot is offline right now; the next check tries again
        try:
            self._bot.ttclient.send_message(self.format_notification(info), type=2)
        except Exception:
            logging.error("[Updater] could not send the update notice", exc_info=True)
            return
        self._announced_sha = info.remote_sha
        logging.info(
            f"[Updater] update announced: {short_sha(info.local_sha)} -> "
            f"{short_sha(info.remote_sha)} ({len(info.commits)} commit(s))"
        )

    def _can_announce(self) -> bool:
        try:
            from bot.TeamTalk.structs import Flags

            ttclient = self._bot.ttclient
            return bool(ttclient.flags & Flags.AUTHORIZED) and ttclient.tt.getMyChannelID() > 0
        except Exception:
            return False

    # ----------------------------------------------------------------- check

    def check(self) -> Optional[UpdateInfo]:
        """Asks GitHub whether the bot folder is behind. None means up to date."""
        with self._git_lock:
            info = self._check()
            self.pending = info
            return info

    def _check(self) -> Optional[UpdateInfo]:
        self._ensure_repository()
        remote = self._config.remote or "origin"
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch == "HEAD":
            raise UpdateError("The bot folder is not on a branch (detached HEAD)")
        local_sha = _git(["rev-parse", "HEAD"])
        reference = "refs/heads/" + branch
        remote_sha = ""
        for line in _git(["ls-remote", remote, reference], LS_REMOTE_TIMEOUT).splitlines():
            sha, _, name = line.partition("\t")
            if name.strip() == reference:
                remote_sha = sha.strip()
        if not remote_sha:
            raise UpdateError(
                "Branch '{branch}' was not found on '{remote}'".format(
                    branch=branch, remote=remote
                )
            )
        if remote_sha == local_sha:
            return None
        if self._cache and self._cache[:2] == (local_sha, remote_sha):
            return self._cache[2]
        info = self._describe(remote, branch, local_sha, remote_sha)
        self._cache = (local_sha, remote_sha, info)
        return info

    def _ensure_repository(self) -> None:
        code, out, _ = _run_git(["rev-parse", "--show-toplevel"], LOCAL_TIMEOUT)
        if code != 0 or not out:
            raise UpdateError(
                "This installation is not a Git clone, so it cannot update itself"
            )
        same = os.path.normcase(os.path.realpath(out)) == os.path.normcase(
            os.path.realpath(app_vars.directory)
        )
        if not same:
            raise UpdateError("The bot folder is not the root of a Git repository")

    def _describe(
        self, remote: str, branch: str, local_sha: str, remote_sha: str
    ) -> Optional[UpdateInfo]:
        _git(["fetch", "--quiet", remote, "refs/heads/" + branch], FETCH_TIMEOUT)
        if _is_ancestor(remote_sha, local_sha):
            return None  # this copy is ahead of GitHub, there is nothing to install
        can_fast_forward = _is_ancestor(local_sha, remote_sha)
        log = _git(
            [
                "log",
                "-n",
                str(MAX_COMMITS),
                "--format=%H%x1f%an%x1f%at%x1f%s",
                "{}..{}".format(local_sha, remote_sha),
            ]
        )
        commits: List[Commit] = []
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4 and parts[2].isdigit():
                commits.append(Commit(parts[0], parts[1], int(parts[2]), parts[3]))
        new_version: Optional[str] = None
        code, out, _ = _run_git(
            ["show", "{}:bot/app_vars.py".format(remote_sha)], LOCAL_TIMEOUT
        )
        if code == 0:
            match = _VERSION_RE.search(out)
            if match and match.group(1) != app_vars.app_version:
                new_version = match.group(1)
        requirements = _git(
            ["diff", "--name-only", local_sha, remote_sha, "--", "requirements.txt"]
        )
        return UpdateInfo(
            remote=remote,
            branch=branch,
            local_sha=local_sha,
            remote_sha=remote_sha,
            commits=commits,
            current_version=app_vars.app_version,
            new_version=new_version,
            requirements_changed=bool(requirements),
            can_fast_forward=can_fast_forward,
        )

    # --------------------------------------------------------------- install

    def install(self, info: UpdateInfo) -> str:
        """Fast-forwards the bot folder to GitHub. Returns the new commit."""
        with self._git_lock:
            if not info.can_fast_forward:
                raise UpdateError(
                    "This copy has changes that are not on GitHub, so it cannot be "
                    "brought up to date automatically"
                )
            _git(["pull", "--ff-only", info.remote, info.branch], PULL_TIMEOUT)
            new_sha = _git(["rev-parse", "HEAD"])
            self.pending = None
            self._cache = None
            logging.info(
                f"[Updater] installed {short_sha(info.local_sha)} -> {short_sha(new_sha)}"
            )
            return new_sha

    # ---------------------------------------------------------------- notice

    def format_notification(self, info: UpdateInfo) -> str:
        """The channel message that announces an update."""
        translate = self._bot.translator.translate
        lines = [
            translate("Update available"),
            translate("A new version of TTMediaBot is ready to install."),
            translate("Installed version: {version} ({commit})").format(
                version=info.current_version, commit=short_sha(info.local_sha)
            ),
        ]
        if info.new_version:
            lines.append(
                translate("Available version: {version} ({commit})").format(
                    version=info.new_version, commit=short_sha(info.remote_sha)
                )
            )
        else:
            lines.append(
                translate("Latest commit: {commit}").format(
                    commit=short_sha(info.remote_sha)
                )
            )
        if info.commits:
            latest = info.commits[0]
            subject = latest.subject
            if len(subject) > 120:
                subject = subject[:117].rstrip() + "..."
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(latest.timestamp))
            lines.append(
                translate("Latest change: {subject} ({author}, {date})").format(
                    subject=subject, author=latest.author, date=when
                )
            )
            if len(info.commits) > 1:
                count = (
                    "{}+".format(MAX_COMMITS)
                    if len(info.commits) >= MAX_COMMITS
                    else str(len(info.commits))
                )
                lines.append(
                    translate("This update contains {count} changes.").format(count=count)
                )
        if info.requirements_changed:
            lines.append(
                translate(
                    "It also changes the required Python packages. They are installed while the bot restarts."
                )
            )
        if info.can_fast_forward:
            lines.append(
                translate("To install it, an administrator can send: install")
            )
            lines.append(
                translate("The bot will restart automatically to finish the update.")
            )
        else:
            lines.append(
                translate(
                    "This copy has changes that are not on GitHub, so it must be updated manually."
                )
            )
        return "\n".join(lines)
