import os
import tempfile
from pathlib import Path
from unittest import TestCase

from bot.ffmpeg_locator import windows_package_manager_candidates


class WindowsPackageManagerLocationTests(TestCase):
    def _touch(self, root, *parts):
        path = Path(root, *parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ")
        return str(path)

    def test_finds_the_winget_link_and_the_package_folder(self):
        with tempfile.TemporaryDirectory() as local:
            link = self._touch(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe")
            package = self._touch(
                local, "Microsoft", "WinGet", "Packages",
                "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe", "ffmpeg-8.1-full_build", "bin", "ffmpeg.exe",
            )
            found = windows_package_manager_candidates({"LOCALAPPDATA": local})
        self.assertEqual(found, [link, package])

    def test_finds_chocolatey_and_machine_wide_winget(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as programs:
            choco = self._touch(data, "chocolatey", "bin", "ffmpeg.exe")
            machine = self._touch(programs, "WinGet", "Packages", "Gyan.FFmpeg_x", "ffmpeg-7", "bin", "ffmpeg.exe")
            found = windows_package_manager_candidates({"ProgramData": data, "ProgramFiles": programs})
        self.assertEqual(found, [machine, choco])

    def test_nothing_installed_gives_an_empty_list(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(windows_package_manager_candidates({"LOCALAPPDATA": empty, "ProgramData": empty}), [])

    def test_missing_environment_variables_do_not_crash(self):
        self.assertIsInstance(windows_package_manager_candidates({}), list)
