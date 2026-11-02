#!/usr/bin/env python3
"""
Transcribe audio files that are missing transcripts using local Whisper (mlx-whisper).

Usage:
    # Transcribe all missing (uses default dirs)
    python scripts/transcribe_missing.py

    # Specify custom dirs and model
    python scripts/transcribe_missing.py \\
        --audio-dir data/output/audio \\
        --transcript-dir data/output/transcripts \\
        --model mlx-community/whisper-large-v3-turbo

    # Limit to 5 files for testing
    python scripts/transcribe_missing.py --max-files 5
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from journal_utilities.transcribe.transcriber import (
    DEFAULT_MODEL,
    TranscriptionStatus,
    find_missing_transcripts,
    transcribe_missing,
)


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Transcribe audio files missing transcripts using local Whisper.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=Path("data/output/audio"),
        help="Directory containing audio files (default: data/output/audio)",
    )
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        default=Path("data/output/transcripts"),
        help="Directory for transcript output (default: data/output/transcripts)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"MLX Whisper model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Transcription language (default: en)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of files to transcribe",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list missing transcripts without transcribing",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger("transcribe_missing")

    logger.info("=" * 60)
    logger.info("Local Whisper Transcription (mlx-whisper)")
    logger.info("=" * 60)
    logger.info("Audio dir:      %s", args.audio_dir)
    logger.info("Transcript dir: %s", args.transcript_dir)
    logger.info("Model:          %s", args.model)
    logger.info("Language:       %s", args.language)

    # Dry-run: just list missing files
    if args.dry_run:
        missing = find_missing_transcripts(args.audio_dir, args.transcript_dir)
        logger.info("Missing transcripts: %d", len(missing))
        for path in missing:
            print(f"  {path.stem}  ({path.name})")
        return 0

    # Run transcription
    summary = transcribe_missing(
        audio_dir=args.audio_dir,
        transcript_dir=args.transcript_dir,
        model=args.model,
        language=args.language,
        max_files=args.max_files,
    )

    # Report
    logger.info("=" * 60)
    logger.info("TRANSCRIPTION COMPLETE")
    logger.info("  Total processed:  %d", summary.total)
    logger.info("  Successful:       %d", summary.success)
    logger.info("  Skipped:          %d", summary.skipped)
    logger.info("  Failed:           %d", summary.failed)
    logger.info("  Total time:       %.1fs", summary.total_duration_seconds)
    logger.info("=" * 60)

    # Print failures for review
    failures = [r for r in summary.results if r.status == TranscriptionStatus.FAILED]
    if failures:
        logger.warning("Failed transcriptions:")
        for r in failures:
            logger.warning("  %s: %s", r.video_id, r.error)

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
