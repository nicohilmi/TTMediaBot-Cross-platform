import os

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
