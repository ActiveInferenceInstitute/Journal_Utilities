"""Unit tests for journal SRT caption derivation (M5).

Pure formatting tests — no API, no network. The journal transcript.json
format (whisperx blocks: video_id + segments with start/end/text/speaker) is
exercised through tmp_path fixtures.
"""

from pathlib import Path

from journal_utilities.youtube.captions import (
    MAX_CUE_LINES,
    MAX_LINE_CHARS,
    build_cues,
    clean_text,
    derive_srt_for_video,
    humanize_speaker,
    is_speaker_change_line,
    load_blocks,
    segments_for_video,
    segments_to_srt,
    speaker_mapping,
    srt_timestamp,
    wrap_lines,
)

# --------------------------------------------------------------------- basics


def test_clean_text_collapses_whitespace_and_bom() -> None:
    assert clean_text("\ufeff  Excellent.\n\nAnd ") == "Excellent. And"
    assert clean_text("   ") == ""


def test_humanize_speaker_strips_pipeline_label() -> None:
    assert humanize_speaker("SPEAKER_00") == "Speaker 0"
    assert humanize_speaker("SPEAKER_12") == "Speaker 12"
    assert humanize_speaker("Karl Friston") == "Karl Friston"


def test_wrap_lines_respects_42_char_budget() -> None:
    text = (
        "So welcome everybody to the first episode of Active Inference Insights, "
        "brought to you by the Active Inference Institute."
    )
    lines = wrap_lines(text)
    assert lines
    assert all(len(line) <= MAX_LINE_CHARS for line in lines)
    assert " ".join(lines) == clean_text(text)


def test_wrap_lines_hard_splits_oversized_word() -> None:
    long_word = "x" * (MAX_LINE_CHARS + 10)
    lines = wrap_lines(long_word)
    assert all(len(line) <= MAX_LINE_CHARS for line in lines)
    assert "".join(lines) == long_word


def test_is_speaker_change_line() -> None:
    assert is_speaker_change_line("Karl Friston: Hello.")
    assert is_speaker_change_line("Speaker 0: ok")
    assert not is_speaker_change_line("plain text")
    assert not is_speaker_change_line("")


# ----------------------------------------------------------------- cue builds


def _segments(*texts: str, start: float = 0.0, duration: float = 2.0) -> list[dict]:
    return [
        {"start": start + i * duration, "end": start + (i + 1) * duration, "text": t}
        for i, t in enumerate(texts)
    ]


def test_build_cues_two_line_wrapping_never_exceeds_budget() -> None:
    segs = _segments(
        "Okay so welcome everybody to the first episode of Active Inference Insights "
        "brought to you by the Institute, and today I have the privilege."
    )
    cues = build_cues(segs)
    assert cues
    for cue in cues:
        assert len(cue["lines"]) <= MAX_CUE_LINES
        assert all(len(line) <= MAX_LINE_CHARS for line in cue["lines"])
    # Reassembled body preserves the full text order.
    joined = " ".join(" ".join(c["lines"]) for c in cues)
    assert "privilege." in joined


def test_build_cues_proportional_times_are_monotonic() -> None:
    segs = _segments("one two three four five six seven eight nine ten eleven twelve thirteen")
    cues = build_cues(segs)
    starts = [c["start"] for c in cues]
    ends = [c["end"] for c in cues]
    assert starts == sorted(starts)
    assert ends == sorted(ends)
    assert cues[0]["start"] == segs[0]["start"]
    assert abs(cues[-1]["end"] - segs[0]["end"]) < 0.01


