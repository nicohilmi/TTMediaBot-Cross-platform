"""Downloads of tools/setup_deps.py: browser identities, 7-Zip, the SDK folder, temp files.

Nothing here touches the network: every opener, extractor and checker is replaced.
"""
import http.server
import os
import tempfile
import threading
import urllib.error
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from tools import setup_deps as sd
from tests.test_setup_deps import OFFICIAL_PAGE, _Response

ROOT = Path(__file__).resolve().parents[1]


def refused(code):
    return urllib.error.HTTPError("http://x", code, "refused", {}, None)


class _PoolCase(TestCase):
    """Gives every test a known pool of identities and restores the real one afterwards."""

    def setUp(self):
        sd.reset_user_agents()
        sd._POOL.agents = ["agent-A", "agent-B", "agent-C"]
        sd._POOL.index = 0
        self.addCleanup(sd.reset_user_agents)
        # no real pause between two identities, and never the outside programs (curl,
        # PowerShell) behind the back of a test that did not ask for them
        pause = patch.object(sd, "REFUSAL_PAUSE", 0)
        pause.start()
        self.addCleanup(pause.stop)


class UserAgentFileTests(TestCase):
    def test_the_shipped_list_is_usable(self):
        agents = sd.load_user_agents(ROOT / "tools" / "user_agents.txt")
        self.assertGreaterEqual(len(agents), 20)
        self.assertEqual(len(agents), len(set(agents)), "duplicate identities")
        for agent in agents:
            self.assertTrue(agent.startswith("Mozilla/5.0 ("), agent)
            self.assertLess(len(agent), 300, agent)
            self.assertTrue(agent.isascii() and agent.isprintable(), agent)

    def test_comments_blank_lines_and_duplicates_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents.txt"
            path.write_text("# a comment\n\n  one  \ntwo\none\n   \n#three\n", encoding="utf-8")
            self.assertEqual(sd.load_user_agents(path), ["one", "two"])

    def test_a_missing_or_empty_file_falls_back_to_the_built_in_identities(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sd.load_user_agents(Path(tmp) / "none.txt"), list(sd.FALLBACK_USER_AGENTS))
            empty = Path(tmp) / "empty.txt"
            empty.write_text("# only a comment\n", encoding="utf-8")
            self.assertEqual(sd.load_user_agents(empty), list(sd.FALLBACK_USER_AGENTS))

    def test_the_pool_is_read_once_and_keeps_every_identity(self):
        sd.reset_user_agents()
        first = list(sd.user_agent_pool().agents)
        self.assertEqual(sorted(first), sorted(sd.load_user_agents()))
        self.assertEqual(sd.user_agent_pool().agents, first)

    def test_the_old_tool_identity_is_gone(self):
        text = (ROOT / "tools" / "setup_deps.py").read_text(encoding="utf-8")
        self.assertNotIn("compatible; TTMediaBot-setup", text)


