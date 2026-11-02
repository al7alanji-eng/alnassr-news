import time
from email.utils import formatdate

from bot.config import load_config
from bot.drafts import build_body, parse_body
from bot.sources import classify_source, collect_candidates, match_subjects
from bot.tweet import compose, weighted_length

NOW = formatdate(time.time() - 1800, usegmt=True)
OLD = formatdate(time.time() - 3 * 86400, usegmt=True)

BING = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss">
<channel><title>Bing</title>
<item><title>رونالدو يقود النصر للفوز على الحزم</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;url=https%3a%2f%2fwww.spl.com.sa%2far%2fnews%2f123&amp;c=1</link>
<description>سجل رونالدو هدفين في فوز النصر.</description><pubDate>{NOW}</pubDate>
<News:Source>SPL</News:Source><News:Image>https://www.bing.com/th?id=OVFT.abc&amp;pid=News</News:Image></item>
<item><title>Ronaldo scores for Al Nassr</title>
<link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2frandomblog.example%2fpost&amp;c=1</link>
<pubDate>{NOW}</pubDate><News:Source>Random Blog</News:Source></item>
<item><title>النصر يستعد للمباراة القادمة</title>
<link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.arriyadiyah.com%2f999&amp;c=1</link>
<pubDate>{OLD}</pubDate><News:Source>الرياضية</News:Source></item>
<item><title>الهلال يفوز على الاتحاد</title>
<link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.arriyadiyah.com%2f1000&amp;c=1</link>
<pubDate>{NOW}</pubDate><News:Source>الرياضية</News:Source></item>
</channel></rss>"""

GOOGLE = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>رونالدو يقود النصر للفوز على الحزم - SPL</title>
<link>https://news.google.com/rss/articles/CBMiXYZ?oc=5</link><pubDate>{NOW}</pubDate>
<source url="https://www.spl.com.sa">SPL</source></item>
<item><title>Joao Felix brace as Al Nassr beat Pakhtakor - ESPN</title>
<link>https://news.google.com/rss/articles/CBMiABC?oc=5</link><pubDate>{NOW}</pubDate>
<source url="https://www.espn.com">ESPN</source></item>
</channel></rss>"""


def fake_fetch(url):
    if "bing.com" in url:
        return BING.encode()
    if "news.google.com" in url:
        return GOOGLE.encode()
    return None


def test_collect_filters_and_dedupes():
    cfg = load_config()
    items = collect_candidates(cfg, fetcher=fake_fetch)
    titles = [i.title for i in items]
    # duplicate across Bing and Google and across queries collapses to one
    assert titles.count("رونالدو يقود النصر للفوز على الحزم") == 1
    assert "Joao Felix brace as Al Nassr beat Pakhtakor" in titles
    assert not any("randomblog" in i.url for i in items), "untrusted source must be dropped"
    assert not any("الهلال" in t for t in titles), "off-topic item must be dropped"
    assert not any("يستعد" in t for t in titles), "old item must be dropped"
    first = items[0]
    assert first.tier == "official" and first.url.startswith("https://www.spl.com.sa")
    assert first.image_hint and "&w=1200" in first.image_hint
    assert "ronaldo" in first.subjects and "alnassr" in first.subjects


def test_source_tiers():
    cfg = load_config()
    assert classify_source("spl.com.sa", cfg) == "official"
    assert classify_source("sport.alnassr.sa", cfg) == "official"
    assert classify_source("espn.com", cfg) == "trusted"
    assert classify_source("evil-espn.com", cfg) is None
    cfg["source_mode"] = "official_only"
    assert classify_source("espn.com", cfg) is None


def test_subject_matching():
    cfg = load_config()
    assert set(match_subjects("Kingsley Coman and Sadio Mané", cfg)) == {"coman", "mane"}


def test_weighted_length():
    assert weighted_length("النصر") == 5
    assert weighted_length("https://example.com/very/long/path") == 23
    assert weighted_length("😀") == 2  # emoji count as 2 on X


def test_compose_and_draft_roundtrip():
    tweet = compose("⚽ النصر يفوز", "SPL", None, ["#النصر"])
    assert tweet.endswith("المصدر: SPL") and "#النصر" in tweet
    meta = {"id": "abc", "headline": "عنوان", "subjects": ["alnassr"]}
    body = build_body(tweet=tweet, image_url="https://img.example/a.jpg", source_name="SPL",
                      source_url="https://spl.com.sa/1", tier="official", headline="عنوان",
                      summary="ملخص", kind="رسمي", meta=meta)
    parsed = parse_body(body)
    assert parsed["tweet"] == tweet
    assert parsed["image_url"] == "https://img.example/a.jpg"
    assert parsed["meta"] == meta
    # user removes the image and edits the text
    edited = body.replace("https://img.example/a.jpg<!-- image:end -->", "<!-- image:end -->").replace("يفوز", "يكسب")
    parsed = parse_body(edited)
    assert parsed["image_url"] is None and "يكسب" in parsed["tweet"]


def test_new_sources_in_config():
    cfg = load_config()
    from bot.sources import feed_urls
    urls = [u for _, u in feed_urls(cfg)]
    assert any("site%3Amarca.com" in u and "mkt=es-ES" in u for u in urls)
    assert any("site%3Amarca.com" in u and "hl=es&gl=ES&ceid=ES:es" in u for u in urls)
    assert any("site%3Aarriyadiyah.com" in u for u in urls)
    assert any("site%3Aaawsat.com" in u for u in urls)
    assert classify_source("marca.com", cfg) == "trusted"
    assert any(a["username"] == "saadlegal2030" for a in cfg["x_accounts"])


def test_x_timeline_parsing():
    from datetime import datetime, timezone
    from bot.x_source import parse_timeline
    cfg = load_config()
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    body = {
        "data": [
            {"id": "111", "text": "خاص: إدارة الفريق تقترب من حسم صفقة جديدة", "created_at": now_iso,
             "attachments": {"media_keys": ["m1"]}},
            {"id": "112", "text": "قصير", "note_tweet": {"text": "نص طويل كامل عن رونالدو"}, "created_at": now_iso},
            {"id": "100", "text": "قديم", "created_at": "2020-01-01T00:00:00Z"},
        ],
        "includes": {"media": [{"media_key": "m1", "type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"}]},
        "meta": {"newest_id": "112"},
    }
    account = {"username": "saadlegal2030", "name": "سعد السبيعي", "quote": True, "require_keywords": False}
    items = parse_timeline(body, account, cfg)
    assert [i.quote_tweet_id for i in items] == ["111", "112"]
    assert items[0].tier == "x" and items[0].source_name == "سعد السبيعي"
    assert items[0].url == "https://x.com/saadlegal2030/status/111"
    assert items[0].image_hint == "https://pbs.twimg.com/media/a.jpg?name=large"
    assert items[1].description == "نص طويل كامل عن رونالدو" and "ronaldo" in items[1].subjects
    # with keywords required, the post that names no subject is dropped
    strict = parse_timeline(body, {**account, "require_keywords": True}, cfg)
    assert [i.quote_tweet_id for i in strict] == ["112"]
