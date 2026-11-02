"""Load config.yaml and resolve project paths."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
STATE_FILE = DATA_DIR / "state.json"
FEED_FILE = DOCS_DIR / "feed.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("auto_publish", False)
    cfg.setdefault("include_link", False)
    cfg.setdefault("hashtags", ["#النصر"])
    cfg.setdefault("claude_model", "claude-opus-5-5")
    cfg.setdefault("claude_effort", "low")
    cfg.setdefault("max_age_hours", 12)
    cfg.setdefault("max_items_per_run", 6)
    cfg.setdefault("source_mode", "official_and_trusted")
    cfg.setdefault("extra_feeds", [])
    cfg.setdefault("official_domains", [])
    cfg.setdefault("trusted_domains", [])
    return cfg


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None