class OpenUrlTests(_PoolCase):
    def make_opener(self, answers):
        seen = []

        def opener(request, timeout):
            seen.append((request.get_header("User-agent"), request.get_header("Accept"), request.get_method(), timeout))
            item = answers.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        opener.seen = seen
        return opener

    def test_a_refused_identity_is_replaced_by_the_next_one(self):
        opener = self.make_opener([refused(403), refused(429), _Response(b"ok")])
        with sd.open_url("http://x", opener, 5) as response:
            self.assertEqual(response.read(), b"ok")
        self.assertEqual([seen[0] for seen in opener.seen], ["agent-A", "agent-B", "agent-C"])
        self.assertEqual({seen[1] for seen in opener.seen}, {"*/*"})
        self.assertEqual(opener.seen[0][3], 5)

    def test_the_identity_that_worked_is_used_first_next_time(self):
        opener = self.make_opener([refused(403), _Response(b"one"), _Response(b"two")])
        sd.open_url("http://x", opener)
        sd.open_url("http://x", opener)
        self.assertEqual([seen[0] for seen in opener.seen], ["agent-A", "agent-B", "agent-B"])

    def test_406_is_treated_like_403(self):
        opener = self.make_opener([refused(406), _Response(b"ok")])
        sd.open_url("http://x", opener)
        self.assertEqual(len(opener.seen), 2)

    def test_the_non_standard_454_of_bearware_is_treated_like_403(self):
        # The report: "HTTP Error 454" from https://bearware.dk/?page_id=419 ended the
        # download at once, because only 403, 406 and 429 were answered with another identity.
        opener = self.make_opener([refused(454), refused(454), _Response(b"ok")])
        with sd.open_url("http://x", opener) as response:
            self.assertEqual(response.read(), b"ok")
        self.assertEqual([seen[0] for seen in opener.seen], ["agent-A", "agent-B", "agent-C"])

    def test_every_4xx_answer_but_404_and_410_means_not_you(self):
        for code in (400, 401, 403, 405, 406, 429, 451, 454, 499):
            with self.subTest(code=code):
                self.assertTrue(sd.is_refusal(code))
        for code in (200, 301, 404, 410, 500, 502, 503):
            with self.subTest(code=code):
                self.assertFalse(sd.is_refusal(code))

    def test_410_is_final_like_404(self):
        opener = self.make_opener([refused(410), _Response(b"never")])
        with self.assertRaises(urllib.error.HTTPError):
            sd.open_url("http://x", opener)
        self.assertEqual(len(opener.seen), 1)

    def test_a_browser_like_set_of_headers_is_sent(self):
        seen = []

        def opener(request, timeout):
            seen.append({key.lower(): value for key, value in request.header_items()})
            return _Response(b"ok")

        sd.open_url("http://x", opener, referer="https://bearware.dk/?page_id=419")
        self.assertEqual(seen[0]["referer"], "https://bearware.dk/?page_id=419")
        self.assertEqual(seen[0]["accept-language"], "en-US,en;q=0.9")
        self.assertEqual(seen[0]["user-agent"], "agent-A")
        seen.clear()
        sd.open_url("http://x", opener)
        self.assertNotIn("referer", seen[0])

    def test_there_is_a_pause_between_two_identities_but_not_after_the_last(self):
        pauses = []
        opener = self.make_opener([refused(454), refused(454), refused(454)])
        with patch.object(sd, "REFUSAL_PAUSE", 0.25), self.assertRaises(urllib.error.HTTPError):
            sd.open_url("http://x", opener, sleep=pauses.append)
        self.assertEqual(pauses, [0.25, 0.25])

    def test_a_refused_answer_is_closed(self):
        closed = []

        class Answer(urllib.error.HTTPError):
            def close(self):
                closed.append(self.code)

        opener = self.make_opener([Answer("http://x", 454, "refused", {}, None), _Response(b"ok")])
        sd.open_url("http://x", opener)
        self.assertEqual(closed, [454])

    def test_a_404_or_a_server_error_is_raised_at_once(self):
        for code in (404, 500, 503):
            with self.subTest(code=code):
                sd.reset_user_agents()
                sd._POOL.agents = ["agent-A", "agent-B"]
                opener = self.make_opener([refused(code), _Response(b"never")])
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    sd.open_url("http://x", opener)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(len(opener.seen), 1)

    def test_when_every_identity_is_refused_the_last_answer_is_raised(self):
        opener = self.make_opener([refused(403), refused(403), refused(429)])
        with self.assertRaises(urllib.error.HTTPError) as raised:
            sd.open_url("http://x", opener)
        self.assertEqual(raised.exception.code, 429)
        self.assertEqual(len(opener.seen), 3)

    def test_no_more_than_the_maximum_number_of_identities_is_tried(self):
        sd._POOL.agents = ["agent-%d" % n for n in range(20)]
        opener = self.make_opener([refused(403) for _ in range(20)])
        with self.assertRaises(urllib.error.HTTPError):
            sd.open_url("http://x", opener)
        self.assertEqual(len(opener.seen), sd.MAX_AGENT_TRIES)

    def test_the_method_is_passed_on(self):
        opener = self.make_opener([_Response(b"")])
        sd.open_url("http://x", opener, method="HEAD")
        self.assertEqual(opener.seen[0][2], "HEAD")

    def test_http_get_switches_identity_without_using_up_a_retry(self):
        opener = self.make_opener([refused(403), _Response(b"page")])
        self.assertEqual(sd.http_get("http://x", opener=opener, retries=1, sleep=lambda s: None), b"page")
        self.assertEqual(len(opener.seen), 2)

    def test_http_get_still_retries_server_errors_with_the_same_identity_pool(self):
        opener = self.make_opener([refused(503), _Response(b"page")])
        self.assertEqual(sd.http_get("http://x", opener=opener, retries=2, sleep=lambda s: None), b"page")

    def test_download_archive_switches_identity_too(self):
        body = sd.SEVEN_ZIP_MAGIC + b"\x00" * (sd.MIN_ARCHIVE_BYTES + 5)
        opener = self.make_opener([refused(403), _Response(body, {"Content-Length": str(len(body))})])
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "say"):
            destination = Path(tmp) / "sdk.7z"
            sd.download_archive("http://x/sdk.7z", destination, opener=opener, sleep=lambda s: None)
            self.assertTrue(destination.read_bytes().startswith(sd.SEVEN_ZIP_MAGIC))
        self.assertEqual([seen[0] for seen in opener.seen], ["agent-A", "agent-B"])


