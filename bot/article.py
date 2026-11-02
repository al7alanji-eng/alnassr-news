"""Open an article page: resolve redirects, read its text and its share image."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

from .config import USER_AGENT

HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "ar,en;q=0.8"}


@dataclass
class Article:
    url: str
    text: str = ""
    image_url: str | None = None
    description: str = ""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.paragraphs: list[str] = []
        self._in_p = 0
        self._skip = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag in ("script", "style", "nav", "footer", "aside", "form"):
            self._skip += 1
        elif tag == "p" and not self._skip:
            self._in_p += 1
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside", "form") and self._skip:
            self._skip -= 1
        elif tag == "p" and self._in_p:
            self._in_p -= 1
            text = " ".join("".join(self._buf).split())
            if len(text) > 40:
                self.paragraphs.append(text)

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self._buf.append(data)


# ── Google News links ────────────────────────────────────────────────────

def decode_google_news(url: str, timeout: int = 15) -> str:
    """Google News RSS links are redirects; turn them into the publisher's URL (best effort)."""
    p = urlparse(url)
    if "news.google.com" not in p.netloc:
        return url
    try:
        article_id = p.path.rstrip("/").split("/")[-1]
        page = requests.get(f"https://news.google.com/rss/articles/{article_id}", headers=HEADERS, timeout=timeout).text
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sig and ts):
            return url
        inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                                "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], article_id, int(ts.group(1)), sig.group(1)]
        payload = [[["Fbv4je", json.dumps(inner), None, "generic"]]]
        r = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={"f.req": json.dumps(payload)},
            timeout=timeout,
        )
        m = re.search(r'\\"garturlres\\",\\"(https?://[^\\"]+)\\"', r.text)
        if m:
            return m.group(1)
    except (requests.RequestException, ValueError):
        pass
    return url


# ── article page ─────────────────────────────────────────────────────────

def read_article(url: str, timeout: int = 15) -> Article:
    url = decode_google_news(url)
    art = Article(url=url)
    if "news.google.com" in urlparse(url).netloc:
        return art
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return art
        art.url = r.url
        parser = _PageParser()
        parser.feed(r.text[:1_500_000])
    except (requests.RequestException, AssertionError):
        return art

    m = parser.meta
    img = m.get("og:image") or m.get("og:image:url") or m.get("twitter:image") or m.get("twitter:image:src")
    if img:
        art.image_url = urljoin(art.url, img)
    art.description = m.get("og:description") or m.get("description") or ""
    art.text = "\n".join(parser.paragraphs)[:4000]
    return art


# ── image download ───────────────────────────────────────────────────────

def download_image(url: str, timeout: int = 20, min_width: int = 400) -> tuple[bytes, str] | None:
    """Download an image and re-encode it as JPEG for X. Returns (bytes, mime) or None."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            return None
        raw = r.raw.read(10 * 1024 * 1024 + 1, decode_content=True)
        if len(raw) > 10 * 1024 * 1024:
            return None
        img = Image.open(io.BytesIO(raw))
        if img.width < min_width:
            return None
        img = img.convert("RGB")
        if img.width > 2048:
            img.thumbnail((2048, 2048))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88, optimize=True)
        data = out.getvalue()
        if len(data) > 5 * 1024 * 1024:
            return None
        return data, "image/jpeg"
    except Exception:  # noqa: BLE001 - any broken image is simply skipped
        return None