def test_speaker_change_label_rendered_once() -> None:
    segs = [
        {"start": 0.0, "end": 2.0, "text": "Good evening.", "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 4.0, "text": "Welcome back.", "speaker": "SPEAKER_00"},
        {"start": 4.0, "end": 6.0, "text": "Thanks for having me.", "speaker": "SPEAKER_01"},
    ]
    cues = build_cues(segs)
    labeled = [ln for c in cues for ln in c["lines"] if ln.endswith(": Good evening.")]
    assert labeled == ["Speaker 0: Good evening."]
    all_text = " ".join(ln for c in cues for ln in c["lines"])
    assert "Speaker 0:" not in all_text.replace("Speaker 0: Good evening.", "")
    assert "Speaker 1: Thanks for having me." in all_text


def test_segments_to_srt_structure() -> None:
    srt = segments_to_srt(_segments("Hello there.", "Second cue."))
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\n")
    assert "2\n00:00:02,000 --> 00:00:04,000\n" in srt
    assert srt.endswith("\n")
    assert "\r" not in srt  # LF line endings, no BOM


def test_srt_timestamp_formatting_and_carry() -> None:
    assert srt_timestamp(59.9996) == "00:01:00,000"  # ms rounding carries into s
    assert srt_timestamp(59.9994) == "00:00:59,999"
    assert srt_timestamp(-3.0) == "00:00:00,000"


# ------------------------------------------------------ speaker name mapping


def test_speaker_mapping_part_match_and_sess_fallback() -> None:
    meta = {
        "parts": [
            {"video_id": "abc123", "speakers": {"SPEAKER_00": "Daniel Friedman"}},
            {"video_id": "other", "speakers": {"SPEAKER_01": "Someone Else"}},
        ]
    }
    # sess-split transcript ids resolve against the base part id.
    assert speaker_mapping(meta, "abc123_sess2") == {"SPEAKER_00": "Daniel Friedman"}
    assert speaker_mapping(meta, "abc123") == {"SPEAKER_00": "Daniel Friedman"}
    merged = speaker_mapping(meta, "unknown-vid")
    assert merged == {"SPEAKER_00": "Daniel Friedman", "SPEAKER_01": "Someone Else"}


def test_speaker_mapping_empty_meta() -> None:
    assert speaker_mapping({}, "vid") == {}
    assert speaker_mapping(None, "vid") == {}  # type: ignore[arg-type]


# ------------------------------------------------------------- journal wiring


def _write_journal_item(tmp_path: Path, segments_by_video: dict[str, list[dict]]) -> Path:
    blocks = [{"video_id": vid, "segments": segs} for vid, segs in segments_by_video.items()]
    item = tmp_path / "Items" / "Series_001"
    item.mkdir(parents=True)
    (item / "transcript.json").write_text(
        '{"not":"blocks"}' if not blocks else __import__("json").dumps(blocks), encoding="utf-8"
    )
    (item / "metadata.json").write_text(
        __import__("json").dumps(
            {
                "item": "Series_001",
                "parts": [
                    {"video_id": vid, "speakers": {"SPEAKER_00": "Karl Friston"}}
                    for vid in blocks_vids(segments_by_video)
                ],
            }
        ),
        encoding="utf-8",
    )
    return item


def blocks_vids(segments_by_video: dict[str, list[dict]]) -> list[str]:
    return list(segments_by_video)


def test_derive_srt_for_video_uses_mapped_names(tmp_path: Path) -> None:
    item = tmp_path / "Item"
    item.mkdir()
    (item / "transcript.json").write_text(
        """
        [{"video_id": "vid1",
          "segments": [
            {"start": 0.0, "end": 2.0, "text": " Hello.", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "text": " Welcome.", "speaker": "SPEAKER_00"}
          ]},
         {"video_id": "vid2",
          "segments": [{"start": 0.0, "end": 1.0, "text": " Other part."}]}]
        """,
        encoding="utf-8",
    )
    (item / "metadata.json").write_text(
        '{"parts": [{"video_id": "vid1", "speakers": {"SPEAKER_00": "Karl Friston"}}]}',
        encoding="utf-8",
    )
    srt = derive_srt_for_video(item, "vid1")
    assert srt is not None
    assert "Karl Friston: Hello." in srt
    assert "SPEAKER_00" not in srt
    # Multi-part isolation: only the requested part's segments appear.
    assert "Other part" not in srt and "vid2" not in srt
    assert "00:00:02,000 --> 00:00:04,000" in srt


def test_derive_srt_humanizes_unmapped_speakers(tmp_path: Path) -> None:
    item = tmp_path / "Item"
    item.mkdir()
    (item / "transcript.json").write_text(
        '[{"video_id": "v", "segments": ['
        '{"start": 0.0, "end": 1.0, "text": " Hi.", "speaker": "SPEAKER_03"}]}]',
        encoding="utf-8",
    )
    srt = derive_srt_for_video(item, "v")
    assert srt is not None
    assert "Speaker 3: Hi." in srt


def test_derive_srt_returns_none_without_transcript(tmp_path: Path) -> None:
    item = tmp_path / "Empty"
    item.mkdir()
    assert derive_srt_for_video(item, "v") is None
    (item / "transcript.json").write_text('{"segments": []}', encoding="utf-8")
    assert derive_srt_for_video(item, "v") is None  # dict, not whisperx blocks


def test_derive_srt_sess_suffix_falls_back_to_base(tmp_path: Path) -> None:
    item = tmp_path / "Item"
    item.mkdir()
    (item / "transcript.json").write_text(
        '[{"video_id": "v", "segments": [{"start": 0.0, "end": 1.0, "text": " From base."}]}]',
        encoding="utf-8",
    )
    srt = derive_srt_for_video(item, "v_sess2")
    assert srt is not None
    assert "From base." in srt


def test_load_blocks_rejects_non_block_format(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text('{"segments": [1]}', encoding="utf-8")
    assert load_blocks(p) is None
    p.write_text("[{bad", encoding="utf-8")
    assert load_blocks(p) is None
    p.write_text("[]", encoding="utf-8")
    assert load_blocks(p) == []


def test_segments_for_video_unknown_id_is_empty() -> None:
    blocks = [{"video_id": "a", "segments": [{"start": 0.0, "end": 1.0, "text": "x"}]}]
    assert segments_for_video(blocks, "zzz") == []
    assert segments_for_video(None, "a") == []
