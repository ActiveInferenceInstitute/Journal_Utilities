"""Tests for static site builder (GitHub Pages generation)."""

import json
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
        "parts": [{"video_id": "test_vid_123", "title": "Part 1", "speakers": {"SPEAKER_00": "Daniel"}}],
    }
    (item_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (item_dir / "transcript.txt").write_text("Hello world transcript", encoding="utf-8")

    # Add translations
    tr_dir = item_dir / "translations"
    tr_dir.mkdir()
    (tr_dir / "LiveStream_001.es.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\nHola mundo\n", encoding="utf-8")

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
