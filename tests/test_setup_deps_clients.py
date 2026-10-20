"""The second chance of tools/setup_deps.py: curl and PowerShell when Python is refused.

The report behind these tests: on Windows the SDK was never downloaded, because
bearware.dk answered the script with the non-standard "HTTP Error 454" and the script
neither tried another browser identity nor another program. Nothing here uses the
internet. Two classes start a local server that refuses what urllib sends and run the
real curl (and, on Windows, the real PowerShell) against it; they are skipped where the
program does not exist.
"""
import http.server
import os
import shutil
import tempfile
import threading
import urllib.error
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

from tools import setup_deps as sd
from tests.test_setup_deps_downloads import _PoolCase, refused
from tests.test_setup_deps import _Response

ARCHIVE = sd.SEVEN_ZIP_MAGIC + b"\x00" * (sd.MIN_ARCHIVE_BYTES + 10)


def curl(path="/usr/bin/curl"):
    return sd.ExternalClient("curl", path)


def powershell(path="powershell.exe"):
    return sd.ExternalClient("powershell", path)


class ExternalClientDetectionTests(TestCase):
    def test_linux_and_macos_know_curl_only(self):
        with patch.object(sd, "IS_WINDOWS", False):
            found = sd.external_clients(lambda name: "/usr/bin/curl" if name == "curl" else None)
            self.assertEqual(found, [sd.ExternalClient("curl", "/usr/bin/curl")])
            self.assertEqual(sd.external_clients(lambda name: None), [])

    def test_windows_prefers_the_programs_that_ship_with_windows(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sd, "IS_WINDOWS", True), \
                patch.dict(os.environ, {"SystemRoot": root}):
            system32 = Path(root) / "System32"
            (system32 / "WindowsPowerShell" / "v1.0").mkdir(parents=True)
            (system32 / "curl.exe").write_bytes(b"x")
            (system32 / "WindowsPowerShell" / "v1.0" / "powershell.exe").write_bytes(b"x")
            found = sd.external_clients(lambda name: "C:/other/" + name)
            self.assertEqual(
                found,
                [
                    sd.ExternalClient("curl", str(system32 / "curl.exe")),
                    sd.ExternalClient("powershell", str(system32 / "WindowsPowerShell" / "v1.0" / "powershell.exe")),
                ],
            )

    def test_windows_without_those_files_looks_on_path(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sd, "IS_WINDOWS", True), \
                patch.dict(os.environ, {"SystemRoot": root}):
            found = sd.external_clients(lambda name: "C:/tools/" + name if name in ("curl.exe", "pwsh") else None)
            self.assertEqual([c.name for c in found], ["curl", "powershell"])
            self.assertEqual(found[1].path, "C:/tools/pwsh")


class ExternalCommandTests(TestCase):
    def test_the_curl_command_is_a_list_with_one_element_per_argument(self):
        command = sd.external_command(
            curl(), "https://x/y?a=1&b=2", Path("out file.bin"), "Mozilla/5.0 (X) Gecko", "https://x/", 120
        )
        self.assertEqual(command[0], "/usr/bin/curl")
        self.assertEqual(command[command.index("--user-agent") + 1], "Mozilla/5.0 (X) Gecko")
        self.assertEqual(command[command.index("--referer") + 1], "https://x/")
        self.assertEqual(command[command.index("--max-time") + 1], "120")
        self.assertEqual(command[command.index("--output") + 1], str(Path("out file.bin")))
        self.assertEqual(command[-1], "https://x/y?a=1&b=2")
        self.assertIn("--location", command)
        self.assertNotIn("--ssl-no-revoke", command)

    def test_curl_without_a_referer_and_with_revocation_check_off(self):
        command = sd.external_command(curl(), "https://x", Path("o"), "A", None, 30, no_revoke=True)
        self.assertNotIn("--referer", command)
        self.assertIn("--ssl-no-revoke", command)

    def test_the_powershell_command_runs_the_script_file_with_named_parameters(self):
        command = sd.external_command(
            powershell(), "https://x/y?a=1", Path("o.bin"), "Agent (X)", None, 60, script=Path("s.ps1")
        )
        self.assertEqual(command[0], "powershell.exe")
        self.assertEqual(command[command.index("-File") + 1], "s.ps1")
        self.assertEqual(command[command.index("-Uri") + 1], "https://x/y?a=1")
        self.assertEqual(command[command.index("-Destination") + 1], "o.bin")
        self.assertEqual(command[command.index("-Identity") + 1], "Agent (X)")
        self.assertEqual(command[command.index("-Seconds") + 1], "60")
        self.assertEqual(command[command.index("-ExecutionPolicy") + 1], "Bypass")

    def test_the_powershell_script_is_plain_ascii(self):
        sd.POWERSHELL_FETCH.encode("ascii")  # a script file without a byte order mark must be safe
        self.assertIn("Invoke-WebRequest", sd.POWERSHELL_FETCH)
        self.assertIn("-UseBasicParsing", sd.POWERSHELL_FETCH)


class RunExternalFetchTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "page.bin"
        self.commands = []

    def runner(self, *answers, write=b"body"):
        answers = list(answers)

        def run(command, timeout):
            self.commands.append(list(command))
            code, output = answers.pop(0)
            if write is not None and code == 0 and output.endswith("HTTP 200"):
                self.target.write_bytes(write)
            return code, output

        return run

    def fetch(self, client, run):
        return sd.run_external_fetch(client, "https://x/p", self.target, "Agent", None, 30, run)

    def test_success_needs_exit_code_0_status_200_and_a_file(self):
        self.assertEqual(self.fetch(curl(), self.runner((0, "HTTP 200"))), (None, 200))
        self.assertEqual(self.target.read_bytes(), b"body")

    def test_a_refusal_is_reported_with_its_status(self):
        problem, status = self.fetch(curl(), self.runner((0, "HTTP 454")))
        self.assertEqual((problem, status), ("curl: HTTP 454", 454))
        self.assertFalse(self.target.exists())

    def test_a_network_error_is_reported_with_the_programs_own_words(self):
        problem, status = self.fetch(curl(), self.runner((6, "curl: (6) Could not resolve host: www.bearware.dk")))
        self.assertIsNone(status)
        self.assertIn("Could not resolve host", problem)

    def test_an_empty_answer_with_exit_code_0_is_not_a_success(self):
        problem, status = self.fetch(curl(), self.runner((0, "HTTP 200"), write=b""))
        self.assertIsNotNone(problem)

    def test_an_old_file_is_not_mistaken_for_the_new_download(self):
        self.target.write_bytes(b"left over from an earlier try")
        problem, status = self.fetch(curl(), self.runner((0, "HTTP 454")))
        self.assertIsNotNone(problem)
        self.assertFalse(self.target.exists())

    def test_windows_curl_asks_again_without_the_revocation_check(self):
        broken = (35, "curl: (35) schannel: CRYPT_E_NO_REVOCATION_CHECK (0x80092012) - unable to check")
        with patch.object(sd, "IS_WINDOWS", True):
            result = self.fetch(curl("curl.exe"), self.runner(broken, (0, "HTTP 200")))
        self.assertEqual(result, (None, 200))
        self.assertNotIn("--ssl-no-revoke", self.commands[0])
        self.assertIn("--ssl-no-revoke", self.commands[1])

    def test_other_systems_do_not_turn_the_revocation_check_off(self):
        broken = (35, "curl: (35) revocation check failed")
        with patch.object(sd, "IS_WINDOWS", False):
            problem, _status = self.fetch(curl(), self.runner(broken))
        self.assertEqual(len(self.commands), 1)
        self.assertIn("revocation", problem)

    def test_an_ordinary_failure_is_not_asked_again_without_the_revocation_check(self):
        with patch.object(sd, "IS_WINDOWS", True):
            self.fetch(curl("curl.exe"), self.runner((0, "HTTP 454")))
        self.assertEqual(len(self.commands), 1)

    def test_powershell_gets_its_script_next_to_the_target(self):
        self.fetch(powershell(), self.runner((0, "HTTP 200")))
        script = Path(self.tmp.name) / "ttbot_fetch.ps1"
        self.assertEqual(script.read_text(encoding="ascii"), sd.POWERSHELL_FETCH)
        self.assertEqual(self.commands[0][self.commands[0].index("-File") + 1], str(script))

    def test_the_status_printed_by_powershell_is_understood(self):
        problem, status = self.fetch(powershell(), self.runner((2, "HTTP 454 The remote server returned an error")))
        self.assertEqual((problem, status), ("powershell: HTTP 454", 454))


