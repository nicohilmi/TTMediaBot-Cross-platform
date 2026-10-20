"""tools/setup_deps.py: the official download page, the choice of the file, FFmpeg plans.

Nothing here touches the network. OFFICIAL_PAGE is a copy of the link list of
https://bearware.dk/?page_id=419 as it was read on 19 October 2026 (v5.23a, 8 April 2026);
the real file names and addresses are what the installer must be able to use.
"""
import io
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from tools import setup_deps as sd

_ROWS = (
    ("Standard Edition", "tt5sdk", "Windows 10/11", "x64", "win64", "www."),
    ("Standard Edition", "tt5sdk", "Mac OS X (10.13)", "Universal", "macos_universal", "www."),
    ("Standard Edition", "tt5sdk", "Linux (Ubuntu 26)", "x86_64", "ubuntu26_x86_64", "www."),
    ("Standard Edition", "tt5sdk", "Android v8.1+", "Universal", "android", "www."),
    ("Standard Edition", "tt5sdk", "iOS 8.0+", "Universal", "ios_universal", "www."),
    ("Standard Edition", "tt5sdk", "Raspbian 12 (bookworm)", "Raspberry Pi", "raspbian_arm64", "www."),
    ("Professional Edition", "tt5prosdk", "Windows 10/11", "x64", "win64", "www."),
    ("Professional Edition", "tt5prosdk", "Mac OS X (10.13)", "Universal", "macos_universal", "www."),
    ("Professional Edition", "tt5prosdk", "Linux (Ubuntu 26)", "x86_64", "ubuntu26_x86_64", "www."),
    ("Professional Edition", "tt5prosdk", "Android v8.1+", "Universal", "android", "www."),
    # the one link of the real page that has no "www."
    ("Professional Edition", "tt5prosdk", "iOS 8.0+", "Universal", "ios_universal", ""),
    ("Professional Edition", "tt5prosdk", "Raspbian 12 (bookworm)", "Raspberry Pi", "raspbian_arm64", "www."),
)


def make_page(version="5.23a", rows=_ROWS):
    lines = ["<html><body><h1>Download TeamTalk 5 SDK</h1><ul>"]
    for edition, kind, platform_name, arch, tag, www in rows:
        lines.append(
            '<li><strong>TeamTalk 5 SDK {0}</strong> v{1} April 8th 2026 {2} '
            '<a href="https://{3}bearware.dk/teamtalksdk/v{1}/{4}_v{1}_{5}.7z">{6}</a></li>'.format(
                edition, version, platform_name, www, kind, tag, arch
            )
        )
    lines.append("</ul><p>To unzip the files use 7-Zip.</p></body></html>")
    return "\n".join(lines)


OFFICIAL_PAGE = make_page()


