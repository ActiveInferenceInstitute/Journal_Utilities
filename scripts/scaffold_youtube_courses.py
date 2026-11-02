#!/usr/bin/env python3
"""
Scaffold YouTube courses from Active Inference channel playlists.

Enumerates playlists, downloads transcripts for each video, and creates
a course directory structure with module.md files.

Usage examples:
    # Enumerate playlists only (no downloads)
    python scripts/scaffold_youtube_courses.py --enumerate-only

    # Scaffold courses from playlists (uses existing transcripts)
    python scripts/scaffold_youtube_courses.py --transcript-dir data/output --courses-dir data/courses

    # Full pipeline: enumerate, download transcripts, scaffold
    python scripts/scaffold_youtube_courses.py --download --max-playlists 3

    # Use a saved playlist manifest
    python scripts/scaffold_youtube_courses.py --manifest data/output/playlists.json --download
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from journal_utilities.download.downloader import DownloadStatus, download_transcript
from journal_utilities.render.renderer import scaffold_course, slugify
from journal_utilities.youtube.playlist import (
    PlaylistManifest,
    enumerate_playlist_videos,
    enumerate_playlists,
    load_playlist_manifest,
    rate_limit_sleep,
    save_playlist_manifest,
)

# Active Inference Institute channel ID
DEFAULT_CHANNEL_ID = "UCbPq2w41ZaJSWtpCq4BE6Dg"
DEFAULT_OUTPUT_DIR = Path("data/output")
DEFAULT_COURSES_DIR = Path("data/courses")


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Scaffold YouTube courses from channel playlists.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Channel / source options
    parser.add_argument(
        "--channel-id",
        default=DEFAULT_CHANNEL_ID,
        help=f"YouTube channel ID (default: {DEFAULT_CHANNEL_ID})",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to a previously saved playlist manifest JSON (skips enumeration)",
    )

    # Output directories
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Base output directory for transcripts (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--courses-dir",
        type=Path,
        default=DEFAULT_COURSES_DIR,
        help=f"Directory for scaffolded courses (default: {DEFAULT_COURSES_DIR})",
    )
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        help="Directory containing existing transcripts (default: same as --output-dir)",
    )

    # Mode flags
    parser.add_argument(
        "--enumerate-only",
        action="store_true",
        help="Only enumerate playlists; do not download or scaffold",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download transcripts for playlist videos before scaffolding",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing module.md files",
    )

    # Limits
    parser.add_argument(
        "--max-playlists",
        type=int,
        help="Maximum number of playlists to process",
    )
    parser.add_argument(
        "--max-videos-per-playlist",
        type=int,
        help="Maximum videos per playlist to process",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between downloads in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        type=str,
        default=None,
        help="Browser to extract cookies from (e.g. safari, chrome, firefox)",
    )

    # Verbosity
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

    args.output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(args.verbose)

    logger = logging.getLogger("scaffold_youtube_courses")
    logger.info("=" * 60)
    logger.info("YouTube Course Scaffolder")
    logger.info("=" * 60)

    transcript_dir = args.transcript_dir or args.output_dir

    # ------------------------------------------------------------------
    # Phase 1: Enumerate or load playlists
    # ------------------------------------------------------------------
    manifest_path = args.output_dir / "playlist_manifest.json"

    if args.manifest and args.manifest.exists():
        logger.info("Loading playlist manifest from %s", args.manifest)
        manifest = load_playlist_manifest(args.manifest)
        playlists_data = manifest.playlists
    else:
        logger.info("Enumerating playlists for channel %s", args.channel_id)
        raw_playlists = enumerate_playlists(
            channel_id=args.channel_id,
            max_playlists=args.max_playlists,
        )
        logger.info("Found %d playlists", len(raw_playlists))

        # For each playlist, enumerate its videos
        playlists_data: dict = {}
        for i, playlist in enumerate(raw_playlists):
            logger.info(
                "[%d/%d] Enumerating: %s (%s)",
                i + 1,
                len(raw_playlists),
                playlist.title,
                playlist.id,
            )
            videos = enumerate_playlist_videos(
                playlist.url,
                max_videos=args.max_videos_per_playlist,
            )
            playlist_slug = slugify(playlist.title)
            playlists_data[playlist_slug] = {
                "id": playlist.id,
                "title": playlist.title,
                "url": playlist.url,
                "slug": playlist_slug,
                "video_count": len(videos),
                "videos": [
                    {
                        "id": v.id,
                        "title": v.title,
                        "duration": v.duration,
                        "upload_date": v.upload_date,
                    }
                    for v in videos
                ],
            }

            if i < len(raw_playlists) - 1:
                rate_limit_sleep(i, delay=args.delay)

        # Save manifest
        manifest = PlaylistManifest(
            channel_id=args.channel_id,
            total_playlists=len(playlists_data),
            playlists=playlists_data,
        )
        save_playlist_manifest(manifest, manifest_path)
        logger.info("Saved playlist manifest to %s", manifest_path)

    if args.enumerate_only:
        logger.info("Enumeration complete. %d playlists found.", len(playlists_data))
        return 0

    # ------------------------------------------------------------------
    # Phase 2: Download transcripts (optional)
    # ------------------------------------------------------------------
    if args.download:
        logger.info("Downloading transcripts...")
        total_downloaded = 0
        total_skipped = 0
        total_failed = 0

        for slug, playlist_info in playlists_data.items():
            videos = playlist_info.get("videos", [])
            logger.info(
                "Downloading transcripts for '%s' (%d videos)",
                playlist_info.get("title", slug),
                len(videos),
            )

            for j, video in enumerate(videos):
                vid = video.get("id", "")
                if not vid:
                    continue

                result = download_transcript(
                    vid,
                    transcript_dir,
                    skip_existing=True,
                    cookies_from_browser=args.cookies_from_browser,
                )

                if result.status == DownloadStatus.SUCCESS:
                    total_downloaded += 1
                elif result.status == DownloadStatus.SKIPPED:
                    total_skipped += 1
                else:
                    total_failed += 1

                if j < len(videos) - 1:
                    rate_limit_sleep(j, delay=args.delay)

        logger.info(
            "Transcript downloads: %d new, %d skipped, %d failed",
            total_downloaded,
            total_skipped,
            total_failed,
        )

    # ------------------------------------------------------------------
    # Phase 3: Scaffold courses
    # ------------------------------------------------------------------
    logger.info("Scaffolding courses into %s", args.courses_dir)
    total_created = 0
    total_course_skipped = 0
    total_course_failed = 0

    for slug, playlist_info in playlists_data.items():
        videos = playlist_info.get("videos", [])
        if not videos:
            logger.info("Skipping empty playlist: %s", slug)
            continue

        result = scaffold_course(
            course_slug=slug,
            videos=videos,
            transcript_dir=transcript_dir,
            courses_dir=args.courses_dir,
            playlist_title=playlist_info.get("title", ""),
            force=args.force,
        )

        total_created += result["created"]
        total_course_skipped += result["skipped"]
        total_course_failed += result["failed"]

    logger.info("=" * 60)
    logger.info("SCAFFOLDING COMPLETE")
    logger.info("  Playlists processed: %d", len(playlists_data))
    logger.info("  Modules created:     %d", total_created)
    logger.info("  Modules skipped:     %d", total_course_skipped)
    logger.info("  Modules failed:      %d", total_course_failed)
    logger.info("  Output directory:    %s", args.courses_dir)
    logger.info("=" * 60)

    return 0 if total_course_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