class FetchExternalTests(_PoolCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "out.bin"

    def test_no_program_available_says_so(self):
        problems = sd.fetch_external("https://x", self.target, clients=[])
        self.assertEqual(len(problems), 1)
        self.assertIn("no curl or PowerShell", problems[0])

    def test_a_refusal_is_answered_with_the_next_identity(self):
        agents = []

        def run(command, timeout):
            agent = command[command.index("--user-agent") + 1]
            agents.append(agent)
            if agent != "agent-C":
                return 0, "HTTP 454"
            self.target.write_bytes(b"ok")
            return 0, "HTTP 200"

        self.assertEqual(sd.fetch_external("https://x", self.target, clients=[curl()], run=run), [])
        self.assertEqual(agents, ["agent-A", "agent-B", "agent-C"])

    def test_every_refusal_of_every_program_is_listed(self):
        def run(command, timeout):
            return 0, "HTTP 454"

        problems = sd.fetch_external("https://x", self.target, clients=[curl(), powershell()], run=run)
        self.assertEqual(problems, ["curl: HTTP 454"] * sd.EXTERNAL_AGENT_TRIES + ["powershell: HTTP 454"] * sd.EXTERNAL_AGENT_TRIES)

    def test_a_failure_that_is_not_a_refusal_goes_to_the_next_program_at_once(self):
        calls = []

        def run(command, timeout):
            calls.append(command[0])
            if command[0] == "/usr/bin/curl":
                return 6, "curl: (6) Could not resolve host"
            self.target.write_bytes(b"ok")
            return 0, "HTTP 200"

        problems = sd.fetch_external(
            "https://x", self.target, clients=[curl(), powershell("/ps")], run=run
        )
        self.assertEqual(problems, [])
        self.assertEqual(calls, ["/usr/bin/curl", "/ps"])

    def test_a_missing_file_is_not_asked_again_with_other_identities(self):
        calls = []

        def run(command, timeout):
            calls.append(command)
            return 0, "HTTP 404"

        problems = sd.fetch_external("https://x", self.target, clients=[curl()], run=run)
        self.assertEqual(problems, ["curl: HTTP 404"])
        self.assertEqual(len(calls), 1)


class HttpGetSecondChanceTests(_PoolCase):
    def test_python_refused_so_the_outside_programs_are_asked(self):
        opener = lambda request, timeout: (_ for _ in ()).throw(refused(454))  # noqa: E731
        with patch.object(sd, "external_get", return_value=(b"page from curl", [])) as outside:
            data = sd.http_get("https://x", opener=opener, retries=1, sleep=lambda s: None, external=True)
        self.assertEqual(data, b"page from curl")
        outside.assert_called_once()

    def test_the_error_names_what_python_and_the_other_programs_said(self):
        opener = lambda request, timeout: (_ for _ in ()).throw(refused(454))  # noqa: E731
        with patch.object(sd, "external_get", return_value=(None, ["curl: HTTP 454", "powershell: HTTP 454"])):
            with self.assertRaises(sd.SetupError) as raised:
                sd.http_get("https://x/page", opener=opener, retries=1, sleep=lambda s: None, external=True)
        message = str(raised.exception)
        self.assertTrue(message.startswith("could not read https://x/page: "), message)
        for part in ("HTTP Error 454", "curl: HTTP 454", "powershell: HTTP 454"):
            self.assertIn(part, message)

    def test_a_missing_file_does_not_wake_the_outside_programs(self):
        opener = lambda request, timeout: (_ for _ in ()).throw(refused(404))  # noqa: E731
        with patch.object(sd, "external_get", side_effect=AssertionError("asked")):
            with self.assertRaises(sd.SetupError):
                sd.http_get("https://x", opener=opener, retries=3, sleep=lambda s: None, external=True)

    def test_an_injected_opener_never_wakes_them_unless_asked(self):
        opener = lambda request, timeout: (_ for _ in ()).throw(refused(454))  # noqa: E731
        with patch.object(sd, "external_get", side_effect=AssertionError("asked")):
            with self.assertRaises(sd.SetupError):
                sd.http_get("https://x", opener=opener, retries=1, sleep=lambda s: None)

    def test_a_network_error_is_answered_by_them_too(self):
        def opener(request, timeout):
            raise urllib.error.URLError("certificate verify failed")

        with patch.object(sd, "external_get", return_value=(b"ok", [])):
            self.assertEqual(sd.http_get("https://x", opener=opener, retries=1, external=True), b"ok")

    def test_the_other_page_addresses_only_try_python(self):
        seen = {}

        def fake_get(url, **kwargs):
            seen.update(kwargs)
            return b"x"

        # the real fetcher without retries and without outside programs ...
        real = sd._single_try(sd.http_get)
        with patch.object(sd, "http_get", fake_get):
            real("https://x")
        self.assertEqual(seen, {"retries": 1, "external": False})
        # ... while an injected one (a test) is used as it is
        injected = lambda url: b"x"  # noqa: E731
        self.assertIs(sd._single_try(injected), injected)


class DownloadSecondChanceTests(_PoolCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name) / "sdk.7z"
        said = patch.object(sd, "say")
        said.start()
        self.addCleanup(said.stop)

    def refusing(self, request, timeout):
        raise refused(454)

    def test_curl_finishes_a_download_that_python_was_refused(self):
        def outside(url, target, referer, timeout, **kwargs):
            target.write_bytes(ARCHIVE)
            return []

        with patch.object(sd, "fetch_external", side_effect=outside) as called:
            sd.download_archive("https://x/sdk.7z", self.destination, opener=self.refusing, retries=1, external=True)
        self.assertEqual(self.destination.read_bytes(), ARCHIVE)
        self.assertFalse(self.destination.with_suffix(".7z.part").exists())
        self.assertEqual(called.call_args.args[2], sd.SDK_PAGES[0], "the download page is the referer")
        self.assertEqual(called.call_args.args[3], sd.EXTERNAL_DOWNLOAD_TIMEOUT)

    def test_a_page_instead_of_the_archive_is_not_installed(self):
        def outside(url, target, referer, timeout, **kwargs):
            target.write_bytes(b"<html>" + b"x" * (sd.MIN_ARCHIVE_BYTES + 5))
            return []

        with patch.object(sd, "fetch_external", side_effect=outside):
            with self.assertRaises(sd.SetupError) as raised:
                sd.download_archive("https://x/sdk.7z", self.destination, opener=self.refusing, retries=1, external=True)
        self.assertIn("not send a 7z archive", str(raised.exception))
        self.assertIn("HTTP Error 454", str(raised.exception))
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.with_suffix(".7z.part").exists(), "no half file may stay behind")

    def test_every_attempt_is_named_when_everything_fails(self):
        with patch.object(sd, "fetch_external", return_value=["curl: HTTP 454", "powershell: HTTP 454"]):
            with self.assertRaises(sd.SetupError) as raised:
                sd.download_archive("https://x/sdk.7z", self.destination, opener=self.refusing, retries=1, external=True)
        message = str(raised.exception)
        self.assertTrue(message.startswith("download of https://x/sdk.7z failed: "), message)
        for part in ("HTTP Error 454", "curl: HTTP 454", "powershell: HTTP 454"):
            self.assertIn(part, message)

    def test_a_missing_file_does_not_wake_the_outside_programs(self):
        def missing(request, timeout):
            raise refused(404)

        with patch.object(sd, "fetch_external", side_effect=AssertionError("asked")):
            with self.assertRaises(sd.SetupError):
                sd.download_archive("https://x/sdk.7z", self.destination, opener=missing, retries=1, external=True)

    def test_a_download_that_python_can_do_never_wakes_them(self):
        body = ARCHIVE
        opener = lambda request, timeout: _Response(body, {"Content-Length": str(len(body))})  # noqa: E731
        with patch.object(sd, "fetch_external", side_effect=AssertionError("asked")):
            sd.download_archive("https://x/sdk.7z", self.destination, opener=opener, retries=1, external=True)
        self.assertEqual(self.destination.read_bytes(), body)


