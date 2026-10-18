import importlib.util
import os
import sys
from types import ModuleType

from bot import app_vars


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *("COM%d" % i for i in range(1, 10)),
    *("LPT%d" % i for i in range(1, 10)),
}


def clean_file_name(file_name: str) -> str:
    """Make a name safe on Windows and Linux alike."""
    for char in ["\\", "/", "%", "*", "?", ":", '"', "|", "<", ">"] + [
        chr(i) for i in range(1, 32)
    ]:
        file_name = file_name.replace(char, "_")
    # Windows silently drops trailing dots and spaces, which breaks later lookups.
    file_name = file_name.strip().rstrip(". ")
    stem = file_name.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        file_name = "_" + file_name
    return file_name


def get_abs_path(file_name: str) -> str:
    return os.path.join(app_vars.directory, file_name)


def load_python_module(name: str, path: str) -> ModuleType:
    """Imports a Python file (or the __init__.py of a package) under ``name``.

    ``SourceFileLoader(...).load_module()`` is deprecated since Python 3.6 and is on
    the removal list of Python 3.15. ``spec_from_file_location`` + ``exec_module`` is
    the replacement the Python documentation names; it works on every version the bot
    supports (3.10 to 3.15) and registers the module in ``sys.modules`` like before.
    """
    is_package = os.path.basename(path) == "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name,
        path,
        submodule_search_locations=[os.path.dirname(path) or "."] if is_package else None,
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load the module {!r} from {!r}".format(name, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module
