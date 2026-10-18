"""Brings config.json up to date, the way an app or an OS keeps your settings.

An update that needs new settings only adds them: everything the user has set
stays as it is, the file is never reset. Before the file is changed it is copied
to ``config.json.bak``.

Adding missing settings is automatic and needs no code here. A change that
cannot be expressed as "add what is missing" (a setting renamed, removed or
given another meaning) is written as a function, registered in
``migrate_functs`` under the config_version it brings the file to, and
CONFIG_VERSION in bot/config/models.py is raised to that number.
"""

from __future__ import annotations

import copy
import logging
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, TYPE_CHECKING

from bot.migrators.config_merge import add_missing, count_added

if TYPE_CHECKING:
    from bot.config import ConfigManager

config_data_type = Dict[str, Any]


@dataclass
class MigrationResult:
    from_version: int
    to_version: int
    # Settings (or whole sections) the file did not have, by dotted name.
    added: List[str] = field(default_factory=list)
    # How many individual settings those are.
    added_count: int = 0
    # Where the copy of the old file was saved ("" when nothing was written).
    backup: str = ""
    written: bool = False


def to_v1(config_data: config_data_type) -> config_data_type:
    return update_version(config_data, 1)


def to_v2(config_data: config_data_type) -> config_data_type:
    # Version 4.1.2 added the "ai" section. Adding it needs no code: every missing
    # setting is filled in from the defaults by migrate() below.
    return update_version(config_data, 2)


migrate_functs: Dict[int, Callable[[config_data_type], config_data_type]] = {
    1: to_v1,
    2: to_v2,
}


def migrate(
    config_manager: ConfigManager,
    config_data: config_data_type,
) -> config_data_type:
    target = config_manager.version
    version = config_data.get("config_version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        sys.exit("Error: invalid config_version value")
    if version > target:
        sys.exit(
            "Error: config.json was written by a newer version of TTMediaBot "
            "(config_version {} is higher than {}). Update the bot, or restore "
            "the copy named config.json.bak.".format(version, target)
        )
    original = copy.deepcopy(config_data)
    data = config_data
    for step in sorted(migrate_functs):
        if step > version:
            data = migrate_functs[step](data)
    merged, added = add_missing(data, config_manager.default_data())
    merged["config_version"] = target
    added = [name for name in added if name != "config_version"]
    result = MigrationResult(
        from_version=version,
        to_version=target,
        added=added,
        added_count=count_added(merged, added),
    )
    config_manager.migration = result
    if merged != original:
        _write(config_manager, merged, result)
    return merged


def _write(
    config_manager: ConfigManager, merged: config_data_type, result: MigrationResult
) -> None:
    path = config_manager.file_name
    backup = path + ".bak"
    try:
        shutil.copy2(path, backup)
        result.backup = backup
        config_manager._dump(merged)
    except OSError as error:
        # The bot still runs: missing settings take their default values anyway.
        logging.warning(f"[Config] could not update {path}: {error}")
        return
    result.written = True
    if result.added:
        logging.info(
            f"[Config] {result.added_count} new setting(s) added to {path} "
            f"({', '.join(result.added)}); your own settings were kept. "
            f"The previous file was saved as {backup}"
        )
    else:
        logging.info(
            f"[Config] {path} brought to version {result.to_version}; "
            f"the previous file was saved as {backup}"
        )


def update_version(config_data: config_data_type, version: int) -> config_data_type:
    _config_data = {"config_version": version}
    _config_data.update(config_data)
    return _config_data
