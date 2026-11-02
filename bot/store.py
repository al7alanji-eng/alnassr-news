"""Persistent state (seen items) and the public feed shown on the dashboard."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import FEED_FILE, STATE_FILE

SEEN_TTL = 7 * 24 * 3600
FEED_LIMIT = 200


def _read(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    tmp.replace(path)


class State:
    """Which items were already handled, plus recent headlines for duplicate checks."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        data = _read(path, {})
        self.seen: dict[str, float] = data.get("seen", {})
        self.titles: dict[str, float] = data.get("titles", {})
        self.recent: list[dict] = data.get("recent", [])
        self.last_run: float = data.get("last_run", 0)

    def is_seen(self, item_id: str, title_key: str) -> bool:
        return item_id in self.seen or title_key in self.titles

    def mark(self, item_id: str, title_key: str) -> None:
        now = time.time()
        self.seen[item_id] = now
        self.titles[title_key] = now

    def remember(self, headline: str) -> None:
        self.recent.append({"h": headline, "t": time.time()})
        self.recent = self.recent[-60:]

    def recent_headlines(self) -> list[str]:
        cutoff = time.time() - 3 * 24 * 3600
        return [r["h"] for r in self.recent if r["t"] > cutoff]

    def save(self) -> None:
        cutoff = time.time() - SEEN_TTL
        self.seen = {k: v for k, v in self.seen.items() if v > cutoff}
        self.titles = {k: v for k, v in self.titles.items() if v > cutoff}
        self.last_run = time.time()
        _write(self.path, {"last_run": self.last_run, "seen": self.seen, "titles": self.titles, "recent": self.recent})


def load_feed(path: Path = FEED_FILE) -> dict:
    return _read(path, {"updated_at": None, "items": []})


def add_to_feed(entry: dict, path: Path = FEED_FILE) -> None:
    feed = load_feed(path)
    items = [i for i in feed.get("items", []) if i.get("id") != entry.get("id")]
    items.insert(0, entry)
    items.sort(key=lambda i: i.get("published_at", ""), reverse=True)
    feed["items"] = items[:FEED_LIMIT]
    feed["updated_at"] = entry.get("published_at")
    _write(path, feed)


def touch_feed(path: Path = FEED_FILE) -> None:
    """Record that the bot checked for news, so the dashboard can show it is alive."""
    from datetime import datetime, timezone
    feed = load_feed(path)
    feed["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write(path, feed)
