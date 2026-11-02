"""Publish an approved draft to X.

Runs in GitHub Actions when a draft Issue gets the `approved` label or a `/publish` comment.
Local use:  python -m bot.publish --issue 12
"""
from __future__ import annotations

import argparse
import json
import sys

from . import x_client
from .article import download_image
from .config import env
from .drafts import feed_entry, parse_body
from .github_api import GitHub
from .store import add_to_feed
from .tweet import MAX_WEIGHT, weighted_length


def post_to_x(tweet: str, image_url: str | None) -> str:
    """Upload the image (if any) and create the post. Returns the post URL."""
    media_id = None
    if image_url:
        img = download_image(image_url)
        if img:
            media_id = x_client.upload_image(*img)
        else:
            print(f"  ! image could not be downloaded, posting without it: {image_url}")
    return x_client.create_post(tweet, media_id)


def publish_issue(gh: GitHub, number: int) -> bool:
    issue = gh.get_issue(number)
    labels = {l["name"] for l in issue.get("labels", [])}
    if "published" in labels:
        print(f"#{number} already published")
        return True
    if "draft" not in labels:
        print(f"#{number} is not a bot draft; skipping")
        return True

    try:
        draft = parse_body(issue.get("body") or "")
        length = weighted_length(draft["tweet"])
        if length > MAX_WEIGHT:
            raise ValueError(f"التغريدة طويلة ({length} من {MAX_WEIGHT}). اختصرها وأعد الموافقة.")
        post_url = post_to_x(draft["tweet"], draft["image_url"])
    except (ValueError, x_client.XError) as exc:
        gh.comment(number, f"❌ ما قدرت أنشر.\n\n**السبب:** {exc}\n\nبعد ما تصلح المشكلة، شيل وسم `approved` وأضفه مرة ثانية، أو اكتب `/publish`.")
        gh.remove_label(number, "approved")
        gh.add_labels(number, ["publish-failed"])
        print(f"#{number} failed: {exc}")
        return False

    add_to_feed(feed_entry(meta=draft["meta"], tweet=draft["tweet"], image_url=draft["image_url"], post_url=post_url))
    gh.comment(number, f"✅ تم النشر: {post_url}")
    gh.remove_label(number, "publish-failed")
    gh.add_labels(number, ["published"])
    gh.close(number)
    print(f"#{number} published → {post_url}")
    return True


def _issue_from_event() -> int | None:
    path = env("GITHUB_EVENT_PATH")
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    issue = event.get("issue") or {}
    return issue.get("number")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", type=int, help="رقم المسودة (Issue)")
    args = ap.parse_args()
    number = args.issue or _issue_from_event()
    if not number:
        print("No issue number given")
        return 1
    return 0 if publish_issue(GitHub(), number) else 1


if __name__ == "__main__":
    sys.exit(main())
