"""Collect candidate news items from news search RSS feeds and direct feeds."""
from __future__ import annotations

import calendar
import hashlib
import html
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote_plus, urlparse, urlunparse

import feedparser
import requests

from .config import USER_AGENT


@dataclass
class Item:
    title: str
    url: str
    source_name: str
    source_domain: str
    published_ts: float
    description: str = ""
    image_hint: str | None = None  # thumbnail supplied by the feed
    feed: str = ""
    tier: str = ""  # "official" | "trusted"
    subjects: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return item_id(self.url, self.title)


# ── helpers ──────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(_TAG_RE.sub(" ", value))
    return _SPACE_RE.sub(" ", value).strip()


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    query = "&".join(
        part for part in p.query.split("&")
        if part and not part.lower().startswith(("utm_", "fbclid", "gclid", "ocid"))
    )
    netloc = p.netloc.lower().removeprefix("www.")
    return urlunparse((p.scheme or "https", netloc, p.path.rstrip("/"), "", query, ""))


def normalize_title(title: str) -> str:
    t = clean_text(title).lower()
    t = re.sub(r"\s[-|–—]\s[^-|–—]+$", "", t)  # drop trailing " - Source"
    t = re.sub(r"[^\w\s]", "", t)
    return _SPACE_RE.sub(" ", t).strip()


def item_id(url: str, title: str) -> str:
    raw = normalize_url(url) + "|" + normalize_title(title)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def title_key(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:16]


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def domain_matches(domain: str, allowed: list[str]) -> bool:
    domain = domain.lower()
    return any(domain == d or domain.endswith("." + d) for d in allowed)


def classify_source(domain: str, cfg: dict) -> str | None:
    if domain_matches(domain, cfg["official_domains"]):
        return "official"
    if cfg["source_mode"] != "official_only" and domain_matches(domain, cfg["trusted_domains"]):
        return "trusted"
    return None


def match_subjects(text: str, cfg: dict) -> list[str]:
    lowered = text.lower()
    hits = []
    for key, subject in cfg["subjects"].items():
        for kw in subject.get("keywords", []):
            if kw.lower() in lowered:
                hits.append(key)
                break
    return hits


def _entry_ts(entry) -> float:
    for attr in ("published_parsed", "updated_parsed"):
        st = entry.get(attr)
        if st:
            return float(calendar.timegm(st))
    return time.time()


# ── feed URLs ────────────────────────────────────────────────────────────

def bing_url(query: str, lang: str) -> str:
    market = "ar-SA" if lang == "ar" else "en-US"
    return f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt={market}&qft=sortbydate%3d%221%22"


def google_url(query: str, lang: str) -> str:
    if lang == "ar":
        return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d')}&hl=ar&gl=SA&ceid=SA:ar"
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:1d')}&hl=en-US&gl=US&ceid=US:en"


def feed_urls(cfg: dict) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    for lang, queries in (cfg.get("search_queries") or {}).items():
        for q in queries:
            urls.append(("bing", bing_url(q, lang)))
            urls.append(("google", google_url(q, lang)))
    for u in cfg.get("extra_feeds") or []:
        urls.append(("direct", u))
    return urls


# ── parsing ──────────────────────────────────────────────────────────────

def _bing_real_url(link: str) -> str:
    """Bing wraps article links in apiclick.aspx?url=<real>."""
    p = urlparse(link)
    if "bing.com" in p.netloc:
        real = parse_qs(p.query).get("url")
        if real:
            return real[0]
    return link


def parse_feed(kind: str, content: bytes, cfg: dict) -> list[Item]:
    parsed = feedparser.parse(content)
    items: list[Item] = []
    for e in parsed.entries:
        title = clean_text(e.get("title"))
        link = e.get("link") or ""
        if not title or not link:
            continue
        description = clean_text(e.get("summary") or e.get("description"))
        image_hint = None
        source_name = ""
        source_url = ""

        if kind == "bing":
            link = _bing_real_url(link)
            source_name = clean_text(e.get("news_source"))
            img = e.get("news_image")
            if img:
                image_hint = img if img.startswith("http") else None
                if image_hint and "bing.com/th" in image_hint and "&w=" not in image_hint:
                    image_hint += "&w=1200&h=675&c=14"
            source_url = link
        elif kind == "google":
            src = e.get("source") or {}
            source_name = clean_text(src.get("title"))
            source_url = src.get("href") or ""
            # Google appends " - Source" to titles
            if source_name and title.endswith(" - " + source_name):
                title = title[: -len(" - " + source_name)].strip()
        else:
            source_url = link
            source_name = clean_text(parsed.feed.get("title"))
            media = e.get("media_content") or e.get("media_thumbnail") or []
            if media and isinstance(media, list) and media[0].get("url"):
                image_hint = media[0]["url"]
            for enc in e.get("enclosures") or []:
                if (enc.get("type") or "").startswith("image/"):
                    image_hint = image_hint or enc.get("href")

        domain = domain_of(source_url or link)
        items.append(Item(
            title=title,
            url=link,
            source_name=source_name or domain,
            source_domain=domain,
            published_ts=_entry_ts(e),
            description=description if description != title else "",
            image_hint=image_hint,
            feed=kind,
        ))
    return items


def fetch(url: str, timeout: int = 20) -> bytes | None:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ar,en;q=0.8"}, timeout=timeout)
        if r.status_code == 200:
            return r.content
        print(f"  ! {r.status_code} {url[:90]}")
    except requests.RequestException as exc:
        print(f"  ! {type(exc).__name__} {url[:90]}")
    return None


def collect_candidates(cfg: dict, fetcher=fetch) -> list[Item]:
    """Fetch every configured feed and return filtered, de-duplicated items (newest first)."""
    now = time.time()
    max_age = cfg["max_age_hours"] * 3600
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    result: list[Item] = []
    stats = {"fetched": 0, "old": 0, "source": 0, "subject": 0}

    for kind, url in feed_urls(cfg):
        content = fetcher(url)
        if not content:
            continue
        for it in parse_feed(kind, content, cfg):
            stats["fetched"] += 1
            if now - it.published_ts > max_age:
                stats["old"] += 1
                continue
            tier = classify_source(it.source_domain, cfg)
            if kind == "direct" and tier is None:
                tier = "official"  # feeds you added by hand are trusted as official
            if tier is None:
                stats["source"] += 1
                continue
            subjects = match_subjects(f"{it.title} {it.description}", cfg)
            if not subjects:
                stats["subject"] += 1
                continue
            tk = title_key(it.title)
            if it.id in seen_ids or tk in seen_titles:
                continue
            seen_ids.add(it.id)
            seen_titles.add(tk)
            it.tier, it.subjects = tier, subjects
            result.append(it)

    # Official first, then newest first.
    result.sort(key=lambda i: (i.tier != "official", -i.published_ts))
    print(f"  feeds: {stats['fetched']} entries, {stats['old']} too old, "
          f"{stats['source']} untrusted source, {stats['subject']} off-topic → {len(result)} candidates")
    return result
