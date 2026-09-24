"""Unit tests for ChapterGenerator parsing and downsampling logic."""

import logging

from journal_utilities.youtube.chapter_generator import (
    calculate_optimal_chapter_count,
    downsample_transcript_segments,
    parse_llm_chapters_text,
    parse_timestamp_to_seconds,
)


def test_parse_timestamp_to_seconds():
    assert parse_timestamp_to_seconds("00:00") == 0.0
    assert parse_timestamp_to_seconds("02:15") == 135.0
    assert parse_timestamp_to_seconds("01:10:05") == 4205.0
    assert parse_timestamp_to_seconds("invalid") is None


def test_parse_llm_chapters_text_clean():
    sample_llm_output = """
    Here are the chapters:
    00:00 - Introduction and Welcoming
    04:30 Foundations of Active Inference
    18:45 Generative Models & Free Energy Principle
    01:05:20 Closing Q&A
    """
    chapters = parse_llm_chapters_text(sample_llm_output)
    assert len(chapters) == 4
    assert chapters[0].start == 0.0
    assert chapters[0].title == "Introduction and Welcoming"
    assert chapters[1].start == 270.0
    assert chapters[1].title == "Foundations of Active Inference"
    assert chapters[2].start == 1125.0
    assert chapters[3].start == 3920.0


def test_parse_llm_chapters_prepends_zero_if_missing():
    sample_llm_output = """
    05:00 Theoretical Setup
    15:30 Discussion
    """
    chapters = parse_llm_chapters_text(sample_llm_output)
    assert len(chapters) == 3
    assert chapters[0].start == 0.0
    assert chapters[0].title == "Introduction"
    assert chapters[1].start == 300.0


def test_downsample_transcript_segments():
    segments = [
        {"start": 0.0, "text": "Hello everyone."},
        {"start": 10.0, "text": "Welcome to the stream."},
        {"start": 65.0, "text": "Today we discuss Markov Blankets."},
        {"start": 130.0, "text": "Let us look at equations."},
    ]
    sampled = downsample_transcript_segments(segments, interval_seconds=60.0)
    assert "[00:00] Hello everyone." in sampled
    assert "Welcome to the stream." not in sampled  # Skipped within 60s
    assert "[01:05] Today we discuss Markov Blankets." in sampled
    assert "[02:10] Let us look at equations." in sampled


# ---------------------------------------------------------------------------
# Real-data contract tests (no mocks): chapter-count enforcement (10-30)
# ---------------------------------------------------------------------------


def _make_llm_chapter_lines(count: int) -> str:
    """Build a realistic LLM chapter list with `count` strictly increasing timestamps."""
    lines = []
    seconds_per_chapter = 60  # one minute apart -> HH:MM:SS-safe for large counts
    for i in range(count):
        total = i * seconds_per_chapter
        ts = f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
        # Titles are >= 25 chars so the short-title quality warning does not fire.
        lines.append(f"{ts} Chapter {i} Topic with a descriptive informative title")
    return "\n".join(lines)


def test_over_30_chapters_downsampled_capped_at_30_and_keeps_first():
    raw = _make_llm_chapter_lines(123)  # matches worst observed gemma3:4b output
    chapters = parse_llm_chapters_text(raw)
    assert len(chapters) <= 30
    assert len(chapters) >= 10
    # First (00:00) entry must always survive downsampling.
    assert chapters[0].start == 0.0
    # Chronological order preserved.
    starts = [c.start for c in chapters]
    assert starts == sorted(starts)


def test_downsample_warning_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="journal_utilities.youtube.chapter_generator"):
        parse_llm_chapters_text(_make_llm_chapter_lines(90))
    assert any("downsampling" in r.message.lower() or "90" in r.message for r in caplog.records)


def test_below_gate_minimum_kept_with_warning(caplog):
    raw = "\n".join(
        [
            "00:00 Introduction",
            "03:00 Topic One",
        ]
    )
    with caplog.at_level(logging.WARNING, logger="journal_utilities.youtube.chapter_generator"):
        chapters = parse_llm_chapters_text(raw)
    # Under-count sets are kept, not dropped (the gate judges them separately).
    assert len(chapters) == 2
    assert chapters[0].start == 0.0
    assert any(
        "chapters" in r.message and any(ch.isdigit() for ch in r.message) for r in caplog.records
    )


def test_at_gate_minimum_no_warning(caplog):
    raw = "\n".join(
        [
            "00:00 Introduction",
            "03:00 Topic One",
            "06:30 Topic Two",
        ]
    )
    with caplog.at_level(logging.WARNING, logger="journal_utilities.youtube.chapter_generator"):
        chapters = parse_llm_chapters_text(raw)
    assert len(chapters) == 3
    assert not caplog.records


def test_in_range_chapter_count_unchanged_no_warning(caplog):
    raw = _make_llm_chapter_lines(15)
    with caplog.at_level(logging.WARNING, logger="journal_utilities.youtube.chapter_generator"):
        chapters = parse_llm_chapters_text(raw)
    assert len(chapters) == 15
    assert not caplog.records


def test_calculate_optimal_chapter_count_respects_gate_floor():
    durations = [60.0, 300.0, 600.0, 1199.0, 1200.0, 2700.0, 5400.0, 7200.0, 14400.0, None]
    for d in durations:
        count = calculate_optimal_chapter_count(d)
        # Videos under 5 minutes legitimately get 3 chapters; everything else 10-30.
        expected_floor = 3 if (d is not None and d < 300.0) else 10
        assert expected_floor <= count <= 30, f"duration={d} produced out-of-contract count {count}"
