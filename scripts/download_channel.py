#!/usr/bin/env python3
"""
Download transcripts, audio, and video from the Active Inference YouTube channel.

Usage examples:
    # Enumerate channel and download all transcripts
    python scripts/download_channel.py --transcripts --max-videos 10

    # Download audio as MP3 for all videos
    python scripts/download_channel.py --audio --audio-format mp3

    # Download everything with rate limiting
    python scripts/download_channel.py --transcripts --audio --video --delay 3.0

    # Resume a previous download (skip existing files)
    python scripts/download_channel.py --transcripts --audio --resume

    # Use a saved manifest instead of re-enumerating
    python scripts/download_channel.py --manifest data/output/channel_videos.json --transcripts

    # Download everything and use local Whisper for missing transcripts (Apple Silicon)
    python scripts/download_channel.py --transcripts --audio --transcribe-missing
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from journal_utilities.download.downloader import (
    DownloadStatus,
    VideoDownloadSummary,
    download_audio,
    download_transcript,
    download_video,
    save_download_manifest,
)
from journal_utilities.youtube.channel import (
    enumerate_channel_videos,
    load_channel_manifest,
)

# Active Inference Institute channel ID
DEFAULT_CHANNEL_ID = "UCbPq2w41ZaJSWtpCq4BE6Dg"
DEFAULT_OUTPUT_DIR = Path("data/output")


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("data/output/download.log", mode="a"),
        ],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Download transcripts, audio, and video from a YouTube channel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Channel options
    parser.add_argument(
        "--channel-id",
        default=DEFAULT_CHANNEL_ID,
        help=f"YouTube channel ID (default: {DEFAULT_CHANNEL_ID})",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to a previously saved channel manifest JSON (skips enumeration)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )

    # Download type flags
    parser.add_argument("--transcripts", action="store_true", help="Download transcripts")
    parser.add_argument("--audio", action="store_true", help="Download audio")
    parser.add_argument("--video", action="store_true", help="Download video")

    # Format options
    parser.add_argument(
        "--audio-format",
        default="mp3",
        choices=["mp3", "wav", "m4a"],
        help="Audio format (default: mp3)",
    )
    parser.add_argument(
        "--video-quality",
        default="best",
        choices=["best", "720p", "480p", "360p"],
        help="Video quality preset (default: best)",
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["en"],
        help="Transcript languages (default: en)",
    )

    # Control options
    parser.add_argument(
        "--max-videos",
        type=int,
        help="Maximum number of videos to process",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between downloads (default: 1.0)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip already-downloaded files",
    )
    parser.add_argument(
        "--date-after",
        help="Only include videos after this date (YYYYMMDD)",
    )
    parser.add_argument(
        "--date-before",
        help="Only include videos before this date (YYYYMMDD)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--enumerate-only",
        action="store_true",
        help="Only enumerate videos; do not download anything",
    )
    parser.add_argument(
        "--cookies-from-browser",
        type=str,
        default=None,
        help="Browser to extract cookies from (e.g. safari, chrome, firefox). "
        "Helps bypass YouTube rate limiting and bot detection.",
    )

    # Whisper local transcription fallback
    parser.add_argument(
        "--transcribe-missing",
        action="store_true",
        help="After downloads, transcribe audio files that lack transcripts using local Whisper.",
    )
    parser.add_argument(
        "--whisper-model",
        default="mlx-community/whisper-large-v3-turbo",
        help="MLX Whisper model for local transcription (default: mlx-community/whisper-large-v3-turbo)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    # Ensure output directory exists for the log file
    args.output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(args.verbose)

    logger = logging.getLogger("download_channel")
    logger.info("=" * 60)
    logger.info("Active Inference Channel Downloader")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Phase 1: Enumerate or load channel manifest
    # ------------------------------------------------------------------
    manifest_path = args.output_dir / "channel_videos.json"

    if args.manifest and args.manifest.exists():
        logger.info("Loading channel manifest from %s", args.manifest)
        manifest = load_channel_manifest(args.manifest)
    else:
        logger.info("Enumerating videos for channel %s", args.channel_id)
        manifest = enumerate_channel_videos(
            channel_id=args.channel_id,
            max_videos=args.max_videos,
            date_after=args.date_after,
            date_before=args.date_before,
            output_path=manifest_path,
        )

    logger.info("Channel manifest: %d videos", manifest.total_videos)

    if args.enumerate_only:
        logger.info("Enumeration complete. Manifest saved to %s", manifest_path)
        return 0

    # Validate that at least one download type is selected
    if not (args.transcripts or args.audio or args.video):
        logger.error("No download type selected. Use --transcripts, --audio, and/or --video.")
        return 1

    # ------------------------------------------------------------------
    # Phase 2: Download assets for each video
    # ------------------------------------------------------------------
    videos = manifest.videos
    if args.max_videos and not args.manifest:
        # max_videos was already applied during enumeration,
        # but if using a pre-existing manifest, apply the limit here
        pass
    if args.max_videos and args.manifest:
        videos = videos[: args.max_videos]

    total = len(videos)
    summaries: list[VideoDownloadSummary] = []
    counts = {"success": 0, "skipped": 0, "failed": 0}

    logger.info(
        "Starting downloads: %d videos | transcripts=%s audio=%s video=%s",
        total,
        args.transcripts,
        args.audio,
        args.video,
    )

    for idx, video in enumerate(videos, 1):
        logger.info("[%d/%d] Processing %s — %s", idx, total, video.id, video.title)

        # Refactored orchestration with smart fallback
        summary = VideoDownloadSummary(video_id=video.id)

        # 1. Download Transcript
        if args.transcripts:
            res = download_transcript(
                video_id=video.id,
                output_dir=args.output_dir,
                languages=args.languages,
                skip_existing=args.resume,
                cookies_from_browser=args.cookies_from_browser,
            )
            summary.results.append(res)

            details = ""
            if res.status in (DownloadStatus.SUCCESS, DownloadStatus.SKIPPED) and res.file_size_str:
                details = f" ({res.file_size_str})"
            elif res.error:
                details = f" ({res.error})"

            logger.info("Transcript for %s: %s%s", video.id, res.status.value, details)

        # 2. Download Audio (Conditional)
        do_audio = args.audio
        if do_audio:
            res = download_audio(
                video_id=video.id,
                output_dir=args.output_dir,
                audio_format=args.audio_format,
                skip_existing=args.resume,
                cookies_from_browser=args.cookies_from_browser,
            )
            summary.results.append(res)

            details = ""
            if res.status in (DownloadStatus.SUCCESS, DownloadStatus.SKIPPED) and res.file_size_str:
                details = f" ({res.file_size_str})"
            elif res.error:
                details = f" ({res.error})"

            logger.info("Audio for %s: %s%s", video.id, res.status.value, details)

        # 3. Download Video
        if args.video:
            res = download_video(
                video_id=video.id,
                output_dir=args.output_dir,
                quality=args.video_quality,
                skip_existing=args.resume,
                cookies_from_browser=args.cookies_from_browser,
            )
            summary.results.append(res)

            details = ""
            if res.status in (DownloadStatus.SUCCESS, DownloadStatus.SKIPPED) and res.file_size_str:
                details = f" ({res.file_size_str})"
            elif res.error:
                details = f" ({res.error})"

            logger.info("Video for %s: %s%s", video.id, res.status.value, details)

        summaries.append(summary)

        # Tally results
        for result in summary.results:
            counts[result.status.value] = counts.get(result.status.value, 0) + 1

        # Rate limiting
        if idx < total and args.delay > 0:
            time.sleep(args.delay)

    # ------------------------------------------------------------------
    # Phase 2.5: Local Whisper transcription fallback
    # ------------------------------------------------------------------
    if args.transcribe_missing:
        logger.info("=" * 60)
        logger.info("Phase 2.5: Local Whisper Transcription")
        logger.info("=" * 60)
        try:
            from journal_utilities.transcribe.transcriber import transcribe_missing

            audio_dir = args.output_dir / "audio"
            transcript_dir = args.output_dir / "transcripts"
            tsummary = transcribe_missing(
                audio_dir=audio_dir,
                transcript_dir=transcript_dir,
                model=args.whisper_model,
            )
            logger.info(
                "Whisper transcription: %d success, %d skipped, %d failed",
                tsummary.success,
                tsummary.skipped,
                tsummary.failed,
            )
        except ImportError:
            logger.error("mlx-whisper not installed. Install with: uv pip install mlx-whisper")
        except Exception as exc:
            logger.error("Whisper transcription failed: %s", exc)

    # ------------------------------------------------------------------
    # Phase 3: Save download manifest and report
    # ------------------------------------------------------------------
    download_manifest_path = args.output_dir / "download_manifest.json"
    save_download_manifest(summaries, download_manifest_path)

    logger.info("=" * 60)
    logger.info("DOWNLOAD COMPLETE")
    logger.info("  Total videos processed: %d", total)
    logger.info("  Successful downloads:   %d", counts["success"])
    logger.info("  Skipped (existing):     %d", counts["skipped"])
    logger.info("  Failed:                 %d", counts["failed"])
    logger.info("  Manifest saved to:      %s", download_manifest_path)
    logger.info("=" * 60)

    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