class _PickyHandler(http.server.BaseHTTPRequestHandler):
    """A download site that turns some browser identities away, like the real one may do."""

    seen = []
    archive = sd.SEVEN_ZIP_MAGIC + b"\x00" * (sd.MIN_ARCHIVE_BYTES + 10)

    def log_message(self, *args):
        pass

    def do_GET(self):
        agent = self.headers.get("User-Agent", "")
        _PickyHandler.seen.append((self.path, agent))
        if self.path == "/tool.7z" and "blocked" in agent:
            body, code = b"", 403
        elif self.path == "/limit.7z" and "blocked" in agent:
            body, code = b"", 429
        elif self.path in ("/tool.7z", "/limit.7z"):
            body, code = self.archive, 200
        elif self.path == "/page":
            body, code = (b"hello", 200) if "blocked" not in agent else (b"", 403)
        else:
            body, code = b"", 404
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class PickySiteTests(_PoolCase):
    """The real urllib against a local server: the header that is sent is the one chosen."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PickyHandler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        super().setUp()
        _PickyHandler.seen.clear()
        sd._POOL.agents = ["Mozilla/5.0 blocked-one", "Mozilla/5.0 blocked-two", "Mozilla/5.0 welcome"]

    def test_the_archive_download_gets_through_after_two_refusals(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "say"):
            destination = Path(tmp) / "tool.7z"
            sd.download_archive(self.base + "/tool.7z", destination, retries=1, sleep=lambda s: None)
            self.assertTrue(destination.read_bytes().startswith(sd.SEVEN_ZIP_MAGIC))
        self.assertEqual(
            [agent for _path, agent in _PickyHandler.seen],
            ["Mozilla/5.0 blocked-one", "Mozilla/5.0 blocked-two", "Mozilla/5.0 welcome"],
        )

    def test_a_429_is_answered_with_another_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "say"):
            sd.download_archive(self.base + "/limit.7z", Path(tmp) / "limit.7z", retries=1, sleep=lambda s: None)
        self.assertEqual(_PickyHandler.seen[-1][1], "Mozilla/5.0 welcome")

    def test_pages_are_read_with_the_identity_that_worked_before(self):
        self.assertEqual(sd.http_get(self.base + "/page", retries=1), b"hello")
        self.assertEqual(sd.http_get(self.base + "/page", retries=1), b"hello")
        agents = [agent for _path, agent in _PickyHandler.seen]
        self.assertEqual(agents, ["Mozilla/5.0 blocked-one", "Mozilla/5.0 blocked-two", "Mozilla/5.0 welcome", "Mozilla/5.0 welcome"])

    def test_a_missing_file_is_still_final(self):
        with self.assertRaises(sd.SetupError):
            sd.http_get(self.base + "/nothing", retries=3, sleep=lambda s: None)
        self.assertEqual(len(_PickyHandler.seen), 1)


class PortableSevenZipTests(_PoolCase):
    GOOD = b"MZ" + b"\x00" * 200_000

    def test_the_program_is_downloaded_into_the_given_folder(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "looks_like_seven_zip", return_value=True):
            path = sd.download_portable_seven_zip(Path(tmp) / "tools", opener=lambda r, timeout: _Response(self.GOOD))
            self.assertEqual(path, Path(tmp) / "tools" / "7zr.exe")
            self.assertEqual(path.read_bytes(), self.GOOD)

    def test_the_next_address_is_used_when_the_first_fails(self):
        urls = []

        def opener(request, timeout):
            urls.append(request.full_url)
            if len(urls) == 1:
                raise refused(404)
            return _Response(self.GOOD)

        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "looks_like_seven_zip", return_value=True):
            self.assertIsNotNone(sd.download_portable_seven_zip(Path(tmp), opener=opener))
        self.assertEqual(urls, list(sd.SEVEN_ZIP_PORTABLE_URLS[:2]))

    def test_an_answer_that_is_not_a_program_is_thrown_away(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = b"<html>" + b"x" * 200_000
            result = sd.download_portable_seven_zip(Path(tmp), opener=lambda r, timeout: _Response(html))
            self.assertIsNone(result)
            self.assertFalse((Path(tmp) / "7zr.exe").exists())

    def test_a_file_of_the_wrong_size_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(sd.download_portable_seven_zip(Path(tmp), opener=lambda r, timeout: _Response(b"MZ")))

    def test_every_address_failing_gives_none(self):
        def opener(request, timeout):
            raise urllib.error.URLError("no internet")

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(sd.download_portable_seven_zip(Path(tmp), opener=opener))

    def test_looks_like_seven_zip_checks_header_size_and_the_name_it_prints(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "7zr.exe"
            exe.write_bytes(self.GOOD)
            with patch.object(sd, "run_quiet", return_value=(7, "7-Zip (r) 24.08 (x86) : Copyright (c) 1999-2024 Igor Pavlov")):
                self.assertTrue(sd.looks_like_seven_zip(exe))
            with patch.object(sd, "run_quiet", return_value=(0, "some other program")):
                self.assertFalse(sd.looks_like_seven_zip(exe))
            exe.write_bytes(b"ZM" + b"\x00" * 200_000)
            with patch.object(sd, "run_quiet", return_value=(7, "7-Zip")):
                self.assertFalse(sd.looks_like_seven_zip(exe))
            self.assertFalse(sd.looks_like_seven_zip(Path(tmp) / "missing.exe"))


class ExtractWithPortableSevenZipTests(TestCase):
    """extract_archive: the last resort on Windows when no tool can open the archive."""

    def patches(self, **overrides):
        values = dict(
            _extract_with_py7zr="py7zr is not installed",
            seven_zip_executables=[],
            seven_zip_install_plans=[],
        )
        values.update(overrides)
        stack = [
            patch.object(sd, "_extract_with_py7zr", return_value=values["_extract_with_py7zr"]),
            patch.object(sd, "seven_zip_executables", return_value=values["seven_zip_executables"]),
            patch.object(sd, "seven_zip_install_plans", return_value=values["seven_zip_install_plans"]),
            patch.object(sd.shutil, "which", return_value=None),
            patch.object(sd, "say"),
        ]
        return stack

    def run_extract(self, system, portable, binary_result=None, allow_install=True):
        calls = {"portable_folder": None, "commands": []}

        def fake_download(folder, *args, **kwargs):
            calls["portable_folder"] = folder
            return portable

        def fake_binary(command):
            calls["commands"].append(list(command))
            return binary_result

        stack = self.patches() + [
            patch.object(sd, "download_portable_seven_zip", fake_download),
            patch.object(sd, "_extract_with_binary", fake_binary),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            archive, target = Path(tmp) / "a.7z", Path(tmp) / "unpacked_0"
            for item in stack:
                item.start()
            try:
                error = None
                try:
                    sd.extract_archive(archive, target, system, allow_install=allow_install)
                except sd.SetupError as exc:
                    error = exc
            finally:
                for item in reversed(stack):
                    item.stop()
            calls["tmp"], calls["archive"], calls["target"], calls["error"] = Path(tmp), archive, target, error
        return calls

    def test_windows_falls_back_to_the_portable_program_in_the_work_folder(self):
        calls = self.run_extract("windows", Path("C:/temp/7zr.exe"))
        self.assertIsNone(calls["error"])
        self.assertEqual(calls["portable_folder"], calls["tmp"])  # the folder that holds the unpacked one
        self.assertEqual(
            calls["commands"],
            [[str(Path("C:/temp/7zr.exe")), "x", "-y", "-o" + str(calls["target"]), str(calls["archive"])]],
        )

    def test_a_portable_program_that_fails_is_reported(self):
        calls = self.run_extract("windows", Path("7zr.exe"), binary_result="7zr.exe failed: bad archive")
        self.assertIsNotNone(calls["error"])
        self.assertIn("bad archive", str(calls["error"]))

    def test_no_download_possible_says_so(self):
        calls = self.run_extract("windows", None)
        self.assertIn("7zr.exe could not be downloaded", str(calls["error"]))

    def test_linux_and_check_only_runs_never_download_a_windows_program(self):
        for system, allow in (("linux", True), ("darwin", True), ("windows", False)):
            with self.subTest(system=system, allow_install=allow):
                calls = self.run_extract(system, Path("7zr.exe"), allow_install=allow)
                self.assertIsNone(calls["portable_folder"])
                self.assertIsNotNone(calls["error"])

    def test_installing_7zip_with_the_package_manager_still_comes_first(self):
        order = []
        state = {"installed": False}

        def binary(command):
            order.append("extract")
            return None if state["installed"] else "missing"

        def install(command):
            order.append("winget")
            state["installed"] = True
            return True

        def portable(folder, *a, **k):
            order.append("portable")
            return None

        stack = [
            patch.object(sd, "_extract_with_py7zr", return_value="py7zr is not installed"),
            patch.object(sd, "seven_zip_executables", return_value=["7z"]),
            patch.object(sd, "_extract_with_binary", binary),
            patch.object(sd.shutil, "which", return_value=None),
            patch.object(sd, "seven_zip_install_plans", return_value=[["winget", "install"]]),
            patch.object(sd, "run_visible", install),
            patch.object(sd, "download_portable_seven_zip", portable),
            patch.object(sd, "say"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for item in stack:
                item.start()
            try:
                sd.extract_archive(Path(tmp) / "a.7z", Path(tmp) / "out", "windows")
            finally:
                for item in reversed(stack):
                    item.stop()
        self.assertEqual(order, ["extract", "winget", "extract"])


class _SdkCase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = Path(self.tmp.name)
        self.said = []
        patcher = patch.object(sd, "say", side_effect=lambda m="": self.said.append(m))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.work_folders = []

    def fetch(self, url):
        return OFFICIAL_PAGE.encode()

    def download(self, url, path):
        self.work_folders.append(path.parent)
        path.write_bytes(b"archive")

    def make_extract(self, files):
        def extract(archive, target, system, allow_install=True):
            for name, content in files.items():
                path = target / "Library" / "TeamTalk_DLL" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

        return extract

    def run_flow(self, files, check):
        with patch.object(sd, "extract_archive", self.make_extract(files)), patch.object(sd, "check_library", check):
            return sd.setup_sdk(self.bot, "windows", "AMD64", fetch=self.fetch, download=self.download)


class SdkFolderTests(_SdkCase):
    """The SDK's Library/TeamTalk_DLL folder becomes <bot folder>/TeamTalk_DLL with the same three files."""

    THREE_FILES = {"TeamTalk5.dll": b"dll", "TeamTalk5.lib": b"import library", "TeamTalk.h": b"header"}
    OK = staticmethod(lambda path: sd.LibraryCheck(True, version="5.23.0.1"))

    def sdk_folder(self):
        return self.bot / "TeamTalk_DLL"

    def test_the_three_files_go_into_the_teamtalk_dll_folder_and_nothing_beside_the_bot(self):
        ok = self.run_flow(self.THREE_FILES, self.OK)
        self.assertTrue(ok)
        self.assertEqual(sorted(p.name for p in self.bot.iterdir()), ["TeamTalk_DLL"])
        self.assertEqual(sorted(p.name for p in self.sdk_folder().iterdir()), ["TeamTalk.h", "TeamTalk5.dll", "TeamTalk5.lib"])
        self.assertEqual((self.sdk_folder() / "TeamTalk5.lib").read_bytes(), b"import library")
        self.assertEqual((self.sdk_folder() / "TeamTalk.h").read_bytes(), b"header")

    def test_the_destination_is_inside_the_sdk_folder_on_every_system(self):
        for system, name in (("windows", "TeamTalk5.dll"), ("linux", "libTeamTalk5.so"), ("darwin", "libTeamTalk5.dylib")):
            with self.subTest(system=system):
                self.assertEqual(sd.sdk_destination(self.bot, system), self.bot / "TeamTalk_DLL" / name)

    def test_only_the_three_documented_files_are_kept(self):
        files = dict(self.THREE_FILES, **{"libhelper.dll": b"helper", "readme.txt": b"text", "TeamTalk5.exp": b"x"})
        ok = self.run_flow(files, self.OK)
        self.assertTrue(ok)
        self.assertEqual(sorted(p.name for p in self.sdk_folder().iterdir()), ["TeamTalk.h", "TeamTalk5.dll", "TeamTalk5.lib"])

    def test_a_release_without_lib_and_header_still_installs_the_dll(self):
        ok = self.run_flow({"TeamTalk5.dll": b"dll"}, self.OK)
        self.assertTrue(ok)
        self.assertEqual([p.name for p in self.sdk_folder().iterdir()], ["TeamTalk5.dll"])
        self.assertIn("TeamTalk5.lib, TeamTalk.h was not in the SDK folder", "\n".join(self.said))

    def test_no_backup_copies_stay_in_the_folder(self):
        self.sdk_folder().mkdir()
        for name in self.THREE_FILES:
            (self.sdk_folder() / name).write_bytes(b"previous")
        calls = {"n": 0}

        def check(path):
            calls["n"] += 1  # the first call looks at the installed (older) library
            return sd.LibraryCheck(True, version="5.11.0.1" if calls["n"] == 1 else "5.23.0.1")

        ok = self.run_flow(self.THREE_FILES, check)
        self.assertTrue(ok)
        self.assertEqual(sorted(p.name for p in self.sdk_folder().iterdir()), ["TeamTalk.h", "TeamTalk5.dll", "TeamTalk5.lib"])
        self.assertEqual((self.sdk_folder() / "TeamTalk5.dll").read_bytes(), b"dll")

    def test_the_library_is_checked_again_from_the_sdk_folder_of_the_bot(self):
        checked = []

        def check(path):
            checked.append(path)
            return sd.LibraryCheck(True, version="5.23.0.1")

        self.run_flow(self.THREE_FILES, check)
        self.assertEqual(checked[-1], self.sdk_folder() / "TeamTalk5.dll")
        self.assertEqual(len(checked), 2)  # the copy in the temporary folder, then the final copy

    def test_a_library_that_only_loads_inside_the_sdk_folder_is_reported_and_nothing_stays(self):
        def check(path):
            if path == self.sdk_folder() / "TeamTalk5.dll":
                return sd.LibraryCheck(False, problem="a library it depends on is missing: helper.dll")
            return sd.LibraryCheck(True, version="5.23.0.1")

        ok = self.run_flow(self.THREE_FILES, check)
        self.assertFalse(ok)
        text = "\n".join(self.said)
        self.assertIn("does not load from", text)
        self.assertIn("helper.dll", text)
        self.assertIn("Nothing was installed", text)
        self.assertIn("Do it by hand", text)
        self.assertEqual(list(self.bot.iterdir()), [], "a copy that cannot load must not stay behind, not even the folder")

    def test_the_previous_files_come_back_when_the_new_copy_cannot_load(self):
        self.sdk_folder().mkdir()
        (self.sdk_folder() / "TeamTalk5.dll").write_bytes(b"previous library")
        calls = {"n": 0}

        def check(path):
            calls["n"] += 1
            if path == self.sdk_folder() / "TeamTalk5.dll" and calls["n"] == 3:  # the final check only
                return sd.LibraryCheck(False, problem="a library it depends on is missing")
            return sd.LibraryCheck(True, version="5.11.0.1" if calls["n"] == 1 else "5.23.0.1")

        ok = self.run_flow(self.THREE_FILES, check)
        self.assertFalse(ok)
        self.assertEqual((self.sdk_folder() / "TeamTalk5.dll").read_bytes(), b"previous library")
        self.assertFalse((self.sdk_folder() / "TeamTalk5.lib").exists())
        self.assertFalse((self.sdk_folder() / "TeamTalk.h").exists())
        self.assertIn("previous files were put back", "\n".join(self.said))

    def test_sdk_extra_files_are_the_lib_and_the_header_only_and_only_on_windows(self):
        folder = self.bot / "Library" / "TeamTalk_DLL"
        folder.mkdir(parents=True)
        for name in ("TeamTalk5.dll", "b.dll", "A.DLL", "TeamTalk5.lib", "TeamTalk.h", "notes.txt"):
            (folder / name).write_bytes(b"x")
        names = [p.name for p in sd.sdk_extra_files(folder / "TeamTalk5.dll", "windows")]
        self.assertEqual(names, ["TeamTalk5.lib", "TeamTalk.h"])
        self.assertEqual(sd.sdk_extra_files(folder / "TeamTalk5.dll", "linux"), [])
        self.assertEqual(sd.sdk_extra_files(folder / "TeamTalk5.dll", "darwin"), [])

    def test_missing_sdk_files_lists_what_the_folder_lacks(self):
        destination = sd.sdk_destination(self.bot, "windows")
        self.assertEqual(sd.missing_sdk_files(destination, "windows"), ["TeamTalk5.dll", "TeamTalk5.lib", "TeamTalk.h"])
        destination.parent.mkdir()
        destination.write_bytes(b"x")
        self.assertEqual(sd.missing_sdk_files(destination, "windows"), ["TeamTalk5.lib", "TeamTalk.h"])
        self.assertEqual(sd.missing_sdk_files(destination, "linux"), [])


