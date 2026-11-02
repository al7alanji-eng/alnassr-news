"""Minimal X (Twitter) API client: upload one image and create a post (OAuth 1.0a user context)."""
from __future__ import annotations

from requests_oauthlib import OAuth1Session

from .config import env

API = "https://api.x.com"
KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


class XError(RuntimeError):
    pass


def configured() -> bool:
    return all(env(k) for k in KEYS)


def _session() -> OAuth1Session:
    if not configured():
        missing = ", ".join(k for k in KEYS if not env(k))
        raise XError(f"مفاتيح X ناقصة: {missing}")
    return OAuth1Session(env("X_API_KEY"), client_secret=env("X_API_SECRET"),
                         resource_owner_key=env("X_ACCESS_TOKEN"),
                         resource_owner_secret=env("X_ACCESS_TOKEN_SECRET"))


def upload_image(data: bytes, mime: str = "image/jpeg") -> str:
    s = _session()
    # v2 upload first, then the legacy v1.1 endpoint as a fallback.
    r = s.post(f"{API}/2/media/upload", files={"media": ("image.jpg", data, mime)},
               data={"media_category": "tweet_image", "media_type": mime}, timeout=60)
    if r.ok:
        body = r.json()
        media_id = (body.get("data") or {}).get("id") or body.get("media_id_string")
        if media_id:
            return str(media_id)
    r2 = s.post("https://upload.twitter.com/1.1/media/upload.json",
                files={"media": ("image.jpg", data, mime)}, timeout=60)
    if r2.ok and r2.json().get("media_id_string"):
        return r2.json()["media_id_string"]
    raise XError(f"فشل رفع الصورة: {r.status_code} {r.text[:200]} | {r2.status_code} {r2.text[:200]}")


def create_post(text: str, media_id: str | None = None, quote_tweet_id: str | None = None) -> str:
    """Create the post (optionally quoting another post) and return its URL."""
    s = _session()
    payload: dict = {"text": text}
    if quote_tweet_id:
        payload["quote_tweet_id"] = str(quote_tweet_id)
    elif media_id:
        payload["media"] = {"media_ids": [media_id]}
    r = s.post(f"{API}/2/tweets", json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise XError(f"فشل النشر على X: {r.status_code} {r.text[:300]}")
    post_id = r.json()["data"]["id"]
    return f"https://x.com/i/status/{post_id}"
