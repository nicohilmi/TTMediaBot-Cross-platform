import json
import os
import sys
from typing import Any, Dict, Optional

from bot import app_vars, utils
from bot.config.models import CONFIG_VERSION, ConfigModel
from bot.migrators import config_migrator

import portalocker

config_data_type = Dict[str, Any]


def dump_model(model: Any) -> config_data_type:
    """The settings of a model as a plain dictionary, on pydantic 1 and 2 alike.

    ``BaseModel.dict()`` still works in pydantic 2 but is deprecated there (it prints
    a warning); ``model_dump()`` is the current name.
    """
    model_dump = getattr(model, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    return model.dict()


def save_default_file() -> None:
    with open(utils.get_abs_path("config_default.json"), "w", encoding="UTF-8") as f:
        json.dump(dump_model(ConfigModel()), f, indent=4, ensure_ascii=False)


class ConfigManager:
    version = CONFIG_VERSION

    def __init__(self, file_name: Optional[str]) -> None:
        # What the update of config.json did at this start (None without a file);
        # see bot/migrators/config_migrator.py.
        self.migration = None
        if file_name:
            if os.path.isfile(file_name):
                self.file_name = os.path.abspath(file_name)
                config_dict = config_migrator.migrate(self, self._load())
                self.config_dir = os.path.dirname(self.file_name)
                self._lock()
            else:
                sys.exit("Incorrect configuration file path")
        else:
            self.config_dir = app_vars.directory
            config_dict = {}
        self.config: ConfigModel = ConfigModel(**config_dict)

    def default_data(self) -> config_data_type:
        """Every setting with its default value, in the order of the model."""
        return dump_model(ConfigModel())

    def _dump(self, data: config_data_type):
        with open(self.file_name, "w", encoding="UTF-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _load(self):
        with open(self.file_name, "r", encoding="UTF-8") as f:
            try:
                return json.load(f)
            except json.decoder.JSONDecodeError as e:
                sys.exit("Syntax error in configuration file: " + str(e))

    def _lock(self):
        self.file_locker = portalocker.Lock(
            self.file_name,
            timeout=0,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        )
        try:
            self.file_locker.acquire()
        except portalocker.exceptions.LockException:
            raise PermissionError()

    def close(self):
        self.file_locker.release()

    def save(self):
        self.file_locker.release()
        self._dump(dump_model(self.config))
        self.file_locker.acquire()