class LegacyRootLibraryTests(_SdkCase):
    """The first 4.2.x copied TeamTalk5.dll beside TTMediaBot.py; that copy moves into TeamTalk_DLL."""

    THREE_FILES = SdkFolderTests.THREE_FILES

    def sdk_folder(self):
        return self.bot / "TeamTalk_DLL"

    def test_an_old_copy_beside_the_bot_is_moved_into_the_sdk_folder_without_any_download(self):
        (self.bot / "TeamTalk5.dll").write_bytes(b"old dll")

        def no_download(url, path):
            raise sd.SetupError("offline")

        def fetch(url):
            raise sd.SetupError("offline")

        with patch.object(sd, "check_library", lambda path: sd.LibraryCheck(True, version="5.23.0.1")):
            ok = sd.setup_sdk(self.bot, "windows", "AMD64", fetch=fetch, download=no_download)
        self.assertTrue(ok, "the moved library works, so the run is a success even offline")
        self.assertFalse((self.bot / "TeamTalk5.dll").exists())
        self.assertEqual((self.sdk_folder() / "TeamTalk5.dll").read_bytes(), b"old dll")
        self.assertIn("Moved TeamTalk5.dll", "\n".join(self.said))

    def test_after_a_successful_install_the_old_copy_and_its_backup_are_removed(self):
        (self.bot / "TeamTalk5.dll").write_bytes(b"old dll")
        (self.bot / "TeamTalk5.dll.bak").write_bytes(b"older dll")
        ok = self.run_flow(self.THREE_FILES, lambda path: sd.LibraryCheck(True, version="5.23.0.1"))
        self.assertTrue(ok)
        self.assertEqual(sorted(p.name for p in self.bot.iterdir()), ["TeamTalk_DLL"])
        self.assertEqual((self.sdk_folder() / "TeamTalk5.dll").read_bytes(), b"dll")
        self.assertIn("Removed the old TeamTalk5.dll.bak", "\n".join(self.said))

    def test_a_copy_in_both_places_keeps_the_sdk_folder_one_and_drops_the_old_one(self):
        self.sdk_folder().mkdir()
        (self.sdk_folder() / "TeamTalk5.dll").write_bytes(b"new place")
        (self.bot / "TeamTalk5.dll").write_bytes(b"old place")
        for name in ("TeamTalk5.lib", "TeamTalk.h"):
            (self.sdk_folder() / name).write_bytes(b"x")
        ok = self.run_flow(self.THREE_FILES, lambda path: sd.LibraryCheck(True, version="5.23.0.1"))
        self.assertTrue(ok)
        self.assertFalse((self.bot / "TeamTalk5.dll").exists())
        self.assertTrue((self.sdk_folder() / "TeamTalk5.dll").is_file())

    def test_the_old_copy_is_kept_when_the_new_install_fails(self):
        (self.bot / "TeamTalk5.dll").write_bytes(b"old dll")

        def check(path):  # the moved library is fine, the downloaded one is not
            if path.read_bytes() == b"dll":
                return sd.LibraryCheck(False, problem="broken")
            return sd.LibraryCheck(True, version="5.11.0.1")

        ok = self.run_flow(self.THREE_FILES, check)
        self.assertTrue(ok, "the moved, working library is still there")
        self.assertEqual((self.sdk_folder() / "TeamTalk5.dll").read_bytes(), b"old dll")

    def test_check_only_reports_the_old_place_and_changes_nothing(self):
        (self.bot / "TeamTalk5.dll").write_bytes(b"old dll")
        ok = sd.setup_sdk(self.bot, "windows", "AMD64", check_only=True)
        self.assertFalse(ok)
        self.assertTrue((self.bot / "TeamTalk5.dll").is_file())
        self.assertFalse(self.sdk_folder().exists())
        self.assertIn("beside TTMediaBot.py", "\n".join(self.said))

    def test_an_up_to_date_library_without_lib_and_header_is_completed_by_a_download(self):
        self.sdk_folder().mkdir()
        (self.sdk_folder() / "TeamTalk5.dll").write_bytes(b"current dll")
        ok = self.run_flow(self.THREE_FILES, lambda path: sd.LibraryCheck(True, version="5.23.0.1"))
        self.assertTrue(ok)
        self.assertTrue(self.work_folders, "the SDK must be downloaded to bring the .lib and the header")
        self.assertEqual(sorted(p.name for p in self.sdk_folder().iterdir()), ["TeamTalk.h", "TeamTalk5.dll", "TeamTalk5.lib"])

    def test_a_complete_up_to_date_folder_downloads_nothing(self):
        self.sdk_folder().mkdir()
        for name in self.THREE_FILES:
            (self.sdk_folder() / name).write_bytes(b"x")
        ok = self.run_flow(self.THREE_FILES, lambda path: sd.LibraryCheck(True, version="5.23.0.1"))
        self.assertTrue(ok)
        self.assertEqual(self.work_folders, [])
        self.assertIn("already the newest release", "\n".join(self.said))


