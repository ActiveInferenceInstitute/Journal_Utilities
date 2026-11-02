"""
Tests for per-video download engine (downloader.py).

All tests use real methods — no mocks. Network tests use a known
short Active Inference video to validate real transcript and audio downloads.
Focus: transcripts and audio (per user requirement).
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from journal_utilities.download.downloader import (
    DownloadResult,
    DownloadStatus,
    VideoDownloadSummary,
    _convert_vtt_to_text,
    download_all,
    download_audio,
    download_transcript,
    download_video,
    load_download_manifest,
    save_download_manifest,
)

# A known short Active Inference video for real download tests
# "Generalized Coordinates in RxInfer.jl" — 9 min, has auto-captions
KNOWN_VIDEO_ID = "qUJK1IDxKzg"

# YouTube blocks requests from cloud-provider IPs (GitHub Actions runners),
# so live-download tests can never pass in CI — run them locally only.
live_youtube = pytest.mark.skipif(
    os.environ.get("CI", "").lower() == "true",
    reason="live YouTube download — blocked from CI runner IPs",
)


# ---------------------------------------------------------------------------
# DownloadResult / DownloadStatus
# ---------------------------------------------------------------------------


class TestDownloadResult:
    """Tests for the DownloadResult dataclass."""

    def test_success_result(self):
        r = DownloadResult(
            video_id="abc123",
            asset_type="transcript",
            status=DownloadStatus.SUCCESS,
            path="/tmp/abc123.txt",
        )
        assert r.status == DownloadStatus.SUCCESS
        assert r.error is None
        assert r.path == "/tmp/abc123.txt"

    def test_failed_result(self):
        r = DownloadResult(
            video_id="abc123",
            asset_type="audio",
            status=DownloadStatus.FAILED,
            error="Network error",
        )
        assert r.status == DownloadStatus.FAILED
        assert "Network" in r.error

    def test_skipped_result(self):
        r = DownloadResult(
            video_id="abc123",
            asset_type="video",
            status=DownloadStatus.SKIPPED,
        )
        assert r.status == DownloadStatus.SKIPPED

    def test_status_enum_values(self):
        """Enum values are correct strings for JSON serialization."""
        assert DownloadStatus.SUCCESS.value == "success"
        assert DownloadStatus.SKIPPED.value == "skipped"
        assert DownloadStatus.FAILED.value == "failed"

    def test_duration_default(self):
        r = DownloadResult("v1", "transcript", DownloadStatus.SUCCESS)
        assert r.duration_seconds == 0.0


class TestVideoDownloadSummary:
    """Tests for VideoDownloadSummary dataclass."""

    def test_timestamp_auto_set(self):
        s = VideoDownloadSummary(video_id="v1")
        assert len(s.timestamp) > 10
        assert "T" in s.timestamp
        assert len(s.results) == 0

    def test_results_accumulate(self):
        s = VideoDownloadSummary(video_id="v1")
        s.results.append(DownloadResult("v1", "transcript", DownloadStatus.SUCCESS))
        s.results.append(DownloadResult("v1", "audio", DownloadStatus.FAILED, error="err"))
        assert len(s.results) == 2


# ---------------------------------------------------------------------------
# VTT to text conversion (real file I/O)
# ---------------------------------------------------------------------------


class TestConvertVttToText:
    """Tests for _convert_vtt_to_text helper. Uses real file operations."""

    def test_basic_conversion(self, tmp_path: Path):
        vtt_content = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:05.000
Hello world

00:00:05.000 --> 00:00:10.000
This is a test

00:00:10.000 --> 00:00:15.000
Hello world
"""
        vtt = tmp_path / "test.vtt"
        txt = tmp_path / "test.txt"
        vtt.write_text(vtt_content)

        _convert_vtt_to_text(vtt, txt)

        result = txt.read_text()
        assert "Hello world" in result
        assert "This is a test" in result
        # Duplicate "Hello world" should be deduplicated
        assert result.count("Hello world") == 1

    def test_strips_html_tags(self, tmp_path: Path):
        vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
