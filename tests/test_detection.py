"""Tests unitaires et de CLI reproductibles, sans service distant."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))
from extract_video_candidates import extract_candidates  # noqa: E402


PAGE_URL = "https://example.test/pages/replay?access=allowed"
BUNNY = "https://iframe.mediadelivery.net/embed/314159/12345678-abcd-4321-9876-123456789abc"
BASH = shutil.which("bash")


class ParserTests(unittest.TestCase):
    def fixture(self, name):
        return extract_candidates((FIXTURES / name).read_text(), PAGE_URL)

    def test_bunny_attributes(self):
        self.assertEqual(self.fixture("bunny.html"), [BUNNY])

    def test_multiple_platforms_and_formats(self):
        urls = self.fixture("multiple.html")
        self.assertEqual(len(urls), 9)
        self.assertIn(
            "https://player.mediadelivery.net/embed/271828/"
            "abcdef12-3456-7890-abcd-abcdef123456?autoplay=false&token=a%2Bb", urls)
        self.assertIn("https://player.vimeo.com/video/123456789?h=secret", urls)
        self.assertIn("https://www.dailymotion.com/embed/video/test-video", urls)
        for name in ("replay.webm", "replay.mov", "master.m3u8", "manifest.mpd"):
            self.assertIn(f"https://example.test/media/{name}", urls)

    def test_relative_urls_and_entities_preserve_queries(self):
        self.assertEqual(self.fixture("relative.html"), [
            "https://example.test/media/replay.mp4?token=a%2Bb&expires=123",
            "https://example.test/pages/movie.webm",
            "https://example.test/streams/master.m3u8?token=one&quality=best",
            "https://www.youtube.com/embed/relative-video",
        ])

    def test_duplicates(self):
        self.assertEqual(self.fixture("duplicates.html"), [
            "https://example.test/media/replay.mp4?a=1&b=2", BUNNY,
        ])

    def test_empty_bunny_is_not_a_video(self):
        self.assertEqual(self.fixture("empty_bunny.html"), [])

    def test_no_video(self):
        self.assertEqual(self.fixture("no_video.html"), [])

    def test_empty_html(self):
        self.assertEqual(extract_candidates("", PAGE_URL), [])

    def test_youtube_iframe(self):
        self.assertEqual(self.fixture("youtube.html"), [
            "https://www.youtube.com/embed/test-video?start=5&rel=0",
        ])

    def test_base_url_and_extensionless_source(self):
        html = '<base href="/assets/"><video><source src="stream?id=1&amp;token=2"></video>'
        self.assertEqual(extract_candidates(html, PAGE_URL), [
            "https://example.test/assets/stream?id=1&token=2",
        ])

    def test_literal_urls_in_scripts(self):
        html = r'''<script>
        const source = "https:\/\/cdn.example.test\/master.m3u8?token=a%2Bb&amp;expires=2";
        const player = "https://iframe.mediadelivery.net/play/42/12345678-abcd-4321-9876-123456789abc";
        </script>'''
        self.assertEqual(extract_candidates(html, PAGE_URL), [
            "https://cdn.example.test/master.m3u8?token=a%2Bb&expires=2",
            "https://iframe.mediadelivery.net/play/42/12345678-abcd-4321-9876-123456789abc",
        ])

    def test_multiline_attributes_and_case(self):
        html = """<DIV DATA-VIDEO='abcdef12-3456-7890-abcd-abcdef123456'
                 DATA-LIBRARY='42'></DIV><VIDEO SRC=' /path/Replay.MP4?token=x%2Fy ' />"""
        self.assertEqual(set(extract_candidates(html, PAGE_URL)), {
            "https://example.test/path/Replay.MP4?token=x%2Fy",
            "https://iframe.mediadelivery.net/embed/42/abcdef12-3456-7890-abcd-abcdef123456",
        })

    def test_json_attribute_and_signed_query_punctuation(self):
        html = """<div data-player='{"file":"https://cdn.example.test/clip.mp4?token=x)"}'></div>
        <source src="https://CDN.example.test/clip.mp4?token=x)">
        <script>const url = "https://cdn.example.test/master.m3u8?token=x)";</script>"""
        self.assertEqual(extract_candidates(html, PAGE_URL), [
            "https://cdn.example.test/clip.mp4?token=x)",
            "https://cdn.example.test/master.m3u8?token=x)",
        ])

    def test_image_source_is_not_a_video(self):
        html = '<picture><source src="/image?id=1" type="image/webp"></picture>'
        self.assertEqual(extract_candidates(html, PAGE_URL), [])

    def test_invalid_or_unsafe_urls_do_not_break_other_candidates(self):
        html = """<video src="javascript:alert(1)"></video>
        <video src="data:video/mp4;base64,abc"></video>
        <source src="https://[broken/movie.mp4">
        <source src="https://example.test:bad/movie.mp4">
        <source src="/clip.mp4?x=1&#10;--exec=command">
        <video src="/valid.mp4?token=good"></video>"""
        self.assertEqual(extract_candidates(html, PAGE_URL), [
            "https://example.test/valid.mp4?token=good",
        ])


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="keep-videos-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.output = self.work / "output"
        self.trace = self.work / "calls.jsonl"
        self.mock = self.bin / "mock_command"
        source = (ROOT / "tests" / "mock_command.py").read_text()
        self.mock.write_text(f"#!{sys.executable}\n" + source.split("\n", 1)[1])
        self.mock.chmod(0o755)
        # PATH isolé : permet de vérifier l'absence de curl/Python sans réseau.
        for cmd in ("bash", "basename", "dirname", "date", "mkdir", "realpath",
                    "tee", "wc", "cat", "mktemp", "rm", "grep", "python3"):
            executable = shutil.which(cmd)
            if executable:
                (self.bin / cmd).symlink_to(executable)
        for cmd in ("yt-dlp", "ffmpeg", "curl"):
            (self.bin / cmd).symlink_to(self.mock)
        self.env = dict(os.environ, PATH=str(self.bin),
                        KEEP_VIDEOS_TEST_CALLS=str(self.trace),
                        MOCK_HTML=str(FIXTURES / "bunny.html"))
        self.cookies = self.work / "cookies.txt"
        self.cookies.write_text("# Netscape HTTP Cookie File\n")

    def run_script(self, *options, url=PAGE_URL, expected=0):
        result = subprocess.run(
            [BASH, str(ROOT / "dl_page_videos.sh"), "-o", str(self.output), *options, url],
            env=self.env, cwd=self.work, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(list(self.output.glob(".run.*")), [])
        return result

    def calls(self, command):
        if not self.trace.exists():
            return []
        return [entry["args"] for line in self.trace.read_text().splitlines()
                if (entry := json.loads(line))["command"] == command]

    def yt_args(self):
        # Seul l'appel principal porte les options communes (pas --version ni l'export).
        calls = [args for args in self.calls("yt-dlp") if "--encoding" in args]
        self.assertEqual(len(calls), 1)
        return calls[0]

    def assert_classic(self):
        args = self.yt_args()
        self.assertNotIn("--batch-file", args)
        self.assertEqual(args[-1], PAGE_URL)

    def test_bunny_detected_before_ytdlp(self):
        result = self.run_script("--keep-html")
        args = self.yt_args()
        self.assertIn("--batch-file", args)
        self.assertEqual(args[args.index("--referer") + 1], PAGE_URL)
        self.assertEqual((self.output / ".candidate_urls.txt").read_text().splitlines(), [BUNNY])
        self.assertIn("1 média(s) vérifié(s)", result.stdout)
        self.assertTrue((self.output / ".downloaded.txt").is_file())
        self.assertTrue((self.output / "download.log").is_file())

    def test_dry_run_displays_candidates_and_writes_no_media(self):
        result = self.run_script("--dry-run")
        self.assertIn(BUNNY, result.stdout)
        args = self.yt_args()
        self.assertIn("--simulate", args)
        self.assertIn("--flat-playlist", args)
        for option in ("--download-archive", "--print-to-file",
                       "--write-thumbnail", "--write-description"):
            self.assertNotIn(option, args)
        self.assertEqual({path.name for path in self.output.iterdir()}, {"download.log"})

    def test_html_and_candidates_are_removed_by_default(self):
        self.run_script()
        self.assertFalse((self.output / ".page.html").exists())
        self.assertFalse((self.output / ".candidate_urls.txt").exists())
        self.assertIn(BUNNY, (self.output / "download.log").read_text())

    def test_batch_downloads_are_numbered_in_page_order(self):
        self.run_script()
        template = self.yt_args()[self.yt_args().index("-o") + 1]
        self.assertTrue(template.endswith("%(playlist_index,autonumber)02d - %(title)s [%(id)s].%(ext)s"))

    def test_multiple_candidates(self):
        self.env["MOCK_HTML"] = str(FIXTURES / "multiple.html")
        result = self.run_script()
        self.assertIn("9 média(s) vérifié(s)", result.stdout)

    def test_no_video_falls_back(self):
        self.env["MOCK_HTML"] = str(FIXTURES / "no_video.html")
        self.run_script()
        self.assert_classic()

    def test_empty_html_falls_back(self):
        empty = self.work / "empty.html"
        empty.touch()
        self.env["MOCK_HTML"] = str(empty)
        self.run_script()
        self.assert_classic()

    def test_curl_network_and_http_errors_fall_back(self):
        for code in ("7", "22", "28"):
            with self.subTest(code=code):
                self.trace.unlink(missing_ok=True)
                self.env["MOCK_CURL_EXIT"] = code
                self.run_script()
                self.assert_classic()

    def test_curl_absent_falls_back(self):
        (self.bin / "curl").unlink()
        result = self.run_script()
        self.assertIn("curl absent", result.stdout)
        self.assert_classic()

    def test_python_absent_falls_back(self):
        (self.bin / "python3").unlink()
        result = self.run_script()
        self.assertIn("Python 3 absent", result.stdout)
        self.assert_classic()

    def test_parser_failure_falls_back(self):
        python = self.bin / "python3"
        python.unlink()
        python.write_text("#!/bin/bash\nexit 1\n")
        python.chmod(0o755)
        result = self.run_script()
        self.assertIn("Échec de l'analyse HTML", result.stdout)
        self.assert_classic()

    def test_redirect_url_is_used_for_relative_urls_and_referer(self):
        self.env["MOCK_HTML"] = str(FIXTURES / "relative.html")
        self.env["MOCK_EFFECTIVE_URL"] = "https://other.example.test/new/replay"
        self.run_script("--keep-html")
        args = self.yt_args()
        self.assertEqual(args[args.index("--referer") + 1], self.env["MOCK_EFFECTIVE_URL"])
        urls = (self.output / ".candidate_urls.txt").read_text()
        self.assertIn("https://other.example.test/new/movie.webm", urls)

    def test_cookies_and_existing_download_options(self):
        self.run_script("--cookies", str(self.cookies), "-n", "2")
        args = self.yt_args()
        self.assertEqual(args[args.index("--cookies") + 1], str(self.cookies))
        self.assertEqual(args[args.index("-N") + 1], "2")
        for option in ("--continue", "--yes-playlist", "--embed-metadata",
                       "--write-thumbnail", "--write-description", "--windows-filenames"):
            self.assertIn(option, args)
        self.assertEqual(args[args.index("--merge-output-format") + 1], "mp4")
        self.assertEqual(args[args.index("--encoding") + 1], "utf-8")
        self.assertEqual(args[args.index("--trim-filenames") + 1], "180")
        self.assertNotIn("--extractor-args", args)
        self.assertEqual(args[args.index("-o") + 1], str(
            self.output / "%(playlist_index,autonumber)02d - %(title)s [%(id)s].%(ext)s"))
        curl = self.calls("curl")[0]
        self.assertEqual(curl[curl.index("--cookie") + 1], str(self.cookies))

    def test_browser_audio_and_no_sidecars(self):
        self.run_script("--cookies-from-browser=firefox", "--audio-only",
                        "--no-thumbnail", "--no-description", "--concurrent=3")
        args = self.yt_args()
        self.assertEqual(args[args.index("--cookies-from-browser") + 1], "firefox")
        self.assertIn("--extract-audio", args)
        self.assertEqual(args[args.index("--audio-format") + 1], "best")
        self.assertNotIn("--merge-output-format", args)
        self.assertNotIn("--write-thumbnail", args)
        self.assertNotIn("--write-description", args)
        self.assertEqual(args[args.index("-N") + 1], "3")
        self.assertEqual(len(list(self.output.glob("*.m4a"))), 1)

    def test_browser_cookies_are_exported_for_curl_then_deleted(self):
        result = self.run_script("--cookies-from-browser", "firefox")
        self.assertIn("Cookies firefox utilisés pour lire la page", result.stdout)
        curl = self.calls("curl")[0]
        cookie_file = Path(curl[curl.index("--cookie") + 1])
        self.assertTrue(cookie_file.name.endswith("browser-cookies.txt"))
        self.assertFalse(cookie_file.exists())
        self.assertEqual(self.yt_args()[self.yt_args().index("--cookies-from-browser") + 1],
                         "firefox")

    def test_browser_profile_syntax_is_accepted(self):
        profile = "firefox:/mnt/c/Users/me/AppData/Roaming/Mozilla/Firefox/Profiles/x.default"
        self.run_script("--cookies-from-browser", profile)
        self.assertEqual(self.yt_args()[self.yt_args().index("--cookies-from-browser") + 1], profile)

    def test_browser_cookie_export_failure_still_scans_public_page(self):
        self.env["MOCK_COOKIE_EXPORT"] = "fail"
        result = self.run_script("--cookies-from-browser", "firefox")
        self.assertIn("Export des cookies firefox impossible", result.stdout)
        self.assertNotIn("--cookie", self.calls("curl")[0])
        self.assertIn("--batch-file", self.yt_args())

    def test_old_ytdlp_prints_update_hint(self):
        self.env["MOCK_YTDLP_VERSION"] = "2020.01.01"
        result = self.run_script()
        self.assertIn("yt-dlp 2020.01.01 date de", result.stdout)
        self.env["MOCK_YTDLP_VERSION"] = "2099.01.01.123456"
        self.assertNotIn("mettez-le à jour", self.run_script().stdout)

    def test_direct_video_urls_keep_native_extractors(self):
        for url in ("https://www.youtube.com/watch?v=video&list=playlist",
                    "https://vimeo.com/12345", BUNNY,
                    "https://cdn.example.test/MEDIA.MP4?token=value",
                    "https://cdn.example.test/master.m3u8", "https://cdn.example.test/main.mpd"):
            with self.subTest(url=url):
                self.trace.unlink(missing_ok=True)
                self.run_script(url=url)
                self.assertEqual(self.calls("curl"), [])
                self.assertEqual(self.yt_args()[-1], url)

    def test_media_content_type_keeps_classic_download(self):
        self.env["MOCK_CONTENT_TYPE"] = "video/mp4"
        self.run_script()
        self.assert_classic()

    def test_archive_skips_without_claiming_new_download(self):
        self.run_script()
        archive = (self.output / ".downloaded.txt").read_bytes()
        result = self.run_script()
        self.assertIn("Aucun nouveau média téléchargé", result.stdout)
        self.assertNotIn("média(s) vérifié(s)", result.stdout)
        self.assertEqual((self.output / ".downloaded.txt").read_bytes(), archive)
        # Journal cumulatif : les deux exécutions sont conservées.
        self.assertEqual((self.output / "download.log").read_text().count("Code retour : 0"), 2)

    def test_ytdlp_error_is_not_hidden(self):
        self.env["MOCK_YTDLP_MODE"] = "error"
        result = self.run_script(expected=1)
        self.assertIn("yt-dlp a échoué", result.stderr)
        self.assertIn("--no-abort-on-error", self.yt_args())
        self.assertNotIn("--ignore-errors", self.yt_args())

    def test_zero_exit_without_media_is_not_success(self):
        for mode in ("hidden_error", "empty", "missing_file"):
            with self.subTest(mode=mode):
                self.trace.unlink(missing_ok=True)
                self.env["MOCK_YTDLP_MODE"] = mode
                result = self.run_script(expected=1)
                self.assertIn("Aucun média téléchargé ou confirmé", result.stderr)
                self.assertNotIn("Traitement terminé", result.stdout)

    def test_partial_failure_preserves_downloads_and_returns_error(self):
        self.env["MOCK_YTDLP_MODE"] = "partial"
        self.env["MOCK_HTML"] = str(FIXTURES / "multiple.html")
        result = self.run_script(expected=1)
        self.assertEqual(len(list(self.output.glob("*.mp4"))), 1)
        self.assertIn("yt-dlp a échoué", result.stderr)
        self.assertIn("1 média(s) téléchargé(s), mais certaines vidéos ont échoué", result.stderr)
        self.assertNotIn("Traitement terminé", result.stdout)

    def test_symlinked_script_still_finds_extractor(self):
        link = self.work / "keep-videos"
        link.symlink_to(ROOT / "dl_page_videos.sh")
        result = subprocess.run(
            [BASH, str(link), "-o", str(self.output), PAGE_URL],
            env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--batch-file", self.yt_args())

    def test_stale_candidates_are_not_reused_after_curl_failure(self):
        self.run_script("--keep-html")
        self.trace.unlink()
        self.env["MOCK_CURL_EXIT"] = "22"
        self.run_script("--keep-html")
        self.assert_classic()
        self.assertEqual((self.output / ".candidate_urls.txt").read_text(), "")

    def test_invalid_options_and_help(self):
        for options in (["--concurrent", "0"], ["--cookies-from-browser", "unknown"],
                        ["--cookies", "/missing/cookies.txt"],
                        ["--cookies", str(self.cookies), "--cookies-from-browser", "firefox"],
                        ["--unknown-option"]):
            with self.subTest(options=options):
                self.run_script(*options, expected=2)
        for flag in ("-h", "--help"):
            self.run_script(flag)
        self.assertEqual(self.calls("yt-dlp"), [])

    def test_long_output_option_with_spaces_and_percent(self):
        self.output = self.work / "output 100% test"
        result = subprocess.run(
            [BASH, str(ROOT / "dl_page_videos.sh"), f"--output={self.output}",
             f"--cookies={self.cookies}", PAGE_URL],
            env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list(self.output.glob("*.mp4"))), 1)
        self.assertEqual(list(self.output.glob(".run.*")), [])


if __name__ == "__main__":
    unittest.main()