class TemporaryFilesTests(_SdkCase):
    def test_the_work_folder_is_in_the_temp_folder_and_removed_afterwards(self):
        ok = self.run_flow({"TeamTalk5.dll": b"dll"}, lambda path: sd.LibraryCheck(True, version="5.23.0.1"))
        self.assertTrue(ok)
        folder = self.work_folders[0]
        self.assertEqual(folder.parent.resolve(), Path(tempfile.gettempdir()).resolve())
        self.assertTrue(folder.name.startswith("ttsdk_"))
        self.assertFalse(folder.exists(), "the downloaded archive and the unpacked SDK must be deleted")

    def test_a_failed_run_leaves_nothing_behind_either(self):
        ok = self.run_flow({"TeamTalk5.dll": b"dll"}, lambda path: sd.LibraryCheck(False, problem="bad"))
        self.assertFalse(ok)
        self.assertFalse(self.work_folders[0].exists())
        self.assertEqual(list(self.bot.iterdir()), [])

    def test_temporary_directory_cleans_up_and_survives_a_locked_file(self):
        with sd.temporary_directory("ttsdk_test_") as name:
            folder = Path(name)
            (folder / "x.bin").write_bytes(b"x")
            self.assertTrue(folder.is_dir())
        self.assertFalse(folder.exists())