class _RefusePythonHandler(http.server.BaseHTTPRequestHandler):
    """A site like the one in the report: it answers 454 to what urllib sends (urllib asks
    for "Connection: close"), and serves what curl or PowerShell ask for."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get("Connection", "").lower() == "close":
            self.send_response(454)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/missing.7z":
            body, code = b"", 404
        elif self.path.endswith(".7z"):
            body, code = ARCHIVE, 200
        else:
            body, code = b"<a href='tt5sdk_v5.23a_win64.7z'>download</a>", 200
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _LocalSiteCase(_PoolCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RefusePythonHandler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        super().setUp()
        said = patch.object(sd, "say")
        said.start()
        self.addCleanup(said.stop)


# The programs of this computer, read once: the tests below replace sd.external_clients.
_REAL_CLIENTS = sd.external_clients()


def _real_client(name):
    return next((c for c in _REAL_CLIENTS if c.name == name), None)


@skipUnless(_real_client("curl"), "curl is not installed")
class RealCurlTests(_LocalSiteCase):
    """The real urllib is refused with 454; the real curl gets the file."""

    def test_python_alone_is_refused_by_the_local_site(self):
        with self.assertRaises(sd.SetupError) as raised:
            sd.http_get(self.base + "/page", retries=1, external=False)
        self.assertIn("454", str(raised.exception))

    def test_a_page_is_read_through_curl(self):
        with patch.object(sd, "external_clients", lambda: [_real_client("curl")]):
            data = sd.http_get(self.base + "/page", retries=1)
        self.assertIn(b"tt5sdk_v5.23a_win64.7z", data)

    def test_the_archive_is_downloaded_through_curl_and_checked(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "external_clients", lambda: [_real_client("curl")]):
            destination = Path(tmp) / "sdk.7z"
            sd.download_archive(self.base + "/sdk.7z", destination, retries=1)
            self.assertEqual(destination.read_bytes(), ARCHIVE)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["sdk.7z"])

    def test_a_missing_file_is_reported_and_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "external_clients", lambda: [_real_client("curl")]):
            with self.assertRaises(sd.SetupError):
                sd.download_archive(self.base + "/missing.7z", Path(tmp) / "sdk.7z", retries=1)
            self.assertEqual(list(Path(tmp).iterdir()), [])


@skipUnless(os.name == "nt" and _real_client("powershell"), "Windows PowerShell is only on Windows")
class RealPowerShellTests(_LocalSiteCase):
    """The same, with the PowerShell that ships with Windows (the second program tried)."""

    def test_a_page_is_read_through_powershell(self):
        with patch.object(sd, "external_clients", lambda: [_real_client("powershell")]):
            data = sd.http_get(self.base + "/page", retries=1)
        self.assertIn(b"tt5sdk_v5.23a_win64.7z", data)

    def test_the_archive_is_downloaded_through_powershell_and_checked(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "external_clients", lambda: [_real_client("powershell")]):
            destination = Path(tmp) / "sdk.7z"
            sd.download_archive(self.base + "/sdk.7z", destination, retries=1)
            self.assertEqual(destination.read_bytes(), ARCHIVE)

    def test_a_missing_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "external_clients", lambda: [_real_client("powershell")]):
            with self.assertRaises(sd.SetupError):
                sd.download_archive(self.base + "/missing.7z", Path(tmp) / "sdk.7z", retries=1)