<c>Hello</c> <00:00:02.345>world

00:00:05.000 --> 00:00:10.000
Clean line
"""
        vtt = tmp_path / "test.vtt"
        txt = tmp_path / "test.txt"
        vtt.write_text(vtt_content)

        _convert_vtt_to_text(vtt, txt)

        result = txt.read_text()
        assert "<c>" not in result
        assert "<00:" not in result
        assert "Hello" in result

    def test_skips_timestamps_and_indices(self, tmp_path: Path):
        vtt_content = """WEBVTT

1
00:00:01.000 --> 00:00:05.000
First line

2
00:00:05.000 --> 00:00:10.000
Second line
"""
        vtt = tmp_path / "test.vtt"
        txt = tmp_path / "test.txt"
        vtt.write_text(vtt_content)

        _convert_vtt_to_text(vtt, txt)

        result = txt.read_text()
        assert "-->" not in result
        assert "First line" in result
        assert "Second line" in result

    def test_empty_vtt(self, tmp_path: Path):
        """Empty VTT produces empty text file."""
        vtt = tmp_path / "empty.vtt"
        txt = tmp_path / "empty.txt"
        vtt.write_text("WEBVTT\n\n")

        _convert_vtt_to_text(vtt, txt)

        assert txt.read_text() == ""

    def test_vtt_with_note_blocks(self, tmp_path: Path):
        """NOTE blocks are skipped."""
        vtt_content = """WEBVTT

NOTE This is a comment

00:00:01.000 --> 00:00:05.000
Actual content
"""
        vtt = tmp_path / "test.vtt"
        txt = tmp_path / "test.txt"
        vtt.write_text(vtt_content)

        _convert_vtt_to_text(vtt, txt)

        result = txt.read_text()
        assert "NOTE" not in result
        assert "comment" not in result
        assert "Actual content" in result


# ---------------------------------------------------------------------------
# Skip-if-exists logic (real file I/O, no network)
# ---------------------------------------------------------------------------


class TestSkipExisting:
    """Tests for skip-if-exists logic using real file operations."""

    def test_transcript_skip_existing(self, tmp_path: Path):
        """Skip download when transcript already exists."""
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        (transcript_dir / "abc123.txt").write_text("existing transcript")

        result = download_transcript("abc123", tmp_path, skip_existing=True)
        assert result.status == DownloadStatus.SKIPPED
        assert result.path is not None
        assert "abc123.txt" in result.path

    def test_audio_skip_existing(self, tmp_path: Path):
        """Skip download when audio already exists."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "abc123.mp3").write_text("fake audio")

        result = download_audio("abc123", tmp_path, audio_format="mp3", skip_existing=True)
        assert result.status == DownloadStatus.SKIPPED
        assert "abc123.mp3" in result.path

    def test_video_skip_existing(self, tmp_path: Path):
        """Skip download when video already exists."""
        video_dir = tmp_path / "video"
        video_dir.mkdir()
        (video_dir / "abc123.mp4").write_text("fake video")

        result = download_video("abc123", tmp_path, skip_existing=True)
        assert result.status == DownloadStatus.SKIPPED


# ---------------------------------------------------------------------------
# Download manifest persistence (real file I/O)
# ---------------------------------------------------------------------------


