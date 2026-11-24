"""Vérification réelle de curl, yt-dlp et ffmpeg sur un serveur local."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Thread
import unittest


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("bash", "curl", "yt-dlp", "ffmpeg")


class FixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path.startswith("/auth/") and "access=allowed" not in self.headers.get("Cookie", ""):
            self.send_error(403)
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/nested/replay")
            self.end_headers()
            return
        pages = {
            "/replay": '<video src="/sample.mp4"></video>',
            "/nested/replay": '<video src="../sample.mp4"></video>',
            "/auth/replay": '<video src="/auth/sample.mp4"></video>',
            "/unavailable": '<video src="/missing.mp4"></video>',
        }
        if self.path in pages:
            body = pages[self.path].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/auth/"):
            self.path = self.path.removeprefix("/auth")
        super().do_GET()


@unittest.skipUnless(all(shutil.which(cmd) for cmd in REQUIRED),
                     "curl, yt-dlp et ffmpeg requis pour les tests réels locaux")
class LocalDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="keep-videos-http-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        subprocess.run([
            shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=32x32:d=0.2",
            "-c:v", "mpeg4", "-an", str(cls.work / "sample.mp4"),
        ], check=True, capture_output=True, timeout=15)
        try:
            cls.server = ThreadingHTTPServer(
                ("127.0.0.1", 0), partial(FixtureHandler, directory=str(cls.work)))
        except PermissionError as error:
            raise unittest.SkipTest("Sockets locaux interdits dans cet environnement") from error
        cls.addClassCleanup(cls.server.server_close)
        cls.worker = Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.addClassCleanup(cls.stop_server)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.worker.join(timeout=5)

    def setUp(self):
        self.output = self.work / self.id().rsplit(".", 1)[-1]

    def run_script(self, route, *options, expected=0):
        env = dict(os.environ, NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
        result = subprocess.run([
            shutil.which("bash"), str(ROOT / "dl_page_videos.sh"),
            "-o", str(self.output), "--no-thumbnail", "--no-description",
            *options, self.base_url + route,
        ], env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(list(self.output.glob(".run.*")), [])
        return result

    def test_real_download_redirect_and_archive(self):
        result = self.run_script("/redirect", "--keep-html")
        media = list(self.output.glob("*.mp4"))
        self.assertEqual(len(media), 1)
        self.assertTrue(media[0].name.startswith("01 - "), media[0].name)
        self.assertGreater(media[0].stat().st_size, 0)
        self.assertIn("1 média(s) vérifié(s)", result.stdout)
        self.assertIn(self.base_url + "/sample.mp4",
                      (self.output / ".candidate_urls.txt").read_text())
        self.assertTrue((self.output / ".downloaded.txt").is_file())
        result = self.run_script("/redirect")
        self.assertIn("Aucun nouveau média téléchargé", result.stdout)
        self.assertEqual(len(list(self.output.glob("*.mp4"))), 1)

    def test_real_dry_run(self):
        result = self.run_script("/replay", "--dry-run")
        self.assertIn(self.base_url + "/sample.mp4", result.stdout)
        self.assertEqual(list(self.output.glob("*.mp4")), [])
        self.assertFalse((self.output / ".downloaded.txt").exists())

    def test_real_authenticated_html_and_media(self):
        cookies = self.work / "cookies.txt"
        cookies.write_text(
            "# Netscape HTTP Cookie File\n"
            "127.0.0.1\tFALSE\t/\tFALSE\t0\taccess\tallowed\n")
        self.run_script("/auth/replay", "--cookies", str(cookies))
        self.assertEqual(len(list(self.output.glob("*.mp4"))), 1)

    def test_real_removed_video_is_failure(self):
        result = self.run_script("/unavailable", expected=1)
        self.assertIn("yt-dlp a échoué", result.stderr)
        self.assertEqual(list(self.output.glob("*.mp4")), [])

    def test_real_http_403_falls_back_and_reports_failure(self):
        result = self.run_script("/auth/replay", expected=1)
        self.assertIn("Récupération HTML impossible", result.stdout)
        self.assertIn("yt-dlp a échoué", result.stderr)


if __name__ == "__main__":
    unittest.main()
