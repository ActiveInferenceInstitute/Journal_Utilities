"""Tests for plain-text transcript to pseudo-timed segment conversion.

Uses real files on disk (no mocks): synthetic transcripts written to tmp_path
plus the real lMROkmtaUWo.txt transcript when present in the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from txt_to_segments import parse_txt_to_segments  # noqa: E402


def _write_txt(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "transcript.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_known_text_produces_expected_count_and_durations(tmp_path: Path) -> None:
    # 200 words at 100 wpm -> 0.6 s/word -> 80-word chunks of 48 s each.
    words = ["word"] * 200
    path = _write_txt(tmp_path, "\n".join(words) + "\n")
    segments = parse_txt_to_segments(path, wpm=100)

    assert len(segments) == 3  # 200 // 80 -> chunks of 80, 80, 40
    assert [len(seg["text"].split()) for seg in segments] == [80, 80, 40]
    assert [seg["duration"] for seg in segments] == [48.0, 48.0, 24.0]
    assert segments[0]["start"] == 0.0
    assert segments[1]["start"] == 48.0
    assert segments[2]["start"] == 96.0
    for seg in segments:
        assert set(seg) == {"text", "start", "duration"}


def test_starts_are_monotonic_on_real_transcript() -> None:
    real = REPO_ROOT / "data/output/transcripts/lMROkmtaUWo.txt"
    if not real.exists():
        pytest.skip("real transcript fixture not present")
    segments = parse_txt_to_segments(real)
    assert len(segments) > 10
    starts = [float(seg["start"]) for seg in segments]
    assert starts[0] == 0.0
    assert all(b > a for a, b in zip(starts, starts[1:], strict=False))


def test_total_duration_matches_words_over_wpm(tmp_path: Path) -> None:
    words = ["alpha"] * 1600  # exactly 20 chunks of 80 words
    path = _write_txt(tmp_path, " ".join(words))
    wpm = 150
    segments = parse_txt_to_segments(path, wpm=wpm)

    total = float(segments[-1]["start"]) + float(segments[-1]["duration"])
    expected = len(words) / wpm * 60.0
    assert abs(total - expected) <= expected * 0.01  # within 1% tolerance


def test_whitespace_is_normalized(tmp_path: Path) -> None:
    path = _write_txt(tmp_path, "hello\n\n   world\t\tagain\n")
    segments = parse_txt_to_segments(path)
    assert len(segments) == 1
    assert segments[0]["text"] == "hello world again"


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    path = _write_txt(tmp_path, "")
    assert parse_txt_to_segments(path) == []


def test_whitespace_only_file_returns_empty_list(tmp_path: Path) -> None:
    path = _write_txt(tmp_path, " \n\t \n ")
    assert parse_txt_to_segments(path) == []


def test_cli_writes_output_json(tmp_path: Path) -> None:
    import json
    import subprocess

    src = _write_txt(tmp_path, " ".join(["tok"] * 160))
    out = tmp_path / "segments.json"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/txt_to_segments.py"), str(src), str(out), "--wpm", "120"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    segments = json.loads(out.read_text(encoding="utf-8"))
    assert len(segments) == 2
    assert segments[0]["duration"] == 40.0
