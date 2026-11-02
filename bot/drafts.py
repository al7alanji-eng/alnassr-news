"""Build and parse the GitHub Issue that holds one draft post."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

MARKER = "<!-- alnassr-bot:draft v1 -->"
SUBJECT_LABELS = {
    "alnassr": ("النصر", "FCD116"),
    "ronaldo": ("رونالدو", "E8A33D"),
    "felix": ("فيليكس", "4C8DF6"),
    "mane": ("ماني", "34A853"),
    "coman": ("كومان", "A142F4"),
}


def _between(body: str, name: str) -> str | None:
    m = re.search(rf"<!--\s*{name}:start\s*-->(.*?)<!--\s*{name}:end\s*-->", body, re.S)
    return m.group(1).strip() if m else None


def build_body(*, tweet: str, image_url: str | None, source_name: str, source_url: str, tier: str,
               headline: str, summary: str, kind: str, meta: dict, reason: str = "", rewritten: bool = True) -> str:
    tier_label = "جهة رسمية" if tier == "official" else "وسيلة إعلام موثوقة"
    image_block = f"<!-- image:start -->{image_url}<!-- image:end -->\n\n![صورة الخبر]({image_url})" if image_url \
        else "<!-- image:start --><!-- image:end -->\n\nلم أجد صورة مناسبة. تقدر تضيف رابط صورة بين العلامتين فوق."
    note = "" if rewritten else "\n> ⚠️ هذا النص هو العنوان الأصلي بدون إعادة صياغة لأن مفتاح Claude غير مضاف.\n"
    return f"""{MARKER}
### ✍️ نص التغريدة
عدّل النص بين العلامتين إذا تبي، وبعدين وافق.
{note}
<!-- tweet:start -->
{tweet}
<!-- tweet:end -->

### 🖼️ الصورة
{image_block}

### 📰 المصدر
- **الجهة:** {source_name} ({tier_label})
- **الرابط:** {source_url}
- **التصنيف:** {kind}

### 📝 ملخص للوحة العرض
**{headline}**

{summary}

---
**✅ للنشر:** أضف الوسم `approved`، أو اكتب تعليق `/publish`.
**❌ للرفض:** أغلق المسودة.

<!-- meta:{json.dumps(meta, ensure_ascii=False)} -->
"""


def parse_body(body: str) -> dict:
    if MARKER not in (body or ""):
        raise ValueError("هذه ليست مسودة من البوت")
    tweet = _between(body, "tweet")
    if not tweet:
        raise ValueError("ما لقيت نص التغريدة بين العلامتين tweet:start و tweet:end")
    image = (_between(body, "image") or "").strip() or None
    meta_match = re.search(r"<!-- meta:(\{.*?\}) -->", body, re.S)
    meta = json.loads(meta_match.group(1)) if meta_match else {}
    return {"tweet": tweet, "image_url": image, "meta": meta}


def issue_title(headline: str, tier: str) -> str:
    prefix = "🟡 رسمي" if tier == "official" else "📰"
    return f"{prefix} | {headline}"[:200]


def feed_entry(*, meta: dict, tweet: str, image_url: str | None, post_url: str | None) -> dict:
    return {
        "id": meta.get("id"),
        "headline": meta.get("headline"),
        "summary": meta.get("summary"),
        "text": tweet,
        "image": image_url,
        "source": meta.get("source_name"),
        "source_url": meta.get("source_url"),
        "tier": meta.get("tier"),
        "kind": meta.get("kind"),
        "subjects": meta.get("subjects", []),
        "post_url": post_url,
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