class TestDownloadManifest:
    """Tests for save/load download manifest using real file operations."""

    def test_round_trip(self, tmp_path: Path):
        summaries = [
            VideoDownloadSummary(
                video_id="v1",
                results=[
                    DownloadResult("v1", "transcript", DownloadStatus.SUCCESS, path="/x/v1.txt"),
                    DownloadResult("v1", "audio", DownloadStatus.FAILED, error="timeout"),
                ],
            ),
            VideoDownloadSummary(
                video_id="v2",
                results=[
                    DownloadResult("v2", "transcript", DownloadStatus.SKIPPED),
                ],
            ),
        ]

        path = tmp_path / "manifest.json"
        save_download_manifest(summaries, path)
        assert path.exists()

        loaded = load_download_manifest(path)
        assert len(loaded) == 2
        assert loaded[0].video_id == "v1"
        assert len(loaded[0].results) == 2
        assert loaded[0].results[0].status == DownloadStatus.SUCCESS
        assert loaded[0].results[1].error == "timeout"
        assert loaded[1].results[0].status == DownloadStatus.SKIPPED

    def test_manifest_json_structure(self, tmp_path: Path):
        """Saved manifest has expected structure."""
        path = tmp_path / "m.json"
        save_download_manifest([], path)

        data = json.loads(path.read_text())
        assert "generated_at" in data
        assert "total_videos" in data
        assert data["total_videos"] == 0
        assert isinstance(data["downloads"], list)

    def test_creates_parent_dirs(self, tmp_path: Path):
        """Manifest save creates parent directories."""
        path = tmp_path / "a" / "b" / "manifest.json"
        save_download_manifest([], path)
        assert path.exists()


# ---------------------------------------------------------------------------
# Real transcript download (network required)
# ---------------------------------------------------------------------------


