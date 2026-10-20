"""The stand-in for the native TeamTalk library (tests/__init__.py).

Without it every test that imports ``bot`` fails on a fresh clone, because the binding
loads TeamTalk5.dll / libTeamTalk5.so the moment it is imported.
"""
import ctypes
import importlib.util
import os
import sys
from pathlib import Path
from unittest import TestCase, skipIf
from unittest.mock import patch

import tests

ROOT = Path(__file__).resolve().parents[1]
REAL_SDK = os.environ.get("TTBOT_TEST_REAL_SDK") == "1"


def load_binding(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "TeamTalkPy" / "TeamTalk5.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@skipIf(REAL_SDK, "TTBOT_TEST_REAL_SDK=1: the real library is used")
class StandInTests(TestCase):
    def test_the_binding_is_loaded_without_the_native_library(self):
        import TeamTalkPy

        self.assertIsInstance(TeamTalkPy.TeamTalk5.dll, tests._FakeNativeLibrary)
        self.assertTrue(hasattr(TeamTalkPy, "TeamTalk"))
        self.assertTrue(hasattr(TeamTalkPy, "AudioBlock"))

    def test_the_real_enums_and_structures_are_kept(self):
        import TeamTalkPy

        self.assertEqual(TeamTalkPy.SoundSystem.SOUNDSYSTEM_WASAPI, 5)  # as in TeamTalk5.py
        self.assertEqual(TeamTalkPy.TT_STRLEN, 512)

    def test_importing_it_leaves_ctypes_and_os_as_they_were(self):
        before = (ctypes.cdll, getattr(os, "add_dll_directory", None))
        with patch.dict(sys.modules):
            del sys.modules["TeamTalkPy"]
            for name in [n for n in sys.modules if n.startswith("TeamTalkPy.")]:
                del sys.modules[name]
            tests._import_teamtalk_binding()
        self.assertEqual((ctypes.cdll, getattr(os, "add_dll_directory", None)), before)

    def test_a_native_call_is_a_mock_and_never_reaches_a_library(self):
        import TeamTalkPy

        function = TeamTalkPy.TeamTalk5.dll.TT_GetVersion
        function.return_value = "5.23"
        self.assertEqual(function(), "5.23")

    def test_the_windows_branch_loads_even_when_the_sdk_folder_is_missing(self):
        """On Windows the binding adds <bot folder>\\TeamTalk_DLL to the DLL search path; a
        fresh clone has no such folder and Windows may refuse it."""

        def refuse(path):
            raise FileNotFoundError(3, "The system cannot find the path specified", path)

        with patch.object(sys, "platform", "win32"), \
                patch.object(os, "add_dll_directory", refuse, create=True), \
                patch.object(ctypes, "cdll", tests._FakeLibraryLoader()):
            with self.assertRaises(FileNotFoundError):
                load_binding("tt5_windows_unguarded")
        with patch.object(sys, "platform", "win32"), \
                patch.object(os, "add_dll_directory", lambda path: tests._NoDllDirectory(), create=True), \
                patch.object(ctypes, "cdll", tests._FakeLibraryLoader()):
            module = load_binding("tt5_windows_guarded")
        self.assertIs(module.TTCHAR, ctypes.c_wchar)

    def test_the_windows_branch_asks_for_the_library_by_its_windows_name(self):
        requested = []

        class Loader(tests._FakeLibraryLoader):
            def __getattr__(self, name):
                requested.append(name)
                return super().__getattr__(name)

        with patch.object(sys, "platform", "win32"), \
                patch.object(os, "add_dll_directory", lambda path: tests._NoDllDirectory(), create=True), \
                patch.object(ctypes, "cdll", Loader()):
            load_binding("tt5_windows_name")
        self.assertIn("TeamTalk5", requested)
