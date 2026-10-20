"""Test package bootstrap.

The bot imports ``TeamTalkPy``, and the official binding loads the native TeamTalk 5
library (``TeamTalk5.dll`` on Windows, ``libTeamTalk5.so`` on Linux) the moment it is
imported. A fresh clone does not have that library yet, and unit tests must not need it:
they never talk to a server, and the real library shows its trial banner and the
"Trial expired" window.

So, unless ``TTBOT_TEST_REAL_SDK=1`` is set, the binding is imported here with a stand-in
for the native library. The binding itself (structures, enums, classes) stays the real
one; only the calls into the native code are replaced by mocks.
"""
import ctypes
import os
import sys
from unittest import mock

_REAL_SDK_VARIABLE = "TTBOT_TEST_REAL_SDK"


class _FakeNativeLibrary:
    """Answers every ``dll.TT_Something`` with a mock that accepts argtypes/restype."""

    def __init__(self) -> None:
        self._functions = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        function = self._functions.get(name)
        if function is None:
            function = self._functions[name] = mock.MagicMock(name=name)
        return function


class _FakeLibraryLoader:
    """Stands in for ``ctypes.cdll`` while the binding is imported."""

    def __init__(self) -> None:
        self.library = _FakeNativeLibrary()

    def LoadLibrary(self, name):  # noqa: N802 - the name ctypes uses
        return self.library

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self.library


class _NoDllDirectory:
    """What os.add_dll_directory returns, for a folder that is not really added."""

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _import_teamtalk_binding() -> None:
    if os.environ.get(_REAL_SDK_VARIABLE) == "1" or "TeamTalkPy" in sys.modules:
        return
    real_loader = ctypes.cdll
    ctypes.cdll = _FakeLibraryLoader()
    # On Windows the binding adds the SDK's folder (<bot folder>\TeamTalk_DLL, which a fresh
    # clone does not have) to the DLL search path, and Windows may refuse a folder that
    # is not there. There is no DLL to find, so nothing is added.
    real_add = getattr(os, "add_dll_directory", None)
    if real_add is not None:
        os.add_dll_directory = lambda path: _NoDllDirectory()
    try:
        import TeamTalkPy  # noqa: F401
    except ImportError:
        # The repository root is not on sys.path (tests started from another folder);
        # the tests that need the bot will say so with a normal ImportError.
        pass
    finally:
        ctypes.cdll = real_loader
        if real_add is not None:
            os.add_dll_directory = real_add


_import_teamtalk_binding()
