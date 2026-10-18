import copy
import json
import os
import tempfile
from unittest import TestCase, skipUnless

from bot.migrators import config_migrator
from bot.migrators.config_merge import add_missing, count_added

DEFAULTS = {
    "config_version": 2,
    "general": {"language": "en", "blocked_commands": []},
    "player": {"default_volume": 50},
    "ai": {"enabled": True, "gemini": {"api_key": "", "model": "gemini-x"}},
}


class FakeManager:
    version = 2

    def __init__(self, path, defaults=DEFAULTS):
        self.file_name = path
        self._defaults = defaults
        self.migration = None
        self.fail_to_write = False

    def default_data(self):
        return copy.deepcopy(self._defaults)

    def _dump(self, data):
        if self.fail_to_write:
            raise PermissionError("read-only")
        with open(self.file_name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


class AddMissingTests(TestCase):
    def test_only_what_is_missing_is_added(self):
        merged, added = add_missing(
            {"general": {"language": "id"}}, DEFAULTS
        )
        self.assertEqual(merged["general"], {"language": "id", "blocked_commands": []})
        self.assertEqual(sorted(added), ["ai", "config_version", "general.blocked_commands", "player"])

    def test_values_of_the_user_are_never_touched(self):
        mine = {
            "config_version": 1,
            "general": {"language": "id", "blocked_commands": ["dl", "dlv"]},
            "player": {"default_volume": 10},
            "ai": {"enabled": False, "gemini": {"api_key": "SECRET", "model": "mine"}},
        }
        merged, added = add_missing(copy.deepcopy(mine), DEFAULTS)
        self.assertEqual(merged, mine)
        self.assertEqual(added, [])

    def test_unknown_keys_stay_and_the_order_follows_the_defaults(self):
        merged, _ = add_missing({"zzz": 1, "player": {"x": 2, "default_volume": 5}}, DEFAULTS)
        self.assertEqual(list(merged)[:4], ["config_version", "general", "player", "ai"])
        self.assertEqual(list(merged)[-1], "zzz")
        self.assertEqual(merged["player"], {"default_volume": 5, "x": 2})

    def test_defaults_are_copied_not_shared(self):
        merged, _ = add_missing({}, DEFAULTS)
        merged["general"]["blocked_commands"].append("dl")
        self.assertEqual(DEFAULTS["general"]["blocked_commands"], [])

    def test_a_setting_that_changed_type_is_left_for_validation(self):
        merged, _ = add_missing({"ai": "oops"}, DEFAULTS)
        self.assertEqual(merged["ai"], "oops")

    def test_added_settings_are_counted_one_by_one(self):
        merged, added = add_missing({}, DEFAULTS)
        self.assertEqual(count_added(merged, ["ai"]), 3)  # enabled, api_key, model


class MigrateTests(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def read(self, path=None):
        with open(path or self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_an_old_file_gets_the_new_settings_and_keeps_its_own(self):
        old = {"config_version": 1, "general": {"language": "id", "blocked_commands": ["dl"]},
               "player": {"default_volume": 25}}
        self.write(old)
        manager = FakeManager(self.path)
        data = config_migrator.migrate(manager, self.read())
        written = self.read()
        self.assertEqual(data, written)
        self.assertEqual(written["config_version"], 2)
        self.assertEqual(written["general"]["language"], "id")
        self.assertEqual(written["general"]["blocked_commands"], ["dl"])
        self.assertEqual(written["player"]["default_volume"], 25)
        self.assertEqual(written["ai"]["gemini"]["model"], "gemini-x")
        result = manager.migration
        self.assertEqual((result.from_version, result.to_version), (1, 2))
        self.assertEqual(result.added, ["ai"])
        self.assertEqual(result.added_count, 3)
        self.assertTrue(result.written)
        self.assertEqual(self.read(self.path + ".bak"), old)

    def test_a_file_without_a_version_is_version_zero(self):
        self.write({"general": {"language": "id"}})
        manager = FakeManager(self.path)
        config_migrator.migrate(manager, self.read())
        self.assertEqual(manager.migration.from_version, 0)
        self.assertEqual(self.read()["general"]["language"], "id")
        self.assertEqual(self.read()["config_version"], 2)

    def test_a_current_file_is_not_rewritten(self):
        self.write(DEFAULTS)
        manager = FakeManager(self.path)
        before = os.stat(self.path).st_mtime_ns
        config_migrator.migrate(manager, self.read())
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)
        self.assertFalse(os.path.exists(self.path + ".bak"))
        self.assertEqual(manager.migration.added, [])
        self.assertFalse(manager.migration.written)

    def test_a_second_start_changes_nothing(self):
        self.write({"general": {"language": "id"}})
        config_migrator.migrate(FakeManager(self.path), self.read())
        first = self.read()
        manager = FakeManager(self.path)
        config_migrator.migrate(manager, self.read())
        self.assertEqual(self.read(), first)
        self.assertEqual(manager.migration.added, [])

    def test_a_file_from_a_newer_bot_stops_the_start(self):
        self.write({"config_version": 3})
        with self.assertRaises(SystemExit) as caught:
            config_migrator.migrate(FakeManager(self.path), self.read())
        self.assertIn("newer version", str(caught.exception))
        self.assertEqual(self.read(), {"config_version": 3})

    def test_an_invalid_version_stops_the_start(self):
        for bad in ("2", -1, True, 1.5):
            self.write({"config_version": bad})
            with self.assertRaises(SystemExit):
                config_migrator.migrate(FakeManager(self.path), self.read())

    def test_an_unwritable_file_does_not_stop_the_bot(self):
        self.write({"general": {"language": "id"}})
        manager = FakeManager(self.path)
        manager.fail_to_write = True
        with self.assertLogs(level="WARNING"):
            data = config_migrator.migrate(manager, self.read())
        self.assertEqual(data["ai"]["gemini"]["model"], "gemini-x")
        self.assertFalse(manager.migration.written)

    def test_a_registered_step_can_rename_a_setting(self):
        defaults = copy.deepcopy(DEFAULTS)
        defaults["config_version"] = 3
        defaults["general"] = {"locale": "en"}

        def to_v3(data):
            general = data.setdefault("general", {})
            if "language" in general:
                general["locale"] = general.pop("language")
            return config_migrator.update_version(data, 3)

        manager = FakeManager(self.path, defaults)
        manager.version = 3
        config_migrator.migrate_functs[3] = to_v3
        try:
            self.write({"config_version": 2, "general": {"language": "id"}})
            config_migrator.migrate(manager, self.read())
        finally:
            del config_migrator.migrate_functs[3]
        self.assertEqual(self.read()["general"], {"locale": "id"})


try:
    from bot.config.models import ConfigModel
except Exception:  # pydantic missing
    ConfigModel = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@skipUnless(ConfigModel, "pydantic is not available")
class RepositoryFilesTests(TestCase):
    def test_config_default_json_matches_the_model(self):
        with open(os.path.join(ROOT, "config_default.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), ConfigModel().dict())

    def test_config_json_has_every_setting_of_the_model(self):
        with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
            shipped = json.load(f)
        merged, added = add_missing(shipped, ConfigModel().dict())
        self.assertEqual(added, [])
