"""Read the latest posts of the X accounts listed in config.yaml (x_accounts)."""
from __future__ import annotations

import time
from datetime import datetime

from . import x_client
from .sources import Item, match_subjects

API = x_client.API


def _ts(iso: str | None) -> float:
    if not iso:
        return time.time()
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _user_id(session, username: str, state) -> str | None:
    cached = state.x_user_ids.get(username)
    if cached:
        return cached
    r = session.get(f"{API}/2/users/by/username/{username}", timeout=20)
    if not r.ok:
        print(f"  ! X user lookup @{username}: {r.status_code} {r.text[:150]}")
        return None
    uid = r.json().get("data", {}).get("id")
    if uid:
        state.x_user_ids[username] = uid
    return uid


def parse_timeline(body: dict, account: dict, cfg: dict, now: float | None = None) -> list[Item]:
    """Turn a /2/users/:id/tweets response into Items. Kept separate so it can be tested offline."""
    now = now or time.time()
    username, name = account["username"], account.get("name") or account["username"]
    media = {m["media_key"]: m for m in (body.get("includes") or {}).get("media", [])}
    items: list[Item] = []
    for tw in body.get("data") or []:
        text = ((tw.get("note_tweet") or {}).get("text") or tw.get("text") or "").strip()
        if not text:
            continue
        ts = _ts(tw.get("created_at"))
        if now - ts > cfg["max_age_hours"] * 3600:
            continue
        subjects = match_subjects(text, cfg)
        if account.get("require_keywords", True) and not subjects:
            continue
        image = None
        for key in (tw.get("attachments") or {}).get("media_keys", []):
            m = media.get(key) or {}
            if m.get("type") == "photo" and m.get("url"):
                image = m["url"] + ("&" if "?" in m["url"] else "?") + "name=large"
                break
        first_line = text.split("\n", 1)[0][:140]
        items.append(Item(
            title=first_line,
            url=f"https://x.com/{username}/status/{tw['id']}",
            source_name=name,
            source_domain="x.com",
            published_ts=ts,
            description=text,
            image_hint=image,
            feed="x",
            tier="x",
            subjects=subjects,
            quote_tweet_id=tw["id"] if account.get("quote", True) else None,
        ))
    return items


def collect_x_accounts(cfg: dict, state) -> list[Item]:
    accounts = cfg.get("x_accounts") or []
    if not accounts:
        return []
    if not x_client.configured():
        print("  X accounts skipped: X keys are not set")
        return []
    session = x_client._session()
    result: list[Item] = []
    for account in accounts:
        username = account["username"].lstrip("@")
        account = {**account, "username": username}
        uid = _user_id(session, username, state)
        if not uid:
            continue
        params = {
            "max_results": 10,
            "exclude": "retweets,replies",
            "tweet.fields": "created_at,note_tweet,attachments",
            "expansions": "attachments.media_keys",
            "media.fields": "url,type",
        }
        since = state.x_since_ids.get(username)
        if since:
            params["since_id"] = since
        r = session.get(f"{API}/2/users/{uid}/tweets", params=params, timeout=20)
        if not r.ok:
            print(f"  ! X timeline @{username}: {r.status_code} {r.text[:150]}")
            continue
        body = r.json()
        newest = (body.get("meta") or {}).get("newest_id")
        if newest:
            state.x_since_ids[username] = newest
        items = parse_timeline(body, account, cfg)
        print(f"  @{username}: {len(body.get('data') or [])} new posts → {len(items)} candidates")
        result.extend(items)
    return result
