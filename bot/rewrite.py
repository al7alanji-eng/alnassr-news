"""Rewrite a news item as an Arabic post with Claude (structured JSON output)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import anthropic

from .article import Article
from .config import env
from .sources import Item
from .tweet import body_budget, weighted_length

KINDS = ["رسمي", "مباراة", "إصابة", "انتقالات", "أرقام", "تصريحات", "تقارير", "أخرى"]

SYSTEM_PROMPT = """أنت محرر أخبار رياضية لحساب سعودي على منصة X يغطي نادي النصر ولاعبيه: كريستيانو رونالدو، جواو فيليكس، ساديو ماني، كينغسلي كومان.

مهمتك: تقرأ خبرًا من مصدر واحد وتعيد صياغته بالعربية الفصحى المبسطة بأسلوب صحفي سعودي واضح.

قواعد ملزمة:
- اكتب فقط ما هو موجود في نص المصدر. لا تضف أرقامًا أو أسماء أو تواريخ أو نتائج غير مذكورة فيه.
- إذا كان الخبر تقريرًا أو شائعة وليس إعلانًا رسميًا، ابدأ التغريدة بكلمة "تقارير:" ولا تقدمه كحقيقة مؤكدة.
- لا تنسخ جملًا من المصدر حرفيًا؛ أعد الصياغة بكلماتك.
- بدون مبالغة أو عناوين مثيرة أو علامات تعجب متكررة. إيموجي واحد على الأكثر في بداية التغريدة.
- اكتب أسماء اللاعبين بالعربية: رونالدو، جواو فيليكس، ساديو ماني، كومان.
- لا تضع روابط في التغريدة. الوسوم والمصدر يضيفها النظام تلقائيًا، فلا تكتبها.

اعتبر الخبر غير مناسب (relevant = false) إذا:
- لم يكن عن نادي النصر السعودي أو أحد اللاعبين الأربعة (مثلًا: نادٍ آخر اسمه النصر، أو رونالد كومان المدرب، أو لاعب آخر اسمه ماني).
- كان مجرد إعلان أو صفحة نتائج أو استطلاع بدون خبر فعلي.
- كان نص المصدر غير كافٍ لكتابة خبر دقيق.

اعتبره مكررًا (duplicate = true) إذا كان نفس الحدث الموجود في قائمة "أخبار نُشرت مؤخرًا" حتى لو اختلفت الصياغة أو اللغة."""

SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "duplicate": {"type": "boolean"},
        "reason": {"type": "string", "description": "سبب قصير للقرار"},
        "subjects": {"type": "array", "items": {"type": "string", "enum": ["alnassr", "ronaldo", "felix", "mane", "coman"]}},
        "kind": {"type": "string", "enum": KINDS},
        "is_report": {"type": "boolean", "description": "true إذا كان تقريرًا أو شائعة غير مؤكدة"},
        "headline": {"type": "string", "description": "عنوان عربي قصير للوحة العرض"},
        "summary": {"type": "string", "description": "ملخص عربي من جملتين أو ثلاث للوحة العرض"},
        "tweet": {"type": "string", "description": "نص التغريدة بدون وسوم أو مصدر أو روابط"},
    },
    "required": ["relevant", "duplicate", "reason", "subjects", "kind", "is_report", "headline", "summary", "tweet"],
    "additionalProperties": False,
}


@dataclass
class Draft:
    relevant: bool
    duplicate: bool
    reason: str
    subjects: list[str]
    kind: str
    is_report: bool
    headline: str
    summary: str
    tweet: str
    rewritten: bool = True
    extra: dict = field(default_factory=dict)


def fallback_draft(item: Item) -> Draft:
    """Used when no ANTHROPIC_API_KEY is set: keep the original headline, no rewriting."""
    return Draft(True, False, "بدون إعادة صياغة (لا يوجد مفتاح Claude)", item.subjects,
                 "رسمي" if item.tier == "official" else "تقارير", item.tier != "official",
                 item.title, item.description[:300], item.title, rewritten=False)


def _user_message(item: Item, art: Article, recent: list[str], budget: int) -> str:
    source_text = art.text or art.description or item.description
    recent_block = "\n".join(f"- {h}" for h in recent[-40:]) or "(لا يوجد)"
    return (
        f"<source tier=\"{'جهة رسمية' if item.tier == 'official' else 'وسيلة إعلام'}\">\n"
        f"الجهة: {item.source_name} ({item.source_domain})\n"
        f"العنوان: {item.title}\n"
        f"الوصف: {item.description or art.description}\n"
        f"النص:\n{source_text[:4000] or '(غير متوفر)'}\n"
        f"</source>\n\n"
        f"<recent_posts>\n{recent_block}\n</recent_posts>\n\n"
        f"حد التغريدة: {budget} حرفًا كحد أقصى (العربية تُحسب حرفًا واحدًا، والإيموجي حرفين)."
    )


def rewrite(item: Item, art: Article, recent: list[str], cfg: dict, url_in_tweet: str | None) -> Draft:
    if not env("ANTHROPIC_API_KEY"):
        return fallback_draft(item)

    client = anthropic.Anthropic()
    budget = body_budget(item.source_name, url_in_tweet, cfg["hashtags"])
    messages = [{"role": "user", "content": _user_message(item, art, recent, budget)}]

    draft: Draft | None = None
    for attempt in range(2):
        try:
            response = client.beta.messages.create(
                model=cfg["claude_model"],
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=messages,
                output_config={"effort": cfg["claude_effort"], "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError:
            time.sleep(20)
            continue
        except anthropic.APIStatusError as exc:
            print(f"  ! Claude API error {exc.status_code}: {exc.message[:200]}")
            return fallback_draft(item)
        except anthropic.APIConnectionError:
            print("  ! Claude API connection error")
            return fallback_draft(item)

        if response.stop_reason == "refusal":
            return Draft(False, False, "رفض النموذج معالجة الخبر", item.subjects, "أخرى", False, item.title, "", "")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print("  ! Claude returned invalid JSON")
            return fallback_draft(item)
        draft = Draft(**data)

        if not draft.relevant or draft.duplicate or weighted_length(draft.tweet) <= budget:
            return draft
        # Too long: ask once for a shorter version.
        messages += [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": f"التغريدة طولها {weighted_length(draft.tweet)} وتتجاوز الحد ({budget}). اختصرها مع الحفاظ على المعلومة الأهم، وأعد نفس JSON."},
        ]

    if draft is None:
        return fallback_draft(item)
    if weighted_length(draft.tweet) > budget:
        draft.tweet = draft.tweet[: budget - 1].rstrip() + "…"
    return draft