class _Response:
    """What urllib.request.urlopen returns, as far as the installer uses it."""

    def __init__(self, body=b"", headers=None):
        self._stream = io.BytesIO(body)
        self.headers = dict(headers or {})

    def read(self, size=-1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class PageParsingTests(TestCase):
    def test_every_archive_of_the_official_page_is_found(self):
        assets = sd.parse_assets(OFFICIAL_PAGE)
        self.assertEqual(len(assets), 12)
        self.assertEqual({a.version for a in assets}, {"5.23a"})
        self.assertEqual(sum(a.edition == "standard" for a in assets), 6)
        self.assertEqual(sum(a.edition == "professional" for a in assets), 6)

    def test_the_address_of_the_windows_standard_edition_is_the_real_one(self):
        windows = sd.choose_asset(sd.parse_assets(OFFICIAL_PAGE), "windows", "AMD64")
        self.assertEqual(
            windows.url, "https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z"
        )

    def test_a_link_without_www_gets_the_same_address_form(self):
        urls = {a.url for a in sd.parse_assets(OFFICIAL_PAGE)}
        self.assertIn("https://www.bearware.dk/teamtalksdk/v5.23a/tt5prosdk_v5.23a_ios_universal.7z", urls)
        self.assertFalse([u for u in urls if u.startswith("https://bearware.dk")])

    def test_html_entities_and_other_text_do_not_matter(self):
        page = OFFICIAL_PAGE.replace("https://www.bearware.dk", "https&#58;//www.bearware.dk")
        self.assertEqual(len(sd.parse_assets(page)), 12)
        self.assertEqual(sd.parse_assets("<html>nothing to see</html>"), [])

    def test_a_page_with_several_releases_keeps_all_of_them(self):
        page = make_page("5.11b") + make_page("5.23a")
        versions = {a.version for a in sd.parse_assets(page)}
        self.assertEqual(versions, {"5.11b", "5.23a"})

    def test_directory_listings_are_read_too(self):
        listing = (
            '<a href="tt5sdk_v5.23a_win64.7z">x</a> <a href="tt5prosdk_v5.23a_win64.7z">y</a>'
            '<a href="tt5sdk_v5.23a_ubuntu26_x86_64.7z">z</a><a href="readme.txt">r</a>'
        )
        assets = sd.parse_directory(listing, "5.23a")
        self.assertEqual(len(assets), 3)
        self.assertEqual(assets[0].url, "https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z")


class VersionTests(TestCase):
    def test_versions_are_compared_as_numbers_and_letters(self):
        order = ["5.9", "5.11b", "5.23", "5.23a", "5.23b", "6.0"]
        self.assertEqual(sorted(reversed(order), key=sd.version_key), order)

    def test_a_text_that_is_no_version_sorts_first(self):
        self.assertLess(sd.version_key("local"), sd.version_key("5.0"))

    def test_the_numbers_of_a_library_version_are_compared(self):
        self.assertGreaterEqual(sd.version_numbers("5.23.0.1"), sd.version_numbers("5.23a"))
        self.assertLess(sd.version_numbers("5.11.0.1"), sd.version_numbers("5.23a"))


class ChooseAssetTests(TestCase):
    assets = sd.parse_assets(OFFICIAL_PAGE)

    def test_each_system_gets_its_standard_edition_archive(self):
        cases = (
            ("windows", "AMD64", "win64"),
            ("windows", "x86_64", "win64"),
            ("linux", "x86_64", "ubuntu26_x86_64"),
            ("linux", "aarch64", "raspbian_arm64"),
            ("darwin", "arm64", "macos_universal"),
        )
        for system, machine, tag in cases:
            with self.subTest(system=system, machine=machine):
                chosen = sd.choose_asset(self.assets, system, machine)
                self.assertEqual((chosen.tag, chosen.edition), (tag, "standard"))

    def test_unsupported_machines_get_nothing(self):
        for system, machine in (("windows", "x86"), ("windows", "ARM64"), ("linux", "armv7l"), ("freebsd", "amd64")):
            with self.subTest(system=system, machine=machine):
                self.assertIsNone(sd.choose_asset(self.assets, system, machine))

    def test_the_newest_release_wins(self):
        assets = sd.parse_assets(make_page("5.11b") + make_page("5.23a") + make_page("5.9"))
        self.assertEqual(sd.choose_asset(assets, "windows", "AMD64").version, "5.23a")

    def test_the_newest_ubuntu_build_wins_within_a_release(self):
        rows = _ROWS + (("Standard Edition", "tt5sdk", "Linux (Ubuntu 24)", "x86_64", "ubuntu24_x86_64", "www."),)
        assets = sd.parse_assets(make_page(rows=rows))
        self.assertEqual(sd.choose_asset(assets, "linux", "x86_64").tag, "ubuntu26_x86_64")


class KnownAssetTests(TestCase):
    """The file name used when the page cannot be read must be the one the page lists."""

    def test_it_equals_what_the_official_page_lists_for_the_same_system(self):
        official = sd.parse_assets(OFFICIAL_PAGE)
        for system, machine in (
            ("windows", "AMD64"), ("linux", "x86_64"), ("linux", "aarch64"), ("darwin", "arm64"),
        ):
            with self.subTest(system=system, machine=machine):
                self.assertEqual(sd.known_asset(system, machine), sd.choose_asset(official, system, machine))

    def test_the_address_is_the_one_on_the_official_site(self):
        asset = sd.known_asset("windows", "AMD64")
        self.assertEqual(asset.url, "https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z")
        self.assertEqual(asset.version, sd.LAST_SEEN_VERSION)

    def test_no_request_is_made(self):
        with patch.object(sd.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            self.assertIsNotNone(sd.known_asset("windows", "AMD64"))

    def test_unsupported_machines_get_nothing(self):
        self.assertIsNone(sd.known_asset("windows", "x86"))
        self.assertIsNone(sd.known_asset("freebsd", "amd64"))


class DiscoverTests(TestCase):
    def test_the_first_address_that_works_is_used(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return OFFICIAL_PAGE.encode()

        assets, notes = sd.discover_assets(fetch)
        self.assertEqual(len(assets), 12)
        self.assertEqual(notes, [])
        self.assertEqual(calls, [sd.SDK_PAGES[0]])

    def test_the_next_address_is_tried_when_one_fails_and_the_failure_is_kept(self):
        def fetch(url):
            if url == sd.SDK_PAGES[0]:
                raise sd.SetupError("could not read the first page: HTTP Error 454: ")
            return OFFICIAL_PAGE.encode()

        assets, notes = sd.discover_assets(fetch)
        self.assertEqual(len(assets), 12)
        self.assertEqual(notes, ["could not read the first page: HTTP Error 454: "])

    def test_a_page_without_links_is_noted_and_the_directory_is_listed(self):
        def fetch(url):
            if url == sd.SDK_DIRECTORY:
                return b'<a href="v5.23a/">v5.23a/</a>'
            if url == sd.SDK_DOWNLOAD_BASE + "/v5.23a/":
                return b'<a href="tt5sdk_v5.23a_win64.7z">x</a>'
            return b"<html>the layout changed</html>"

        assets, notes = sd.discover_assets(fetch)
        self.assertEqual([a.tag for a in assets], ["win64"])
        self.assertEqual(len(notes), len(sd.SDK_PAGES))
        self.assertTrue(all("no SDK links" in note for note in notes))

    def test_when_nothing_can_be_read_every_reason_is_returned(self):
        def fetch(url):
            raise sd.SetupError("could not read %s: HTTP Error 454: " % url)

        assets, notes = sd.discover_assets(fetch)
        self.assertEqual(assets, [])
        self.assertEqual(len(notes), len(sd.SDK_PAGES) + 1)
        self.assertTrue(all("454" in note for note in notes))


class FfmpegPlanTests(TestCase):
    @staticmethod
    def which(*present):
        return lambda name: "/bin/" + name if name in present else None

    def test_windows_prefers_winget_then_chocolatey_then_scoop(self):
        plans = sd.ffmpeg_install_plans("windows", self.which("winget", "choco", "scoop"))
        self.assertEqual([label.split()[0] for label, _ in plans], ["Windows", "Chocolatey", "Scoop"])
        self.assertIn("Gyan.FFmpeg", plans[0][1][0])

    def test_windows_without_a_package_manager_has_no_plan(self):
        self.assertEqual(sd.ffmpeg_install_plans("windows", self.which()), [])

    def test_linux_uses_the_package_manager_that_is_there(self):
        for tool, command in (("apt-get", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman"), ("apk", "apk")):
            with self.subTest(tool=tool):
                plans = sd.ffmpeg_install_plans("linux", self.which(tool))
                self.assertEqual(plans[0][1][-1][0], command)

    def test_fedora_tries_ffmpeg_and_then_ffmpeg_free(self):
        plans = sd.ffmpeg_install_plans("linux", self.which("dnf"))
        self.assertEqual([p[1][0][-1] for p in plans], ["ffmpeg", "ffmpeg-free"])

    def test_macos_uses_homebrew(self):
        self.assertEqual(sd.ffmpeg_install_plans("darwin", self.which("brew"))[0][0], "Homebrew")


class SdkFlowTests(TestCase):
    """setup_sdk with the page unreadable (the HTTP 454 of the report) and with a local file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = Path(self.tmp.name) / "bot"
        self.bot.mkdir()
        self.said = []
        patcher = patch.object(sd, "say", side_effect=lambda m="": self.said.append(m))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def extract(files):
        def run(archive, target, system, allow_install=True):
            for name, content in files.items():
                path = target / "Library" / "TeamTalk_DLL" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

        return run

    def run_sdk(self, fetch, download, **kwargs):
        ok_library = lambda path: sd.LibraryCheck(True, version="5.23.0.1")  # noqa: E731
        with patch.object(sd, "extract_archive", self.extract({"TeamTalk5.dll": b"dll"})), \
                patch.object(sd, "check_library", ok_library):
            return sd.setup_sdk(self.bot, "windows", "AMD64", fetch=fetch, download=download, **kwargs)

    def test_an_unreadable_page_still_downloads_the_known_official_file(self):
        downloaded = []

        def fetch(url):
            raise sd.SetupError("could not read %s: HTTP Error 454: " % url)

        def download(url, path):
            downloaded.append(url)
            path.write_bytes(b"archive")

        self.assertTrue(self.run_sdk(fetch, download))
        self.assertEqual(downloaded, ["https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z"])
        self.assertTrue((self.bot / "TeamTalk_DLL" / "TeamTalk5.dll").is_file())
        text = "\n".join(self.said)
        self.assertIn("HTTP Error 454", text, "the reason the page could not be read must be shown")
        self.assertIn("directly on the official site", text)

    def test_a_failed_download_prints_every_reason_and_the_manual_steps(self):
        def fetch(url):
            raise sd.SetupError("could not read %s: HTTP Error 454: " % url)

        def download(url, path):
            raise sd.SetupError("download of %s failed: HTTP Error 454; curl: HTTP 454" % url)

        self.assertFalse(self.run_sdk(fetch, download))
        text = "\n".join(self.said)
        self.assertIn("curl: HTTP 454", text)
        self.assertIn("Do it by hand", text)
        self.assertIn("--sdk-file", text)
        self.assertIn("https://www.bearware.dk/teamtalksdk/v5.23a/tt5sdk_v5.23a_win64.7z", text)
        self.assertFalse((self.bot / "TeamTalk_DLL" / "TeamTalk5.dll").exists())

    def test_an_archive_given_by_the_person_is_used_without_any_request(self):
        given = Path(self.tmp.name) / "tt5sdk_v5.23a_win64.7z"
        given.write_bytes(b"archive")

        def no_network(*args, **kwargs):
            raise AssertionError("the network must not be used")

        self.assertTrue(self.run_sdk(no_network, no_network, archive=given))
        self.assertTrue((self.bot / "TeamTalk_DLL" / "TeamTalk5.dll").is_file())
        self.assertTrue(given.is_file(), "the person's file must not be moved or deleted")
        self.assertIn("Using the archive you gave", "\n".join(self.said))

    def test_an_archive_replaces_an_installed_library_even_without_force(self):
        (self.bot / "TeamTalk_DLL").mkdir()
        (self.bot / "TeamTalk_DLL" / "TeamTalk5.dll").write_bytes(b"old")
        given = Path(self.tmp.name) / "sdk.7z"
        given.write_bytes(b"archive")
        self.assertTrue(self.run_sdk(None, None, archive=given))
        self.assertEqual((self.bot / "TeamTalk_DLL" / "TeamTalk5.dll").read_bytes(), b"dll")

    def test_a_file_that_does_not_exist_is_reported(self):
        missing = Path(self.tmp.name) / "nothing.7z"
        self.assertFalse(self.run_sdk(None, None, archive=missing))
        self.assertIn("does not exist", "\n".join(self.said))

    def test_the_command_line_accepts_the_file(self):
        calls = {}

        def fake(bot_dir, system, machine, force=False, check_only=False, archive=None, **kw):
            calls["archive"] = archive
            return True

        with patch.object(sd, "setup_sdk", fake):
            self.assertEqual(sd.main(["sdk", "--bot-dir", str(self.bot), "--sdk-file", "x.7z"]), 0)
        self.assertEqual(calls["archive"], Path("x.7z").resolve())
