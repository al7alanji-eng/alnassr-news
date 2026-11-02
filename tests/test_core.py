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
