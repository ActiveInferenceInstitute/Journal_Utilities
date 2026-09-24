"""Tests for static site builder (GitHub Pages generation)."""

import json
import re
from pathlib import Path

import pytest

from journal_utilities.site.builder import (
    build_item_payload,
    build_site,
    parse_srt,
    translation_lang_key,
)


def test_parse_srt() -> None:
    srt_text = (
        "1\n00:00:01,000 --> 00:00:04,500\nHello and welcome!\n\n"
        "2\n00:00:05,000 --> 00:00:08,200\nToday we talk about Active Inference.\n"
    )
    cues = parse_srt(srt_text)
    assert len(cues) == 2
    assert cues[0]["start"] == 1.0
    assert cues[0]["end"] == 4.5
    assert cues[0]["text"] == "Hello and welcome!"
    assert cues[1]["start"] == 5.0
    assert cues[1]["end"] == 8.2


def test_build_item_payload_and_site(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    item_dir = journal_dir / "data/video/activeinferenceinstitute/Livestream/LiveStream_001"
    item_dir.mkdir(parents=True)

    meta = {
        "series": "Livestream",
        "item": "LiveStream_001",
        "title": "Introduction to Active Inference",
        "category": "Livestream",
        "episode": "1",
        "parts": [
            {"video_id": "test_vid_123", "title": "Part 1", "speakers": {"SPEAKER_00": "Daniel"}}
        ],
    }
    (item_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (item_dir / "transcript.txt").write_text("Hello world transcript", encoding="utf-8")

    # Add translations
    tr_dir = item_dir / "translations"
    tr_dir.mkdir()
    (tr_dir / "LiveStream_001.es.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHola mundo\n", encoding="utf-8"
    )

    # Add INDEX.json
    index_data = {
        "count": 1,
        "items": [
            {
                "path": "data/video/activeinferenceinstitute/Livestream/LiveStream_001",
                "series": "Livestream",
                "item": "LiveStream_001",
                "has_transcript": True,
            }
        ],
    }
    (journal_dir / "INDEX.json").write_text(json.dumps(index_data), encoding="utf-8")

    payload = build_item_payload(item_dir, meta)
    assert payload["id"] == "Livestream/LiveStream_001"
    assert "es" in payload["translations"]
    assert len(payload["translations"]["es"][0]["cues"]) == 1

    out_dir = tmp_path / "site_out"
    res = build_site(journal_dir=journal_dir, output_dir=out_dir)
    assert res["items_processed"] == 1
    assert (out_dir / "index.html").exists()
    assert (out_dir / "styles.css").exists()
    assert (out_dir / "app.js").exists()
    assert (out_dir / "manifest.json").exists()

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_items"] == 1
    assert manifest["items"][0]["languages"] == ["es"]


SRT_BODY = "1\n00:00:01,000 --> 00:00:02,000\nsubtitle line\n"


def test_translation_lang_key_variants() -> None:
    assert translation_lang_key(Path("V.es.srt")) == "es"
    assert translation_lang_key(Path("V.chi(translated).srt")) == "chi"
    assert translation_lang_key(Path("V.zh-Hans.srt")) == "zh-Hans"
    assert translation_lang_key(Path("V.en(ca).srt")) == "en"
    assert translation_lang_key(Path("V.ger(translated).srt")) == "ger"
    assert translation_lang_key(Path("V.srt")) is None
    assert translation_lang_key(Path("dump_transcript.srt")) is None
    assert translation_lang_key(Path("08 ~ Governing_transcript.srt")) is None


def test_build_item_payload_reads_capital_translations_dir(tmp_path: Path) -> None:
    item_dir = tmp_path / "item"
    tr_dir = item_dir / "Translations"
    tr_dir.mkdir(parents=True)
    (tr_dir / "V.chi(translated).srt").write_text(SRT_BODY, encoding="utf-8")
    # Garbage-named file without a language tag must be ignored, not crash.
    (tr_dir / "dump_transcript.srt").write_text(SRT_BODY, encoding="utf-8")

    payload = build_item_payload(item_dir, {"series": "S", "item": "I", "parts": []})

    assert list(payload["translations"]) == ["chi"]
    assert payload["translations"]["chi"][0]["file"] == "V.chi(translated).srt"
    assert len(payload["translations"]["chi"][0]["cues"]) == 1


def test_build_item_payload_matches_uppercase_srt_extension(tmp_path: Path) -> None:
    item_dir = tmp_path / "item"
    tr_dir = item_dir / "Translations"
    tr_dir.mkdir(parents=True)
    (tr_dir / "V.fr.SRT").write_text(SRT_BODY, encoding="utf-8")

    payload = build_item_payload(item_dir, {"series": "S", "item": "I", "parts": []})

    assert "fr" in payload["translations"]


def test_build_item_payload_dedupes_both_dir_spellings(tmp_path: Path) -> None:
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    if (tmp_path / "caseprobe").exists():
        pytest.skip("case-insensitive filesystem cannot hold both dir spellings")

    item_dir = tmp_path / "item"
    (item_dir / "translations").mkdir(parents=True)
    (item_dir / "Translations").mkdir()
    (item_dir / "translations" / "V.fr.srt").write_text(SRT_BODY, encoding="utf-8")
    (item_dir / "Translations" / "V.fr.srt").write_text(SRT_BODY, encoding="utf-8")

    payload = build_item_payload(item_dir, {"series": "S", "item": "I", "parts": []})

    # The same file under both spellings must appear once, from lowercase dir.
    assert len(payload["translations"]["fr"]) == 1
    assert payload["translations"]["fr"][0]["file"] == "V.fr.srt"


def test_build_site_manifest_languages_capital_spelling(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    item_dir = journal_dir / "data/video/activeinferenceinstitute/Insights/Insights_001"
    item_dir.mkdir(parents=True)
    (item_dir / "metadata.json").write_text(
        json.dumps({"series": "Insights", "item": "Insights_001", "title": "T", "parts": []}),
        encoding="utf-8",
    )
    tr_dir = item_dir / "Translations"
    tr_dir.mkdir()
    (tr_dir / "V1.chi(translated).srt").write_text(SRT_BODY, encoding="utf-8")
    index_data = {
        "count": 1,
        "items": [
            {
                "path": "data/video/activeinferenceinstitute/Insights/Insights_001",
                "series": "Insights",
                "item": "Insights_001",
                "has_transcript": False,
            }
        ],
    }
    (journal_dir / "INDEX.json").write_text(json.dumps(index_data), encoding="utf-8")

    out_dir = tmp_path / "site_out"
    build_site(journal_dir=journal_dir, output_dir=out_dir)

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"][0]["languages"] == ["chi"]


M4_BASE_URL = "https://activeinferenceinstitute.github.io/ActiveInferenceJournal/"


def _ld_json_blocks(html_doc: str) -> list[dict]:
    """Extract every ``application/ld+json`` payload from a baked page."""
    return [
        json.loads(m)
        for m in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', html_doc, re.DOTALL
        )
    ]


def _m4_journal(tmp_path: Path) -> Path:
    """Synthetic 2-item journal; spaces in the series name exercise URL encoding."""
    journal_dir = tmp_path / "journal"
    series = "Applied Active Inference Symposium"
    metas = [
        {
            "series": series,
            "item": "2021 Talk One",
            "title": "First Talk",
            "guests": ["Karl J Friston"],
            "paper_title": "Transcript of: First Talk",
            "parts": [
                {
                    "video_id": "vid0001",
                    "url": "https://www.youtube.com/watch?v=vid0001",
                    "title": "Part 1",
                    "upload_date": "20210621",
                    "duration": 300.0,
                    "chapters": [
                        {"start": 0, "title": "Welcome"},
                        {"start": 120, "title": "Introduction"},
                    ],
                }
            ],
        },
        {
            "series": series,
            "item": "2022 Talk Two",
            "title": "Second Talk",
            "parts": [{"video_id": "vid0002", "title": "Only part"}],
        },
    ]
    for meta in metas:
        item_dir = journal_dir / "data/video/activeinferenceinstitute" / series / meta["item"]
        item_dir.mkdir(parents=True)
        (item_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    transcript = (
        journal_dir
        / "data/video/activeinferenceinstitute"
        / series
        / "2021 Talk One"
        / "transcript.txt"
    )
    transcript.write_text("hello and welcome\n\nsecond paragraph\n", encoding="utf-8")
    index_data = {
        "items": [
            {
                "path": f"data/video/activeinferenceinstitute/{series}/{m['item']}",
                "series": series,
                "item": m["item"],
                "has_transcript": i == 0,
            }
            for i, m in enumerate(metas)
        ]
    }
    (journal_dir / "INDEX.json").write_text(json.dumps(index_data), encoding="utf-8")
    return journal_dir


def test_build_site_static_pages_emits_per_item_bundle(tmp_path: Path) -> None:
    journal_dir = _m4_journal(tmp_path)
    out_dir = tmp_path / "site_out"

    res = build_site(journal_dir=journal_dir, output_dir=out_dir, static_pages=True)

    assert res["items_processed"] == 2
    assert res["pages_written"] == 2
    enc_series = "Applied%20Active%20Inference%20Symposium"
    page_a = (
        out_dir / "item" / "Applied Active Inference Symposium" / "2021 Talk One" / "index.html"
    )
    page_b = (
        out_dir / "item" / "Applied Active Inference Symposium" / "2022 Talk Two" / "index.html"
    )
    assert page_a.exists() and page_b.exists()
    html_a = page_a.read_text(encoding="utf-8")

    canonical = f"{M4_BASE_URL}item/{enc_series}/2021%20Talk%20One/"
    assert f'<link rel="canonical" href="{canonical}">' in html_a
    # Server-rendered core metadata — no JS required.
    assert "<h1>First Talk</h1>" in html_a
    assert "Guests: Karl J Friston" in html_a
    assert "Date: 2021-06-21" in html_a
    assert "<p>hello and welcome</p>" in html_a
    assert "<p>second paragraph</p>" in html_a
    # YouTube-nocookie embed per part.
    assert 'src="https://www.youtube-nocookie.com/embed/vid0001"' in html_a
    # Navigation: next sibling in series (percent-encoded) + SPA player link.
    assert f'href="../../{enc_series}/2022%20Talk%20Two/"' in html_a
    assert (
        f'href="{M4_BASE_URL}#/item/'
        'Applied%20Active%20Inference%20Symposium%2F2021%20Talk%20One"' in html_a
    )

    robots = (out_dir / "robots.txt").read_text(encoding="utf-8")
    assert robots == f"User-agent: *\nAllow: /\nSitemap: {M4_BASE_URL}sitemap.xml\n"

    sitemap = (out_dir / "sitemap.xml").read_text(encoding="utf-8")
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in sitemap
    assert f"<loc>{M4_BASE_URL}</loc>" in sitemap  # root entry first
    assert sitemap.count("<url>") == 3  # root + one per item
    assert "<changefreq>" not in sitemap and "<priority>" not in sitemap
    assert "index.html" not in sitemap  # canonicals never carry index.html
    rich_loc = f"<loc>{M4_BASE_URL}item/{enc_series}/2021%20Talk%20One/</loc>"
    bare_loc = f"<loc>{M4_BASE_URL}item/{enc_series}/2022%20Talk%20Two/</loc>"
    assert rich_loc in sitemap and bare_loc in sitemap
    assert "<lastmod>2021-06-21</lastmod>" in sitemap
    # lastmod is strictly parts[].upload_date-derived: the dateless item gets none.
    bare_block = sitemap.split(bare_loc)[1].split("</url>")[0]
    assert "<lastmod>" not in bare_block


def test_item_page_jsonld_video_object_and_dataset(tmp_path: Path) -> None:
    journal_dir = _m4_journal(tmp_path)
    out_dir = tmp_path / "site_out"
    build_site(journal_dir=journal_dir, output_dir=out_dir, static_pages=True)

    page = out_dir / "item" / "Applied Active Inference Symposium" / "2021 Talk One" / "index.html"
    blocks = _ld_json_blocks(page.read_text(encoding="utf-8"))
    datasets = [b for b in blocks if b["@type"] == "Dataset"]
    videos = [b for b in blocks if b["@type"] == "VideoObject"]
    assert len(datasets) == 1
    assert len(videos) == 1  # one VideoObject per part

    ds = datasets[0]
    assert ds["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert ds["citation"] == "https://doi.org/10.5281/zenodo.7299755"
    assert ds["isPartOf"]["name"] == "Active Inference Journal"

    vo = videos[0]
    assert vo["embedUrl"] == "https://www.youtube-nocookie.com/embed/vid0001"
    assert vo["thumbnailUrl"] == ["https://i.ytimg.com/vi/vid0001/hqdefault.jpg"]
    assert vo["inLanguage"] == "en"
    assert vo["uploadDate"] == "2021-06-21"  # ISO 8601 from parts[].upload_date
    assert vo["description"] == "Transcript of: First Talk"
    clip = vo["hasPart"][0]
    assert clip["@type"] == "Clip"
    assert clip["startOffsetTime"] == 0
    assert clip["url"] == "https://www.youtube.com/watch?v=vid0001&t=0"


def test_item_page_languages_cover_both_dir_spellings(tmp_path: Path) -> None:
    journal_dir = _m4_journal(tmp_path)
    tr_dir = (
        journal_dir
        / "data/video/activeinferenceinstitute"
        / "Applied Active Inference Symposium"
        / "2021 Talk One"
        / "Translations"
    )
    tr_dir.mkdir()
    (tr_dir / "V.chi(translated).srt").write_text(SRT_BODY, encoding="utf-8")
    (tr_dir / "V.es.srt").write_text(SRT_BODY, encoding="utf-8")

    out_dir = tmp_path / "site_out"
    build_site(journal_dir=journal_dir, output_dir=out_dir, static_pages=True)

    page = out_dir / "item" / "Applied Active Inference Symposium" / "2021 Talk One" / "index.html"
    html_doc = page.read_text(encoding="utf-8")
    # Post-I4 discovery (capital-T dir) + M2 normalization: chi → zh-Hans.
    assert ">zh-Hans</a>" in html_doc
    assert ">es</a>" in html_doc
    assert "chi(translated)" not in html_doc
    # Languages link to the interactive SPA view, never to fabricated files.
    spa_link = f"{M4_BASE_URL}#/item/Applied%20Active%20Inference%20Symposium%2F2021%20Talk%20One"
    assert f'href="{spa_link}"' in html_doc
