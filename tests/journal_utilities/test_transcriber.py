"""Tests for the local Whisper transcriber module."""

from pathlib import Path

from journal_utilities.transcribe.transcriber import (
    TranscriptionStatus,
    find_missing_transcripts,
    transcribe_audio,
)


class TestFindMissingTranscripts:
    """Tests for find_missing_transcripts."""

    def test_all_missing(self, tmp_path: Path) -> None:
        """When no transcripts exist, all audio files are missing."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        # Create dummy audio files
        (audio_dir / "abc123.mp3").write_text("fake audio")
        (audio_dir / "def456.mp3").write_text("fake audio")

        missing = find_missing_transcripts(audio_dir, transcript_dir)
        assert len(missing) == 2
        assert {p.stem for p in missing} == {"abc123", "def456"}

    def test_some_existing(self, tmp_path: Path) -> None:
        """When some transcripts exist, only missing ones are returned."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        (audio_dir / "abc123.mp3").write_text("fake audio")
        (audio_dir / "def456.mp3").write_text("fake audio")
        (audio_dir / "ghi789.mp3").write_text("fake audio")

        # One transcript exists
        (transcript_dir / "def456.txt").write_text("some transcript content")

        missing = find_missing_transcripts(audio_dir, transcript_dir)
        assert len(missing) == 2
        stems = {p.stem for p in missing}
        assert "def456" not in stems
        assert "abc123" in stems
        assert "ghi789" in stems

    def test_none_missing(self, tmp_path: Path) -> None:
        """When all transcripts exist, returns empty."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        (audio_dir / "abc123.mp3").write_text("fake audio")
        (transcript_dir / "abc123.txt").write_text("some transcript")

        missing = find_missing_transcripts(audio_dir, transcript_dir)
        assert len(missing) == 0

    def test_empty_transcript_counted_as_missing(self, tmp_path: Path) -> None:
        """Empty transcript files (0 bytes) should be treated as missing."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        (audio_dir / "abc123.mp3").write_text("fake audio")
        (transcript_dir / "abc123.txt").write_text("")  # empty

        missing = find_missing_transcripts(audio_dir, transcript_dir)
        assert len(missing) == 1

    def test_nonexistent_audio_dir(self, tmp_path: Path) -> None:
        """When audio dir doesn't exist, returns empty list."""
        missing = find_missing_transcripts(tmp_path / "nonexistent", tmp_path / "transcripts")
        assert len(missing) == 0

    def test_ignores_non_audio_files(self, tmp_path: Path) -> None:
        """Non-audio files in audio_dir should be ignored."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        (audio_dir / "abc123.mp3").write_text("fake audio")
        (audio_dir / "readme.txt").write_text("not audio")
        (audio_dir / "data.json").write_text("{}")

        missing = find_missing_transcripts(audio_dir, transcript_dir)
        assert len(missing) == 1
        assert missing[0].stem == "abc123"

    def test_multiple_extensions(self, tmp_path: Path) -> None:
        """Handles wav and m4a extensions."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        (audio_dir / "a.mp3").write_text("fake")
        (audio_dir / "b.wav").write_text("fake")
        (audio_dir / "c.m4a").write_text("fake")

        missing = find_missing_transcripts(audio_dir, transcript_dir)
        assert len(missing) == 3


class TestTranscribeAudio:
    """Tests for transcribe_audio."""

    def test_skip_existing(self, tmp_path: Path) -> None:
        """Should skip when transcript already exists and skip_existing=True."""
        output_dir = tmp_path / "transcripts"
        output_dir.mkdir()
        audio_file = tmp_path / "test123.mp3"
        audio_file.write_text("fake audio")
        (output_dir / "test123.txt").write_text("existing transcript")

        result = transcribe_audio(audio_file, output_dir, skip_existing=True)
        assert result.status == TranscriptionStatus.SKIPPED
        assert result.video_id == "test123"

    def test_no_skip_when_disabled(self, tmp_path: Path) -> None:
        """When skip_existing=False, doesn't skip (may fail if mlx-whisper can't process)."""
        output_dir = tmp_path / "transcripts"
        output_dir.mkdir()
        audio_file = tmp_path / "test123.mp3"
        audio_file.write_text("fake audio")
        (output_dir / "test123.txt").write_text("existing transcript")

        # This will attempt transcription (and likely fail on fake audio),
        # but it proves it doesn't skip
        result = transcribe_audio(audio_file, output_dir, skip_existing=False)
        assert result.status != TranscriptionStatus.SKIPPED


class TestTranscribeMissing:
    """Tests for transcribe_missing batch function."""

    def test_batch_execution(self, tmp_path: Path) -> None:
        """Test that batch function orchestrates transcription correctly."""
        from unittest.mock import patch

        from journal_utilities.transcribe.transcriber import (
            TranscriptionResult,
            transcribe_missing,
        )

        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        transcript_dir = tmp_path / "transcripts"
        transcript_dir.mkdir()

        # Create 2 dummy audio files
        (audio_dir / "1.mp3").write_text("fake")
        (audio_dir / "2.mp3").write_text("fake")

        # Mock the individual transcribe_audio function (canonical module path)
        with patch("journal_utilities.transcribe.transcriber.transcribe_audio") as mock_transcribe:
            # Configure mock to return success
            mock_transcribe.return_value = TranscriptionResult(
                video_id="id", status=TranscriptionStatus.SUCCESS, duration_seconds=1.0
            )

            summary = transcribe_missing(audio_dir, transcript_dir)

            assert summary.total == 2
            assert summary.success == 2
            assert mock_transcribe.call_count == 2
