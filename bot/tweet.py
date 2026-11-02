"""Tweet length counting (X's weighted rules) and final tweet assembly."""
from __future__ import annotations

import re

MAX_WEIGHT = 280
URL_WEIGHT = 23
_URL_RE = re.compile(r"https?://\S+")
# Ranges X counts as weight 1 (Latin, Arabic, Hebrew, Cyrillic, punctuation...). Everything else counts 2.
_LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))


def weighted_length(text: str) -> int:
    total = 0
    for part in _URL_RE.split(text):
        for ch in part:
            cp = ord(ch)
            total += 1 if any(lo <= cp <= hi for lo, hi in _LIGHT_RANGES) else 2
    total += URL_WEIGHT * len(_URL_RE.findall(text))
    return total


def compose(body: str, source_name: str, url: str | None, hashtags: list[str]) -> str:
    """Body from Claude + hashtags missing from it + source credit (+ optional link)."""
    body = body.strip()
    tags = [h for h in hashtags if h and h not in body]
    lines = [body]
    if tags:
        lines.append(" ".join(tags))
    credit = f"المصدر: {source_name}" if source_name else ""
    if url:
        credit = f"{credit}\n{url}" if credit else url
    if credit:
        lines.append(credit)
    return "\n\n".join(lines)


def body_budget(source_name: str, url: str | None, hashtags: list[str]) -> int:
    """How many weighted characters Claude may use for the body."""
    overhead = weighted_length(compose("", source_name, url, hashtags))
    return MAX_WEIGHT - overhead - 4
