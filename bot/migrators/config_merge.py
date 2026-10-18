"""Adds the settings a newer version introduced, and changes nothing else."""

import copy
from typing import Any, Dict, List, Tuple


def add_missing(
    current: Dict[str, Any], defaults: Dict[str, Any], _path: str = ""
) -> Tuple[Dict[str, Any], List[str]]:
    """Returns (merged, added).

    ``merged`` has every key of ``defaults``, in the order of ``defaults``, with
    the value from ``current`` where there is one and the default where there is
    not. Keys that only ``current`` has stay, after the others. Values the user
    set, lists included, are never touched. ``added`` lists the dotted names of
    what was missing; a whole new section is named once.
    """
    merged: Dict[str, Any] = {}
    added: List[str] = []
    for key, default in defaults.items():
        where = _path + key
        if key not in current:
            merged[key] = copy.deepcopy(default)
            added.append(where)
        elif isinstance(default, dict) and isinstance(current[key], dict):
            merged[key], inner = add_missing(current[key], default, where + ".")
            added.extend(inner)
        else:
            merged[key] = current[key]
    for key, value in current.items():
        if key not in merged:
            merged[key] = value
    return merged, added


def count_settings(data: Any) -> int:
    """Number of individual settings inside a value (a section counts its leaves)."""
    if isinstance(data, dict):
        return sum(count_settings(value) for value in data.values()) or 1
    return 1


def count_added(merged: Dict[str, Any], added: List[str]) -> int:
    total = 0
    for dotted in added:
        value: Any = merged
        for part in dotted.split("."):
            value = value[part]
        total += count_settings(value)
    return total
