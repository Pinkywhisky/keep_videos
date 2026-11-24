#!/usr/bin/env python3
"""Doublures des commandes externes : aucun accès réseau."""

from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys


name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["KEEP_VIDEOS_TEST_CALLS"], "a", encoding="utf-8") as trace:
    trace.write(json.dumps({"command": name, "args": args}) + "\n")

if name == "curl":
    status = int(os.environ.get("MOCK_CURL_EXIT", "0"))
    if status:
        print(f"curl: HTTP error or network failure ({status})", file=sys.stderr)
        sys.exit(status)
    Path(args[args.index("-o") + 1]).write_bytes(Path(os.environ["MOCK_HTML"]).read_bytes())
    print(os.environ.get("MOCK_EFFECTIVE_URL", args[-1]))
    print(os.environ.get("MOCK_CONTENT_TYPE", "text/html"), end="")
    sys.exit(0)

if name == "ffmpeg":
    sys.exit(0)

if "--version" in args:
    print(os.environ.get("MOCK_YTDLP_VERSION", date.today().strftime("%Y.%m.%d")))
    sys.exit(0)

# Export des cookies navigateur : pas d'URL, fichier écrit puis code 2.
if "--cookies-from-browser" in args and "--encoding" not in args:
    if os.environ.get("MOCK_COOKIE_EXPORT") != "fail":
        Path(args[args.index("--cookies") + 1]).write_text(
            "# Netscape HTTP Cookie File\nexample.test\tFALSE\t/\tFALSE\t0\taccess\tallowed\n")
    print("yt-dlp: error: You must provide at least one URL.", file=sys.stderr)
    sys.exit(2)

mode = os.environ.get("MOCK_YTDLP_MODE", "success")
if mode == "error":
    print("ERROR: Video unavailable (HTTP 403/404 or extractor failure)", file=sys.stderr)
    sys.exit(1 if "--no-abort-on-error" in args else 0)
if mode in {"empty", "hidden_error"}:
    if mode == "hidden_error":
        print("ERROR: ignored download failure", file=sys.stderr)
    sys.exit(0)

if "--batch-file" in args:
    urls = Path(args[args.index("--batch-file") + 1]).read_text().splitlines()
else:
    urls = [args[-1]]
if "--simulate" in args:
    for url in urls:
        print(f"Fixture | mock-id | mock | {url}")
    sys.exit(0)

archive = Path(args[args.index("--download-archive") + 1])
output = Path(args[args.index("-o") + 1]).parent
completed = Path(args[args.index("--print-to-file") + 2].replace("%%", "%"))
for index, url in enumerate(urls):
    media_id = hashlib.sha256(url.encode()).hexdigest()[:12]
    record = f"mock {media_id}"
    if archive.exists() and record in archive.read_text().splitlines():
        print(f"[download] {media_id}: has already been recorded in the archive")
        continue
    if mode == "partial" and index > 0:
        print("ERROR: Video unavailable", file=sys.stderr)
        continue
    ext = "m4a" if "--extract-audio" in args else "mp4"
    media = output / f"00 - Fixture [{media_id}].{ext}"
    if mode != "missing_file":
        media.write_bytes(b"mock media")
        with archive.open("a") as records:
            records.write(record + "\n")
    with completed.open("a") as records:
        records.write(str(media) + "\n")
    if "--write-thumbnail" in args:
        media.with_suffix(".jpg").write_bytes(b"mock thumbnail")
    if "--write-description" in args:
        media.with_suffix(".description").write_text("mock description")
sys.exit(1 if mode == "partial" else 0)
