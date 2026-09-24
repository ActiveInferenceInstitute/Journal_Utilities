"""Tests for M4 static per-item pages (pages_site.py) and builder integration."""

import json
import re
from pathlib import Path

import pytest

from journal_utilities.site.builder import build_site
from journal_utilities.site.pages_site import (
    page_url,
    plan_item_pages,
    plan_sitemap_urls,
    write_item_pages,
)
from journal_utilities.site.sitemap import SitemapUrl, render_robots, render_sitemap

SRT_BODY = "1\n00:00:01,000 --> 00:00:02,000\nsubtitle line\n"


def _make_item(journal: Path, series: str, item: str, meta: dict) -> Path:
    item_dir = journal / "data/video/activeinferenceinstitute" / series / item
    item_dir.mkdir(parents=True)
    (item_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return item_dir


def _make_journal(tmp_path: Path) -> Path:
    """Synthetic 3-item journal: 2 items in Series A, 1 in Series B."""
    journal = tmp_path / "journal"
    journal.mkdir()

    # Item 1: rich — transcript, translations (both spellings), chapters, guests.
    meta1 = {
        "series": "Series A",
        "item": "2021 Talk One",
        "title": "First Talk",
        "date": "2021-06-21",
        "guests": ["Karl J Friston"],
        "paper_title": "Transcript of: First Talk",
        "parts": [
            {
                "video_id": "vid0001",
                "url": "https://www.youtube.com/watch?v=vid0001",
                "title": "Part one",
                "upload_date": "20210621",
                "duration": 300.0,
                "chapters": [
                    {"start": 0, "title": "Welcome"},
                    {"start": 120, "title": "Introduction"},
                ],
            }
        ],
    }
    d1 = _make_item(journal, "Series A", "2021 Talk One", meta1)
    (d1 / "transcript.txt").write_text(
        "## vid0001\n\nhello and welcome\n\nsecond paragraph\n", encoding="utf-8"
    )
    # Both translation-dir spellings (one on-disk dir on case-insensitive
    # macOS; the builder's case-insensitive discovery covers the journal's
    # real mixed-case layout).
    tr = d1 / "translations"
    tr.mkdir()
    (tr / "V.es.srt").write_text(SRT_BODY, encoding="utf-8")
    (tr / "V.chi(translated).srt").write_text(SRT_BODY, encoding="utf-8")

    # Item 2: minimal — no transcript, no date on parts, meta date only.
    meta2 = {
        "series": "Series A",
        "item": "2022 Talk Two",
        "title": "Second Talk",
        "date": "2022-03-05",
        "parts": [{"video_id": "vid0002", "title": "Only part"}],
    }
    _make_item(journal, "Series A", "2022 Talk Two", meta2)

    # Item 3: single-part other series.
    meta3 = {
        "series": "Series B",
        "item": "Seminar X",
        "title": "Third Talk",
        "parts": [{"video_id": "vid0003", "title": "Solo"}],
    }
    d3 = _make_item(journal, "Series B", "Seminar X", meta3)
    (d3 / "transcript.txt").write_text("just one paragraph\n", encoding="utf-8")

    index = {
        "items": [
            {
                "path": "data/video/activeinferenceinstitute/Series A/2021 Talk One",
                "series": "Series A",
                "item": "2021 Talk One",
                "parts": ["vid0001"],
                "has_transcript": True,
            },
            {
                "path": "data/video/activeinferenceinstitute/Series A/2022 Talk Two",
                "series": "Series A",
                "item": "2022 Talk Two",
                "parts": ["vid0002"],
                "has_transcript": False,
            },
            {
                "path": "data/video/activeinferenceinstitute/Series B/Seminar X",
                "series": "Series B",
                "item": "Seminar X",
                "parts": ["vid0003"],
                "has_transcript": True,
            },
        ]
    }
    (journal / "INDEX.json").write_text(json.dumps(index), encoding="utf-8")
    return journal


def _plan(journal: Path, base_url: str = "https://example.com/") -> list:
    entries = []
    for it in json.loads((journal / "INDEX.json").read_text())["items"]:
        meta_path = journal / it["path"] / "metadata.json"
        meta = json.loads(meta_path.read_text())
        meta.setdefault("series", it["series"])
        meta.setdefault("item", it["item"])
        entries.append((it["path"], meta))
    return plan_item_pages(journal, entries, base_url=base_url)


def test_plan_item_pages_count_and_paths(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    plans = _plan(journal)
    assert len(plans) == 3
    rels = {p.rel_path for p in plans}
    assert rels == {
        "item/Series A/2021 Talk One/index.html",
        "item/Series A/2022 Talk Two/index.html",
        "item/Series B/Seminar X/index.html",
    }


def test_item_page_jsonld_parses_with_video_object_and_dataset(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    (plans := _plan(journal))
    html_doc = plans[0].html
    blocks = re.findall(r"application/ld\+json\">(.*?)</script>", html_doc, re.S)
    assert len(blocks) == 2  # Dataset + 1 part
    nodes = [json.loads(b) for b in blocks]
    by_type = {n["@type"]: n for n in nodes}
    ds = by_type["Dataset"]
    assert ds["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert ds["citation"] == "https://doi.org/10.5281/zenodo.7299755"
    assert ds["isPartOf"]["name"] == "Active Inference Journal"
    vo = by_type["VideoObject"]
    assert vo["embedUrl"] == "https://www.youtube-nocookie.com/embed/vid0001"
    assert vo["uploadDate"] == "2021-06-21"
    assert vo["contentUrl"] == "https://www.youtube.com/watch?v=vid0001"
    assert vo["thumbnailUrl"] == ["https://i.ytimg.com/vi/vid0001/hqdefault.jpg"]
    clips = vo["hasPart"]
    assert len(clips) == 2
    assert clips[0]["@type"] == "Clip"
    assert clips[0]["startOffsetTime"] == 0
    assert clips[0]["url"].endswith("?t=0")
    assert clips[1]["endOffsetTime"] == 300  # falls back to part duration
    assert clips[0]["name"] == "Welcome"


def test_item_page_head_tags_and_transcript(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    plans = _plan(journal)
    html_doc = plans[0].html
    # Canonical URL: percent-encoded series/item, trailing slash, no index.html.
    assert (
        '<link rel="canonical" href="'
        + page_url("https://example.com/", "Series A", "2021 Talk One")
        + '">'
        in html_doc
    )
    assert 'href="https://example.com/item/Series%20A/2021%20Talk%20One/">' in html_doc
    assert 'property="og:type" content="video"' in html_doc
    assert 'name="twitter:card" content="summary_large_image"' in html_doc
    # FULL transcript text baked in, part-tagged.
    assert "<p>hello and welcome</p>" in html_doc
    assert "<p>second paragraph</p>" in html_doc
    assert "Part one" in html_doc
    # Guest, date, summary server-rendered.
    assert "Karl J Friston" in html_doc
    assert "Date: 2021-06-21" in html_doc
    assert "Transcript of: First Talk" in html_doc
    # Chapters as jump links.
    assert 'href="https://www.youtube.com/watch?v=vid0001?t=120"' in html_doc
    assert ">Welcome (0:00)</a>" in html_doc and ">Introduction (2:00)</a>" in html_doc
    # YouTube-nocookie embed.
    assert "youtube-nocookie.com/embed/vid0001" in html_doc
    # Languages: union of both translation-dir spellings, chi normalized.
    assert ">es</a>" in html_doc and ">zh-Hans</a>" in html_doc
    assert "chi(translated)" not in html_doc


def test_minimal_item_page_has_no_fabricated_fields(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    plans = _plan(journal)
    doc2 = next(p for p in plans if p.item == "2022 Talk Two").html
    # No date on parts; meta date IS the recorded fallback.
    assert "Date: 2022-03-05" in doc2
    assert "uploadDate" in doc2  # from meta date fallback
    # No chapters section, no translations, no fabricated guests.
    assert "Chapters" not in doc2
    assert "Translations" not in doc2
    assert "Guests" not in doc2
    # Single-part transcript without part markers.
    doc3 = next(p for p in plans if p.item == "Seminar X").html
    assert "<p>just one paragraph</p>" in doc3


def test_write_item_pages(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    plans = _plan(journal)
    out = tmp_path / "out"
    assert write_item_pages(plans, out) == 3
    for plan in plans:
        assert (out / plan.rel_path).read_text(encoding="utf-8") == plan.html


def test_plan_sitemap_urls_bijection(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    plans = _plan(journal)
    urls = plan_sitemap_urls(plans, base_url="https://example.com/")
    # Root + one per item.
    assert len(urls) == 4
    locs = [u.loc for u in urls]
    assert locs[0] == "https://example.com/"
    item_locs = {u.loc for u in urls[1:]}
    assert item_locs == {
        page_url("https://example.com/", "Series A", "2021 Talk One"),
        page_url("https://example.com/", "Series A", "2022 Talk Two"),
        page_url("https://example.com/", "Series B", "Seminar X"),
    }
    # lastmod: strictly max parts[].upload_date (spec §3); items 2/3 have no
    # parts dates, so lastmod is omitted even though item 2 has a meta date
    # (meta date still feeds page display and VideoObject uploadDate).
    mods = {u.loc: u.lastmod for u in urls[1:]}
    assert mods[page_url("https://example.com/", "Series A", "2021 Talk One")] == "2021-06-21"
    assert mods[page_url("https://example.com/", "Series A", "2022 Talk Two")] is None
    assert mods[page_url("https://example.com/", "Series B", "Seminar X")] is None


def test_sitemap_render_and_robots() -> None:
    xml = render_sitemap(
        [
            SitemapUrl(loc="https://example.com/"),
            SitemapUrl(loc="https://example.com/item/A%20B/C/", lastmod="2021-06-21"),
            SitemapUrl(loc="https://example.com/item/D/E/"),
        ]
    )
    assert 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' in xml
    assert xml.count("<url>") == 3
    assert "<lastmod>2021-06-21</lastmod>" in xml
    assert "<changefreq>" not in xml and "<priority>" not in xml
    assert xml.count("<lastmod>") == 1  # never fabricated
    assert "&" not in xml.replace("&amp;", "")
    robots = render_robots("https://example.com/")
    assert robots == ("User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n")


def test_build_site_static_pages_integration(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    out = tmp_path / "site"
    result = build_site(journal_dir=journal, output_dir=out, static_pages=True)
    assert result["items_processed"] == 3
    assert result["pages_written"] == 3
    # sitemap URL count == items (spec §3 post-build assertion).
    sitemap = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert sitemap.count("<loc>") == 4  # root + 3 items
    robots = (out / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap:" in robots
    page = out / "item/Series A/2021 Talk One/index.html"
    assert page.exists()
    assert "hello and welcome" in page.read_text(encoding="utf-8")


def test_build_site_default_off_preserves_spa_only(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    out = tmp_path / "site"
    result = build_site(journal_dir=journal, output_dir=out)
    assert result["pages_written"] == 0
    assert not (out / "sitemap.xml").exists()
    assert not (out / "item").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["total_items"] == 3


def test_build_site_sitemap_count_mismatch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = _make_journal(tmp_path)
    import journal_utilities.site.builder as builder_mod

    real = builder_mod.plan_item_pages

    def short_plans(*args, **kwargs):
        return real(*args, **kwargs)[:-1]  # drop one page

    monkeypatch.setattr(builder_mod, "plan_item_pages", short_plans)
    with pytest.raises(RuntimeError, match="mismatch"):
        build_site(journal_dir=journal, output_dir=tmp_path / "site", static_pages=True)


def test_prev_next_navigation(tmp_path: Path) -> None:
    journal = _make_journal(tmp_path)
    plans = _plan(journal)
    first = next(p for p in plans if p.item == "2021 Talk One").html
    second = next(p for p in plans if p.item == "2022 Talk Two").html
    third = next(p for p in plans if p.item == "Seminar X").html
    # Item 1: no prev, has next.
    assert "Previous in series" not in first
    assert 'href="../../Series%20A/2022%20Talk%20Two/">' in first
    # Item 2: has both.
    assert 'href="../../Series%20A/2021%20Talk%20One/">' in second
    # Item 3: other series, no siblings.
    assert "Previous in series" not in third
    assert "Next in series" not in third