class ManualHelpTests(TestCase):
    def test_windows_help_gives_the_extract_copy_and_delete_commands(self):
        text = sd.manual_sdk_help("windows", Path("D:/TTMediaBot-master"), "no internet")
        self.assertIn("could not be set up automatically: no internet", text)
        self.assertIn("https://bearware.dk/?page_id=419", text)
        self.assertIn('7z x -y -o"%TEMP%\\ttsdk" tt5sdk_*_win64.7z', text)
        for name in ("TeamTalk5.dll", "TeamTalk5.lib", "TeamTalk.h"):
            self.assertIn('copy "%TEMP%\\ttsdk\\Library\\TeamTalk_DLL\\' + name + '"', text)
        self.assertIn(str(Path("D:/TTMediaBot-master") / "TeamTalk_DLL"), text)
        self.assertIn("does not go beside TTMediaBot.py", text)
        self.assertIn('dir /s /b "%TEMP%\\ttsdk\\TeamTalk5.dll"', text)
        self.assertIn('rmdir /s /q "%TEMP%\\ttsdk"', text)
        self.assertIn("30 day trial", text)

    def test_other_systems_keep_the_short_help(self):
        for system, library in (("linux", "libTeamTalk5.so"), ("darwin", "libTeamTalk5.dylib")):
            with self.subTest(system=system):
                text = sd.manual_sdk_help(system, Path("/opt/bot"), "x")
                self.assertIn(library, text)
                self.assertIn("7-Zip", text)
                self.assertNotIn("%TEMP%", text)


class InstallerMentionsSevenZipTests(TestCase):
    def test_the_windows_installer_says_that_7zip_is_set_up_when_needed(self):
        text = (ROOT / "install_windows.bat").read_text(encoding="utf-8")
        step = text[text.index("[6/6]"):]
        step = step[: step.index("setup_deps.py all")]
        self.assertIn("7-Zip", step)
        self.assertIn("Temp", step)
