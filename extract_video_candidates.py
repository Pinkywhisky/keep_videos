#!/usr/bin/env python3
"""Détection statique des vidéos, sans exécution de JavaScript ni requête réseau."""

import re
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


MEDIA_PATH = re.compile(r"\.(?:mp4|webm|mov|m3u8|mpd)$", re.IGNORECASE)
BUNNY_VIDEO = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
LITERAL_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
# Une valeur contenant ces caractères est du JSON/HTML, pas une URL unique.
NOT_A_SINGLE_URL = re.compile(r"[\"<>{}]")
BUNNY_PATH = re.compile(r"/(?:(?:embed|play)/)?\d+/[^/]+")
VIMEO_PATH = re.compile(r"/(?:video/)?\d+(?:/|$)")
BUNNY_HOSTS = {"iframe.mediadelivery.net", "player.mediadelivery.net"}
SHORT_HOSTS = {"youtu.be", "dai.ly"}
YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
}


def normalize_url(value, base_url):
    """Résoudre les URLs relatives en conservant les paramètres signés."""
    value = value.strip().replace(r"\/", "/")
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parts = urlsplit(urljoin(base_url, value))
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        # Valider aussi les ports pour isoler une éventuelle URL mal formée.
        _ = parts.port
    except ValueError:
        return None
    userinfo, separator, host_port = parts.netloc.rpartition("@")
    netloc = (userinfo + separator if separator else "") + host_port.lower()
    return urlunsplit((
        parts.scheme.lower(), netloc, quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
        parts.query.replace(" ", "%20"), "",
    ))


def is_video_url(url):
    parts = urlsplit(url)
    host = parts.hostname  # déjà en minuscules
    if MEDIA_PATH.search(parts.path):
        return True
    if host in BUNNY_HOSTS:
        return bool(BUNNY_PATH.match(parts.path))
    if host in SHORT_HOSTS:
        return bool(parts.path.strip("/"))
    if host in YOUTUBE_HOSTS:
        return parts.path == "/watch" or parts.path.startswith(("/embed/", "/shorts/", "/live/"))
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        return bool(VIMEO_PATH.match(parts.path))
    if host == "dailymotion.com" or host.endswith(".dailymotion.com"):
        return parts.path.startswith(("/video/", "/embed/video/", "/player/"))
    return False


class VideoParser(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.base_url = page_url
        self.has_base = False
        self.attributes = []
        self.literal_text = []
        self.bunny_urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base" and not self.has_base:
            base_url = normalize_url(attrs.get("href") or "", self.base_url)
            if base_url:
                self.base_url = base_url
                self.has_base = True
        for key, value in attrs.items():
            if value:
                # video/source peuvent utiliser une URL de média sans extension.
                media_source = (
                    tag in {"video", "source"} and key in {"src", "data-src"}
                    and not (attrs.get("type") or "").lower().startswith(("image/", "audio/"))
                )
                self.attributes.append((value, media_source))

        library = (attrs.get("data-library") or "").strip()
        video = (attrs.get("data-video") or "").strip()
        if re.fullmatch(r"[0-9]+", library) and BUNNY_VIDEO.fullmatch(video):
            self.bunny_urls.append(f"https://iframe.mediadelivery.net/embed/{library}/{video}")

    def handle_data(self, data):
        self.literal_text.append(data)

    def candidates(self):
        # Un dict conserve l'ordre de découverte et élimine les doublons exacts.
        found = {}
        for value, media_source in self.attributes:
            url = None
            if not NOT_A_SINGLE_URL.search(value):
                url = normalize_url(value, self.base_url)
            if url and (media_source or is_video_url(url)):
                found[url] = None
            else:
                self.add_literals(value, found)
        for url in self.bunny_urls:
            found[url] = None
        # Conserver la détection historique des URLs littérales (scripts/JSON).
        # HTMLParser ne décode pas les entités des blocs script.
        for data in self.literal_text:
            self.add_literals(unescape(data), found)
        return list(found)

    def add_literals(self, data, found):
        for value in LITERAL_URL.findall(data.replace(r"\/", "/")):
            url = normalize_url(value, self.base_url)
            if url and not is_video_url(url):
                url = normalize_url(value.rstrip("),;]}"), self.base_url)
            if url and is_video_url(url):
                found[url] = None


def extract_candidates(html, page_url):
    parser = VideoParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.candidates()


def main():
    if len(sys.argv) != 3:
        sys.exit(f"Usage : {Path(sys.argv[0]).name} <fichier.html> <url-de-la-page>")
    html_file, page_url = sys.argv[1:]
    html = Path(html_file).read_text(encoding="utf-8", errors="replace")
    for url in extract_candidates(html, page_url):
        print(url)


if __name__ == "__main__":
    main()
