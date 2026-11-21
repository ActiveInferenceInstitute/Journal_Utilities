"""Unit tests for YouTube metadata and description formatter."""

import pytest

from journal_utilities.youtube.metadata_formatter import (
    ChapterEntry,
    assemble_video_description,
    build_journal_item_url,
    build_video_item_index,
    format_chapters_block,
    format_seconds_to_timestamp,
    resolve_video_journal_url,
    split_base_description,
)


def test_format_seconds_to_timestamp():
    assert format_seconds_to_timestamp(0) == "00:00"
    assert format_seconds_to_timestamp(65) == "01:05"
    assert format_seconds_to_timestamp(3665) == "01:01:05"


def test_format_chapters_block():
    chapters = [
        {"start": 120.0, "title": "Main Presentation"},
        {"start": 600.0, "title": "Q&A Session"},
    ]
    formatted = format_chapters_block(chapters)
    # Checks that 00:00 Introduction is prepended automatically
    assert "00:00 Introduction" in formatted
    assert "02:00 Main Presentation" in formatted
    assert "10:00 Q&A Session" in formatted


def test_resolve_video_journal_url():
    items = [
        {
            "path": "data/video/activeinferenceinstitute/DemoSeries/DemoSeries_001",
            "series": "DemoSeries",
            "item": "DemoSeries_001",
            "has_transcript": True,
            "parts": ["vid_with_transcript"],
        },
        {
            "path": "data/video/activeinferenceinstitute/DemoSeries/DemoSeries_002",
            "series": "DemoSeries",
            "item": "DemoSeries_002",
            "has_transcript": False,
            "parts": ["vid_without_transcript"],
        },
    ]
    index = build_video_item_index(items)
    expected = (
        "https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/tree/main"
        "/data/video/activeinferenceinstitute/DemoSeries/DemoSeries_001"
    )
    assert build_journal_item_url(items[0]["path"]) == expected
    assert resolve_video_journal_url("vid_with_transcript", index) == expected
    # has_transcript comes from INDEX, not local files.
    assert resolve_video_journal_url("vid_without_transcript", index) is None
    # Unmapped video IDs never produce a guessed URL.
    assert resolve_video_journal_url("vid_not_in_index", index) is None
    assert "vid_not_in_index" not in index


def test_assemble_video_description():
    chapters = [
        ChapterEntry(start=0.0, title="Intro"),
        ChapterEntry(start=180.0, title="Discussion"),
    ]
    items = [
        {
            "path": "data/video/activeinferenceinstitute/DemoSeries/DemoSeries_001",
            "series": "DemoSeries",
            "item": "DemoSeries_001",
            "has_transcript": True,
            "parts": ["test_vid_123"],
        }
    ]
    item_index = build_video_item_index(items)
    desc = assemble_video_description(
        base_description="A deep dive into Active Inference.",
        chapters=chapters,
        github_transcript_url=resolve_video_journal_url("test_vid_123", item_index),
        slides_url="https://slides.example.com",
    )
    assert "A deep dive into Active Inference." in desc
    assert "--- TIMESTAMPS & CHAPTERS ---" in desc
    assert "00:00 Intro" in desc
    assert "03:00 Discussion" in desc
    assert "--- RESOURCES & TRANSCRIPT ---" in desc
    assert (
        "https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/tree/main"
        "/data/video/activeinferenceinstitute/DemoSeries/DemoSeries_001" in desc
    )
    assert "https://slides.example.com" in desc
    assert "Active Inference Institute information:" in desc
    assert "https://video.activeinference.institute/" in desc
    assert "Donate: https://donate.activeinference.institute/" in desc
    assert "YouTube: https://www.youtube.com/@ActiveInference\n" in desc
    assert (
        "Transcripts, captions & translations: "
        "https://activeinferenceinstitute.github.io/ActiveInferenceJournal/"
    ) in desc
    # The dead blob URL must never be emitted (Y1/E1/I1 regression lock).
    assert "blob/main/transcripts" not in desc


def test_assemble_video_description_has_no_implicit_transcript_fallback():
    """Regression: an unmapped/unresolved video emits no transcript link at all."""
    desc = assemble_video_description(
        base_description="Abstract text.",
        chapters=[ChapterEntry(start=0.0, title="Intro")],
    )
    assert "Full Transcript" not in desc
    assert "github.com/ActiveInferenceInstitute/ActiveInferenceJournal" not in desc


def test_canonical_journal_item_precedes_duplicate_alias_in_either_order():
    video_id = "example1234"
    canonical = {
        "path": "data/video/activeinferenceinstitute/Symposium 2026/session #3",
        "has_transcript": True,
        "parts": [video_id],
    }
    alias = {
        "path": "data/video/activeinferenceinstitute/Other/Session_003",
        "has_transcript": False,
        "parts": [video_id],
        "duplicate_of": "Symposium 2026/session #3",
    }
    for rows in ([canonical, alias], [alias, canonical]):
        projected = build_video_item_index(rows)
        assert projected[video_id] == canonical
        assert resolve_video_journal_url(video_id, projected).endswith(
            "Symposium%202026/session%20%233"
        )


def test_journal_entry_without_transcript_gets_a_distinct_label():
    url = build_journal_item_url("data/video/activeinferenceinstitute/Fundamentals/Session_028")
    description = assemble_video_description(journal_item_url=url)
    assert f"Active Inference Journal entry:\n{url}" in description
    assert "Full Transcript" not in description


def test_unsafe_journal_item_paths_do_not_produce_urls():
    for item_path in (
        "../INDEX.json",
        "/private/records",
        "data/./item",
        "data\\item",
        "in\nvalid",
    ):
        with pytest.raises(ValueError, match="relative repository path"):
            build_journal_item_url(item_path)
        item_index = build_video_item_index(
            [{"path": item_path, "has_transcript": True, "parts": ["example1234"]}]
        )
        assert resolve_video_journal_url("example1234", item_index) is None


def test_split_base_description_strips_legacy_timestamp_runs():
    """Regression: legacy embedded chapter lists must not duplicate on re-assembly."""
    base = (
        "Paper abstract text.\n"
        "\n"
        "------\n"
        "\n"
        "CHAPTERS\n"
        "00:00 Introduction\n"
        "00:02 Introduction\n"
        "00:34 Chapter 1\n"
        "\n"
        "Follow us:\n"
        "https://example.com"
    )
    paper_info, link_block = split_base_description(base)
    assert "00:00 Introduction" not in paper_info
    assert "Paper abstract text." in paper_info
    assert "Follow us:" in link_block

    chapters = [
        ChapterEntry(start=0.0, title="Introduction"),
        ChapterEntry(start=34.0, title="Chapter 1"),
    ]
    once = assemble_video_description(base_description=base, chapters=chapters)
    twice = assemble_video_description(base_description=once, chapters=chapters)
    assert once == twice  # idempotent
    assert once.count("00:00 Introduction") == 1
    assert once.count("--- TIMESTAMPS & CHAPTERS ---") == 1
    assert "Full Transcript" not in once
    assert "Active Inference Institute information:" in once
    # Short (<3 line) timestamp runs are preserved verbatim.
    short = "Intro text\n00:30 Note\n00:45 Another\n\nFollow us:\nhttps://example.com"
    pi, _ = split_base_description(short)
    assert "00:30 Note" in pi