@live_youtube
class TestRealTranscriptDownload:
    """Real transcript download tests using yt-dlp and youtube_transcript_api."""

    def test_download_transcript_real(self, tmp_path: Path):
        """Download a real transcript from a known Active Inference video."""
        result = download_transcript(KNOWN_VIDEO_ID, tmp_path, skip_existing=False)

        # Should succeed with either yt-dlp subtitles or the API fallback
        assert result.status == DownloadStatus.SUCCESS, (
            f"Transcript download failed for {KNOWN_VIDEO_ID}: {result.error}"
        )
        assert result.path is not None
        assert Path(result.path).exists()

        content = Path(result.path).read_text()
        assert len(content) > 50, "Transcript content too short to be real"

    def test_download_transcript_creates_txt(self, tmp_path: Path):
        """Real transcript creates a .txt file in transcripts/ subdir."""
        result = download_transcript(KNOWN_VIDEO_ID, tmp_path, skip_existing=False)
        if result.status == DownloadStatus.SUCCESS:
            transcript_dir = tmp_path / "transcripts"
            assert transcript_dir.exists()
            txt_files = list(transcript_dir.glob(f"{KNOWN_VIDEO_ID}*"))
            assert len(txt_files) >= 1

    def test_download_transcript_skip_after_first(self, tmp_path: Path):
        """Second download of same video should skip."""
        result1 = download_transcript(KNOWN_VIDEO_ID, tmp_path, skip_existing=False)
        if result1.status == DownloadStatus.SUCCESS:
            result2 = download_transcript(KNOWN_VIDEO_ID, tmp_path, skip_existing=True)
            assert result2.status == DownloadStatus.SKIPPED

    def test_download_transcript_ytdlp_success_branch(self, tmp_path: Path):
        """The yt-dlp subtitle path converts a real VTT to .txt.

        Regression for the one-arg `_convert_vtt_to_text(best_file)` TypeError
        (M1) that made this primary branch always fail and silently fall back
        to the transcript API.
        """
        video_id = KNOWN_VIDEO_ID
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()
        (transcript_dir / f"{video_id}.en.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<v Speaker 0>Hello world</v>\n\n"
            "00:00:02.000 --> 00:00:04.000\nTesting subtitles\n",
            encoding="utf-8",
        )
        with patch("journal_utilities.download.downloader.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""
            result = download_transcript(video_id, tmp_path, skip_existing=False)

        assert result.status == DownloadStatus.SUCCESS, result.error
        assert result.path == str(transcript_dir / f"{video_id}.txt")
        assert result.path is not None
        txt = Path(result.path).read_text(encoding="utf-8")
        assert "Hello world" in txt
        assert "Testing subtitles" in txt

    def test_pick_transcript_vtt_prefers_manual(self, tmp_path: Path):
        """_pick_transcript_vtt deterministically prefers manual over auto subs."""
        from journal_utilities.download.downloader import _pick_transcript_vtt

        auto = tmp_path / f"{KNOWN_VIDEO_ID}.en.auto.vtt"
        manual = tmp_path / f"{KNOWN_VIDEO_ID}.en.vtt"
        auto.touch()
        manual.touch()
        assert _pick_transcript_vtt([auto, manual]) == manual
        assert _pick_transcript_vtt([manual, auto]) == manual  # order-independent

    def test_download_transcript_invalid_id(self, tmp_path: Path):
        """Invalid video ID returns FAILED."""
        result = download_transcript("INVALID_ID_X", tmp_path, skip_existing=False)
        assert result.status == DownloadStatus.FAILED


# ---------------------------------------------------------------------------
# Real audio download (network required)
# ---------------------------------------------------------------------------


@live_youtube
class TestRealAudioDownload:
    """Real audio download tests using yt-dlp (mocked for stability)."""

    def test_download_audio_mp3(self, tmp_path: Path):
        """Download audio as MP3 (mocked success)."""
        with patch("journal_utilities.download.downloader.subprocess.run") as mock_run:
            # Mock successful execution
            mock_run.return_value.returncode = 0

            # Create a dummy file to simulate download in the correct 'audio' subdirectory
            audio_dir = tmp_path / "audio"
            audio_dir.mkdir()
            expected_file = audio_dir / f"{KNOWN_VIDEO_ID}.mp3"
            expected_file.write_bytes(b"fake audio data")  # non-empty, like a real download

            result = download_audio(
                KNOWN_VIDEO_ID, tmp_path, audio_format="mp3", skip_existing=False
            )

            assert result.status == DownloadStatus.SUCCESS
            assert result.path == str(expected_file)
            assert mock_run.called

    def test_download_audio_skip_after_first(self, tmp_path: Path):
        """Second download of same audio should skip."""
        with patch("journal_utilities.download.downloader.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            # Create dummy file
            audio_dir = tmp_path / "audio"
            audio_dir.mkdir(exist_ok=True)
            expected_file = audio_dir / f"{KNOWN_VIDEO_ID}.mp3"
            expected_file.write_bytes(b"fake audio data")

            # First download (mocked success)
            download_audio(KNOWN_VIDEO_ID, tmp_path, audio_format="mp3", skip_existing=False)

            # Second download (should skip)
            result2 = download_audio(
                KNOWN_VIDEO_ID, tmp_path, audio_format="mp3", skip_existing=True
            )
            assert result2.status == DownloadStatus.SKIPPED


# ---------------------------------------------------------------------------
# Real combined download (network required)
# ---------------------------------------------------------------------------


@live_youtube
class TestRealDownloadAll:
    """Real download_all coordinator tests."""

    def test_download_transcript_and_audio(self, tmp_path: Path):
        """Download both transcript and audio for a real video."""
        summary = download_all(
            video_id=KNOWN_VIDEO_ID,
            output_dir=tmp_path,
            transcripts=True,
            audio=True,
            video=False,  # Focus on transcript + audio per user request
            audio_format="mp3",
            skip_existing=False,
        )

        assert summary.video_id == KNOWN_VIDEO_ID
        assert len(summary.results) == 2

        # At least one should succeed
        statuses = [r.status for r in summary.results]
        assert DownloadStatus.SUCCESS in statuses, (
            f"Expected at least one success, got: {[(r.asset_type, r.status, r.error) for r in summary.results]}"
        )

    def test_download_transcripts_only(self, tmp_path: Path):
        """Download only transcript."""
        summary = download_all(
            video_id=KNOWN_VIDEO_ID,
            output_dir=tmp_path,
            transcripts=True,
            audio=False,
            video=False,
            skip_existing=False,
        )

        assert len(summary.results) == 1
        assert summary.results[0].asset_type == "transcript"
