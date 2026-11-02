"""Collect news, rewrite it, and queue drafts for review (or publish directly).

Runs every 15 minutes in GitHub Actions.
Local test without any keys:  python -m bot.collect --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time

from . import x_client
from .article import download_image, read_article
from .config import load_config
from .drafts import SUBJECT_LABELS, build_body, feed_entry, issue_title
from .github_api import GitHub
from .publish import post_to_x
from .rewrite import rewrite
from .sources import collect_candidates, title_key
from .store import State, add_to_feed, load_feed, touch_feed
from .x_source import collect_x_accounts
from .article import Article
from .tweet import compose


def pick_image(item, art) -> str | None:
    for url in (art.image_url, item.image_hint):
        if url and download_image(url):
            return url
    return None


def run(dry_run: bool = False) -> int:
    cfg = load_config()
    state = State()
    gh = None if dry_run or not GitHub.available() else GitHub()
    if gh:
        gh.ensure_labels({name: (color, f"خبر عن {name}") for name, color in SUBJECT_LABELS.values()})
    if not dry_run and cfg["auto_publish"] and not x_client.configured():
        print("! auto_publish is on but X keys are missing; drafts will be queued for review instead")

    print("Collecting news…")
    found = collect_candidates(cfg)
    if not dry_run:
        found += collect_x_accounts(cfg, state)
    candidates = [c for c in found if not state.is_seen(c.id, title_key(c.title))]
    print(f"  {len(candidates)} new")

    created = 0
    for item in candidates[: cfg["max_items_per_run"]]:
        state.mark(item.id, title_key(item.title))
        print(f"\n→ [{item.tier}] {item.source_name}: {item.title}")
        art = Article(url=item.url, text=item.description) if item.feed == "x" else read_article(item.url)
        link = art.url if cfg["include_link"] and not item.quote_tweet_id else None
        draft = rewrite(item, art, state.recent_headlines(), cfg, link)
        if not draft.relevant or draft.duplicate:
            print(f"  skip: {'duplicate' if draft.duplicate else 'not relevant'} — {draft.reason}")
            continue

        state.remember(draft.headline)
        image_url = pick_image(item, art)
        tweet = compose(draft.tweet, item.source_name, link, cfg["hashtags"])
        meta = {
            "id": item.id, "headline": draft.headline, "summary": draft.summary,
            "source_name": item.source_name, "source_url": art.url, "tier": item.tier,
            "kind": draft.kind, "subjects": draft.subjects or item.subjects,
            "quote_tweet_id": item.quote_tweet_id,
        }

        if dry_run or not gh:
            print("  ── draft ──\n  " + tweet.replace("\n", "\n  "))
            print(f"  image: {image_url or '-'}")
            created += 1
            continue

        if cfg["auto_publish"] and x_client.configured():
            try:
                post_url = post_to_x(tweet, image_url, item.quote_tweet_id)
                add_to_feed(feed_entry(meta=meta, tweet=tweet, image_url=image_url, post_url=post_url))
                print(f"  published → {post_url}")
                created += 1
                continue
            except x_client.XError as exc:
                print(f"  ! auto publish failed, queueing for review: {exc}")

        labels = ["draft", "official" if item.tier == "official" else "x-account" if item.tier == "x"
                  else "report" if draft.is_report else None]
        labels += [SUBJECT_LABELS[s][0] for s in meta["subjects"] if s in SUBJECT_LABELS]
        body = build_body(tweet=tweet, image_url=image_url, source_name=item.source_name, source_url=art.url,
                          tier=item.tier, headline=draft.headline, summary=draft.summary, kind=draft.kind,
                          meta=meta, reason=draft.reason, rewritten=draft.rewritten)
        issue = gh.create_issue(issue_title(draft.headline, item.tier), body, [l for l in labels if l])
        print(f"  draft → {issue.get('html_url')}")
        created += 1

    if not dry_run:
        state.save()
        checked = load_feed().get("checked_at")
        if created or not checked or _older_than(checked, 3600):
            touch_feed()
    print(f"\nDone: {created} new drafts/posts")
    return 0


def _older_than(iso: str, seconds: int) -> bool:
    from datetime import datetime
    try:
        return time.time() - datetime.fromisoformat(iso).timestamp() > seconds
    except ValueError:
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="اعرض المسودات فقط بدون نشر أو حفظ")
    return run(dry_run=ap.parse_args().dry_run)


if __name__ == "__main__":
    sys.exit(main())
