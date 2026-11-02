"""
Local audio transcription using mlx-whisper (Apple Silicon optimized).

Provides a fallback for videos where YouTube transcripts are unavailable
due to IP blocking or missing captions. Uses mlx-whisper for fast,
high-quality transcription on Apple Silicon hardware.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Default model: Whisper Large V3 Turbo via MLX Community
DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


class TranscriptionStatus(str, Enum):
    """Status of a transcription operation."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class TranscriptionResult:
    """Result of a single transcription operation."""

    video_id: str
    status: TranscriptionStatus
    path: str | None = None
    duration_seconds: float | None = None
    model: str | None = None
    error: str | None = None


@dataclass
class TranscriptionSummary:
    """Summary of a batch transcription run."""

    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[TranscriptionResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    model: str = DEFAULT_MODEL,
    language: str = "en",
    skip_existing: bool = True,
) -> TranscriptionResult:
    """
    Transcribe a single audio file using mlx-whisper.

    Args:
        audio_path: Path to the audio file (mp3, wav, m4a).
        output_dir: Directory to save the transcript .txt file.
        model: MLX Whisper model identifier.
        language: Language code for transcription.
        skip_existing: If True, skip if transcript already exists.

    Returns:
        TranscriptionResult with status and output path.
    """
    video_id = audio_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / f"{video_id}.txt"

    # Skip if already transcribed
    if skip_existing and txt_path.exists() and txt_path.stat().st_size > 0:
        logger.info("Transcript already exists for %s, skipping", video_id)
        return TranscriptionResult(
            video_id=video_id,
            status=TranscriptionStatus.SKIPPED,
            path=str(txt_path),
            model=model,
        )

    logger.info("Transcribing %s with model %s", video_id, model)
    start_time = time.time()

    try:
        import mlx_whisper  # noqa: E402 — lazy import to avoid hard dependency

        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=model,
            language=language,
            word_timestamps=False,
        )

        # Extract text from segments
        segments = result.get("segments", [])
        full_text = "\n".join(seg.get("text", "").strip() for seg in segments)

        if not full_text.strip():
            logger.warning("Empty transcription for %s", video_id)
            return TranscriptionResult(
                video_id=video_id,
                status=TranscriptionStatus.FAILED,
                error="Empty transcription result",
                model=model,
            )

        # Save transcript
        txt_path.write_text(full_text, encoding="utf-8")
        elapsed = time.time() - start_time

        logger.info(
            "Transcribed %s in %.1fs (%d chars)",
            video_id,
            elapsed,
            len(full_text),
        )
        return TranscriptionResult(
            video_id=video_id,
            status=TranscriptionStatus.SUCCESS,
            path=str(txt_path),
            duration_seconds=elapsed,
            model=model,
        )

    except ImportError:
        logger.error("mlx-whisper not installed. Install with: uv pip install mlx-whisper")
        return TranscriptionResult(
            video_id=video_id,
            status=TranscriptionStatus.FAILED,
            error="mlx-whisper not installed",
            model=model,
        )
    except Exception as exc:
        elapsed = time.time() - start_time
        logger.error("Transcription failed for %s: %s", video_id, exc)
        return TranscriptionResult(
            video_id=video_id,
            status=TranscriptionStatus.FAILED,
            error=str(exc),
            duration_seconds=elapsed,
            model=model,
        )


def find_missing_transcripts(
    audio_dir: Path,
    transcript_dir: Path,
    audio_extensions: list[str] | None = None,
) -> list[Path]:
    """
    Find audio files that have no corresponding transcript.

    Args:
        audio_dir: Directory containing audio files.
        transcript_dir: Directory containing transcript .txt files.
        audio_extensions: File extensions to consider (default: ['.mp3', '.wav', '.m4a']).

    Returns:
        Sorted list of audio file paths missing transcripts.
    """
    if audio_extensions is None:
        audio_extensions = [".mp3", ".wav", ".m4a"]

    existing_transcripts = set()
    if transcript_dir.exists():
        existing_transcripts = {
            p.stem for p in transcript_dir.glob("*.txt") if p.stat().st_size > 0
        }

    missing: list[Path] = []
    if not audio_dir.exists():
        logger.warning("Audio directory does not exist: %s", audio_dir)
        return missing

    audio_files = sorted(audio_dir.iterdir())
    total_audio = sum(1 for f in audio_files if f.suffix.lower() in audio_extensions)
    for audio_file in audio_files:
        if (
            audio_file.suffix.lower() in audio_extensions
            and audio_file.stem not in existing_transcripts
        ):
            missing.append(audio_file)

    logger.info(
        "Found %d audio files missing transcripts (out of %d total audio files)",
        len(missing),
        total_audio,
    )
    return missing


def transcribe_missing(
    audio_dir: Path,
    transcript_dir: Path,
    model: str = DEFAULT_MODEL,
    language: str = "en",
    max_files: int | None = None,
    audio_extensions: list[str] | None = None,
) -> TranscriptionSummary:
    """
    Batch-transcribe all audio files missing transcripts.

    Args:
        audio_dir: Directory containing audio files.
        transcript_dir: Directory to save transcript .txt files.
        model: MLX Whisper model identifier.
        language: Language code for transcription.
        max_files: Optional limit on number of files to transcribe.
        audio_extensions: File extensions to consider.

    Returns:
        TranscriptionSummary with counts and individual results.
    """
    missing = find_missing_transcripts(audio_dir, transcript_dir, audio_extensions)

    if max_files:
        missing = missing[:max_files]

    summary = TranscriptionSummary(total=len(missing))
    logger.info("Starting batch transcription of %d files", len(missing))
    batch_start = time.time()

    for idx, audio_path in enumerate(missing, 1):
        logger.info("[%d/%d] Transcribing %s", idx, summary.total, audio_path.name)

        result = transcribe_audio(
            audio_path=audio_path,
            output_dir=transcript_dir,
            model=model,
            language=language,
            skip_existing=True,
        )
        summary.results.append(result)

        if result.status == TranscriptionStatus.SUCCESS:
            summary.success += 1
        elif result.status == TranscriptionStatus.SKIPPED:
            summary.skipped += 1
        else:
            summary.failed += 1

        if result.duration_seconds:
            summary.total_duration_seconds += result.duration_seconds

    elapsed = time.time() - batch_start
    logger.info(
        "Batch transcription complete: %d success, %d skipped, %d failed (%.1fs total)",
        summary.success,
        summary.skipped,
        summary.failed,
        elapsed,
    )
    return summary
