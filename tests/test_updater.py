import json
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import TestCase, skipUnless

from bot import app_vars, updater
from bot.commands import admin_commands

GIT = shutil.which("git")


def git(cwd, *args):
    result = subprocess.run(
        ["git", "-c", "user.name=Test Author", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode().strip()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


class FakeTTClient:
    def __init__(self):
        self.messages = []

    def send_message(self, text, user=None, type=1):
        self.messages.append((text, user, type))


class FakeBot:
    def __init__(self, config_dir):
        self.config = SimpleNamespace(
            updater=SimpleNamespace(enabled=True, check_interval_minutes=60, remote="origin")
        )
        self.translator = SimpleNamespace(translate=lambda text: text)
        self.ttclient = FakeTTClient()
        self.config_manager = SimpleNamespace(config_dir=config_dir)
        self.is_updating = False


@skipUnless(GIT, "git is not available")
class UpdaterTestBase(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.remote = os.path.join(self.root, "remote.git")
        self.dev = os.path.join(self.root, "dev")
        self.folder = os.path.join(self.root, "bot-folder")
        subprocess.run(["git", "init", "--bare", "-b", "master", self.remote],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.makedirs(os.path.join(self.dev, "bot"))
        git(self.dev, "init", "-b", "master")
        write(os.path.join(self.dev, "bot", "app_vars.py"),
              'app_version = "{}"\n'.format(app_vars.app_version))
        write(os.path.join(self.dev, "requirements.txt"), "requests\n")
        write(os.path.join(self.dev, "feature.txt"), "one\n")
        git(self.dev, "add", ".")
        git(self.dev, "commit", "-m", "First version")
        git(self.dev, "remote", "add", "origin", self.remote)
        git(self.dev, "push", "-u", "origin", "master")
        git(self.root, "clone", self.remote, self.folder)
        self._old_directory = app_vars.directory
        app_vars.directory = self.folder
        self.bot = FakeBot(self.root)
        self.checker = updater.UpdateChecker(self.bot)

    def tearDown(self):
        app_vars.directory = self._old_directory
        shutil.rmtree(self.root, ignore_errors=True)

    def publish(self, message, files=None):
        for name, text in (files or {"feature.txt": message + "\n"}).items():
            write(os.path.join(self.dev, name), text)
        git(self.dev, "add", ".")
        git(self.dev, "commit", "-m", message)
        git(self.dev, "push", "origin", "master")


@skipUnless(GIT, "git is not available")
class UpdaterTests(UpdaterTestBase):
    def test_up_to_date_gives_none(self):
        self.assertIsNone(self.checker.check())

    def test_new_commit_is_described(self):
        self.publish("Fix the reconnect loop")
        info = self.checker.check()
        self.assertIsNotNone(info)
        self.assertEqual(len(info.commits), 1)
        self.assertEqual(info.commits[0].subject, "Fix the reconnect loop")
        self.assertEqual(info.commits[0].author, "Test Author")
        self.assertTrue(info.can_fast_forward)
        self.assertIsNone(info.new_version)
        self.assertFalse(info.requirements_changed)
        self.assertEqual(info.branch, "master")
        self.assertIs(self.checker.pending, info)

    def test_several_commits_and_a_new_version_number(self):
        self.publish("Second change")
        self.publish("Version 4.2", {"bot/app_vars.py": 'app_version = "4.2"\n'})
        info = self.checker.check()
        self.assertEqual([c.subject for c in info.commits], ["Version 4.2", "Second change"])
        self.assertEqual(info.new_version, "4.2")
        notice = self.checker.format_notification(info)
        self.assertIn("Update available", notice)
        self.assertIn("Available version: 4.2", notice)
        self.assertIn("Latest change: Version 4.2 (Test Author,", notice)
        self.assertIn("This update contains 2 changes.", notice)
        self.assertIn("send: install", notice)
        self.assertNotIn("{", notice)

    def test_a_second_check_does_not_fetch_again(self):
        self.publish("Something new")
        calls = []
        original = updater._run_git

        def counting(args, timeout):
            calls.append(args[0])
            return original(args, timeout)

        updater._run_git = counting
        try:
            self.checker.check()
            fetches = calls.count("fetch")
            self.checker.check()
        finally:
            updater._run_git = original
        self.assertEqual(fetches, 1)
        self.assertEqual(calls.count("fetch"), 1)

    def test_changed_requirements_are_flagged(self):
        self.publish("New package", {"requirements.txt": "requests\nnumpy\n"})
        info = self.checker.check()
        self.assertTrue(info.requirements_changed)
        self.assertIn(
            "They are installed while the bot restarts.",
            self.checker.format_notification(info),
        )

    def test_install_pulls_and_the_folder_is_current_afterwards(self):
        self.publish("Ship it")
        info = self.checker.check()
        new_sha = self.checker.install(info)
        self.assertEqual(new_sha, git(self.folder, "rev-parse", "HEAD"))
        self.assertEqual(new_sha, git(self.dev, "rev-parse", "HEAD"))
        with open(os.path.join(self.folder, "feature.txt")) as f:
            self.assertEqual(f.read().strip(), "Ship it")
        self.assertIsNone(self.checker.pending)
        self.assertIsNone(self.checker.check())

    def test_local_commit_not_on_github_is_not_an_update(self):
        write(os.path.join(self.folder, "local.txt"), "mine\n")
        git(self.folder, "add", ".")
        git(self.folder, "commit", "-m", "Local only")
        self.assertIsNone(self.checker.check())

    def test_diverged_copy_is_reported_and_not_installed(self):
        write(os.path.join(self.folder, "local.txt"), "mine\n")
        git(self.folder, "add", ".")
        git(self.folder, "commit", "-m", "Local only")
        self.publish("Remote change")
        info = self.checker.check()
        self.assertFalse(info.can_fast_forward)
        self.assertIn("updated manually", self.checker.format_notification(info))
        with self.assertRaises(updater.UpdateError):
            self.checker.install(info)

    def test_local_edits_that_clash_make_the_pull_fail_cleanly(self):
        write(os.path.join(self.folder, "feature.txt"), "edited by hand\n")
        self.publish("Remote edit of the same file")
        info = self.checker.check()
        with self.assertRaises(updater.UpdateError) as caught:
            self.checker.install(info)
        self.assertLess(len(str(caught.exception)), 300)
        with open(os.path.join(self.folder, "feature.txt")) as f:
            self.assertEqual(f.read(), "edited by hand\n")

    def test_folder_that_is_not_a_clone(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        app_vars.directory = plain
        with self.assertRaises(updater.UpdateError) as caught:
            self.checker.check()
        self.assertIn("not a Git clone", str(caught.exception))

    def test_folder_inside_another_repository(self):
        inner = os.path.join(self.folder, "inner")
        os.makedirs(inner)
        app_vars.directory = inner
        with self.assertRaises(updater.UpdateError) as caught:
            self.checker.check()
        self.assertIn("not the root", str(caught.exception))

    def test_unreachable_remote_fails_quickly_with_a_message(self):
        self.bot.config.updater.remote = "nowhere"
        git(self.folder, "remote", "add", "nowhere", os.path.join(self.root, "missing.git"))
        with self.assertRaises(updater.UpdateError) as caught:
            self.checker.check()
        self.assertTrue(str(caught.exception))

    def test_credentials_in_urls_are_never_shown(self):
        text = "fatal: unable to access 'https://user:secret-token@github.com/a/b/': error"
        message = updater._short_message(text)
        self.assertNotIn("secret-token", message)
        self.assertIn("github.com/a/b", message)

    def test_each_update_is_announced_once(self):
        self.checker._can_announce = lambda: True
        self.publish("First news")
        self.checker._cycle()
        self.checker._cycle()
        self.assertEqual(len(self.bot.ttclient.messages), 1)
        text, _, message_type = self.bot.ttclient.messages[0]
        self.assertEqual(message_type, 2)  # a channel message
        self.assertIn("First news", text)
        self.publish("Second news")
        self.checker._cycle()
        self.assertEqual(len(self.bot.ttclient.messages), 2)

    def test_an_offline_bot_announces_at_the_next_check(self):
        self.publish("While offline")
        self.checker._can_announce = lambda: False
        self.checker._cycle()
        self.assertEqual(self.bot.ttclient.messages, [])
        self.checker._can_announce = lambda: True
        self.checker._cycle()
        self.assertEqual(len(self.bot.ttclient.messages), 1)

    def test_a_failing_check_is_logged_once(self):
        app_vars.directory = os.path.join(self.root)
        with self.assertLogs(level="WARNING") as logs:
            self.checker._cycle()
            self.checker._cycle()
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(self.bot.ttclient.messages, [])


class RecordingRestart:
    calls = []

    def __init__(self, command_processor):
        pass

    def __call__(self, arg, user):
        RecordingRestart.calls.append((arg, user))


@skipUnless(GIT, "git is not available")
class InstallCommandTests(UpdaterTestBase):
    def setUp(self):
        super().setUp()
        processor = SimpleNamespace(
            bot=self.bot, cache=None, cache_manager=None, config=self.bot.config,
            config_manager=self.bot.config_manager, module_manager=None, player=None,
            service_manager=None, task_processor=None, ttclient=self.bot.ttclient,
            translator=self.bot.translator,
        )
        self.bot.update_checker = self.checker
        self.command = admin_commands.InstallUpdateCommand(processor)
        self.command.command_processor = processor
        self.user = SimpleNamespace(id=7, nickname="admin")
        self._real_restart = admin_commands.RestartCommand
        admin_commands.RestartCommand = RecordingRestart
        RecordingRestart.calls = []

    def tearDown(self):
        admin_commands.RestartCommand = self._real_restart
        super().tearDown()

    def test_up_to_date_replies_and_does_not_restart(self):
        reply = self.command("", self.user)
        self.assertIn("up to date (version {})".format(app_vars.app_version), reply)
        self.assertEqual(RecordingRestart.calls, [])
        self.assertFalse(self.bot.is_updating)

    def test_install_updates_marks_and_restarts(self):
        self.publish("Ship it")
        self.assertIsNone(self.command("", self.user))
        self.assertEqual(len(RecordingRestart.calls), 1)
        self.assertTrue(self.bot.is_updating)
        self.assertTrue(os.path.exists(os.path.join(self.root, "update_success")))
        sent = [text for text, _, _ in self.bot.ttclient.messages]
        self.assertTrue(any("Installing the update" in text for text in sent))
        self.assertTrue(any("Restarting now" in text for text in sent))
        self.assertEqual(git(self.folder, "rev-parse", "HEAD"), git(self.dev, "rev-parse", "HEAD"))

    def test_changed_requirements_are_installed_during_the_restart(self):
        self.publish("New package", {"requirements.txt": "requests\nnumpy\n"})
        self.assertIsNone(self.command("", self.user))
        # The packages are not installed by the running bot: it asks the next start
        # to do it (tools/apply_update.py), then restarts.
        self.assertTrue(
            os.path.exists(os.path.join(self.folder, "data", "requirements_pending"))
        )
        self.assertEqual(len(RecordingRestart.calls), 1)
        self.assertTrue(self.bot.is_updating)
        sent = [text for text, _, _ in self.bot.ttclient.messages]
        self.assertTrue(any("installs the required Python packages" in text for text in sent))
        self.assertEqual(git(self.folder, "rev-parse", "HEAD"), git(self.dev, "rev-parse", "HEAD"))

    def test_the_marker_names_the_version_that_was_running(self):
        self.publish("Ship it")
        self.command("", self.user)
        with open(os.path.join(self.root, "update_success"), encoding="utf-8") as marker:
            data = json.load(marker)
        self.assertEqual(data["from_version"], app_vars.app_version)
        self.assertEqual(len(data["to_commit"]), 7)

    def test_failed_install_replies_with_the_reason_and_does_not_restart(self):
        write(os.path.join(self.folder, "feature.txt"), "edited by hand\n")
        self.publish("Remote edit of the same file")
        reply = self.command("", self.user)
        self.assertIn("could not be installed", reply)
        self.assertEqual(RecordingRestart.calls, [])
        self.assertFalse(self.bot.is_updating)

    def test_not_a_clone_replies_with_the_reason(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        app_vars.directory = plain
        reply = self.command("", self.user)
        self.assertIn("Unable to check for updates", reply)
        self.assertIn("not a Git clone", reply)

    def test_two_installations_cannot_overlap(self):
        self.checker.install_lock.acquire()
        try:
            reply = self.command("", self.user)
        finally:
            self.checker.install_lock.release()
        self.assertIn("already being installed", reply)
