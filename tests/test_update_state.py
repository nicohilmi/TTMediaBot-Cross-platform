import importlib.util
import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import TestCase

from bot import app_vars, update_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "ttbot_apply_update", os.path.join(ROOT, "tools", "apply_update.py")
)
apply_update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_update)


def translate(text):
    return text


class Runner:
    def __init__(self, returncode=0, output="", error=None):
        self.returncode, self.output, self.error = returncode, output, error
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if self.error:
            raise self.error
        return SimpleNamespace(returncode=self.returncode, stdout=self.output)


class ApplyUpdateTests(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.out = []
        with open(os.path.join(self.root, "requirements.txt"), "w") as f:
            f.write("requests\n")

    def pending(self):
        os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
        update_state.request_requirements_install(self.root)

    def run_pending(self, runner):
        return apply_update.run_pending(self.root, runner, self.out.append, settle=0)

    def result_file(self):
        with open(os.path.join(self.root, "data", "requirements_result.json")) as f:
            return json.load(f)

    def test_the_two_modules_agree_on_the_file_names(self):
        self.assertEqual(update_state.REQUIREMENTS_PENDING_NAME, apply_update.PENDING_NAME)
        self.assertEqual(update_state.REQUIREMENTS_RESULT_NAME, apply_update.RESULT_NAME)

    def test_nothing_happens_without_a_request(self):
        runner = Runner()
        self.assertIsNone(self.run_pending(runner))
        self.assertEqual(runner.commands, [])

    def test_a_request_installs_the_requirements_once(self):
        self.pending()
        runner = Runner()
        self.assertEqual(self.run_pending(runner), {"ok": True, "error": ""})
        command, kwargs = runner.commands[0]
        self.assertEqual(command[1:5], ["-m", "pip", "install", "-r"])
        self.assertEqual(command[5], os.path.join(self.root, "requirements.txt"))
        self.assertEqual(kwargs["cwd"], self.root)
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "requirements_pending")))
        self.assertEqual(self.result_file(), {"ok": True, "error": ""})
        self.assertIsNone(self.run_pending(runner))  # not repeated
        self.assertEqual(len(runner.commands), 1)

    def test_a_failure_is_recorded_and_not_repeated(self):
        self.pending()
        runner = Runner(1, "Collecting x\nERROR: No matching distribution found for x\n")
        result = self.run_pending(runner)
        self.assertFalse(result["ok"])
        self.assertIn("No matching distribution", result["error"])
        self.assertFalse(self.result_file()["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "data", "requirements_pending")))

    def test_a_timeout_and_a_missing_python_are_failures_too(self):
        self.pending()
        timeout = Runner(error=subprocess.TimeoutExpired("pip", 900))
        self.assertIn("did not finish", self.run_pending(timeout)["error"])
        self.pending()
        missing = Runner(error=FileNotFoundError("no python"))
        self.assertIn("could not be started", self.run_pending(missing)["error"])

    def test_a_missing_requirements_file_is_a_failure(self):
        os.remove(os.path.join(self.root, "requirements.txt"))
        self.pending()
        runner = Runner()
        self.assertIn("not found", self.run_pending(runner)["error"])
        self.assertEqual(runner.commands, [])


class UpdateStateTests(TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_the_marker_remembers_the_running_version(self):
        update_state.write_success_marker(self.root, "abc1234", "def5678")
        info = update_state.read_success_marker(update_state.success_path(self.root))
        self.assertEqual(info, {"from_version": app_vars.app_version,
                                "from_commit": "abc1234", "to_commit": "def5678"})

    def test_the_marker_of_older_versions_is_still_understood(self):
        path = update_state.success_path(self.root)
        with open(path, "w") as f:
            f.write("ok")
        self.assertEqual(update_state.read_success_marker(path), {})
        self.assertEqual(update_state.read_success_marker(path + ".missing"), {})

    def test_the_message_after_an_update_names_the_versions(self):
        text = update_state.completion_message(translate, {"from_version": "4.1"})
        lines = text.split("\n")
        self.assertEqual(lines[0], "Update completed successfully! I am back online.")
        self.assertEqual(
            lines[1], "TTMediaBot was updated from version 4.1 to version {}.".format(app_vars.app_version)
        )
        self.assertEqual(len(lines), 2)

    def test_without_a_known_old_version_it_says_the_current_one(self):
        text = update_state.completion_message(translate, {})
        self.assertIn("TTMediaBot is now version {}.".format(app_vars.app_version), text)

    def test_new_settings_are_mentioned_only_when_there_were_some(self):
        none = SimpleNamespace(added_count=0)
        some = SimpleNamespace(added_count=22)
        self.assertNotIn("setting", update_state.completion_message(translate, {}, none))
        self.assertIn("22 new setting(s) were added to config.json. Your own settings were kept.",
                      update_state.completion_message(translate, {}, some))

    def test_a_failed_package_installation_is_read_once(self):
        os.makedirs(os.path.join(self.root, "data"))
        path = os.path.join(self.root, "data", "requirements_result.json")
        with open(path, "w") as f:
            json.dump({"ok": False, "error": "no network"}, f)
        self.assertEqual(update_state.take_requirements_failure(self.root), "no network")
        self.assertIsNone(update_state.take_requirements_failure(self.root))

    def test_a_successful_installation_is_silent(self):
        os.makedirs(os.path.join(self.root, "data"))
        path = os.path.join(self.root, "data", "requirements_result.json")
        with open(path, "w") as f:
            json.dump({"ok": True, "error": ""}, f)
        self.assertIsNone(update_state.take_requirements_failure(self.root))
        self.assertFalse(os.path.exists(path))
