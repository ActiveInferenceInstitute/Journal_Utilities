"""
Channel video enumeration for Journal Utilities.

This module provides functionality to enumerate all videos from a YouTube
channel using yt-dlp (no API key required). It produces a channel manifest
that can be consumed by the downloader module.
"""

import json
import logging
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """Metadata for a single YouTube video."""

    id: str
    title: str = ""
    upload_date: str = ""
    duration: float | None = None
    description: str = ""
    view_count: int | None = None
    url: str = ""

    def __post_init__(self) -> None:
        if not self.url and self.id:
            self.url = f"https://www.youtube.com/watch?v={self.id}"


@dataclass
class ChannelManifest:
    """Manifest of all videos on a YouTube channel."""

    channel_id: str
    channel_url: str = ""
    enumerated_at: str = ""
    total_videos: int = 0
    videos: list[VideoInfo] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.channel_url and self.channel_id:
            self.channel_url = f"https://www.youtube.com/channel/{self.channel_id}"
        if not self.enumerated_at:
            self.enumerated_at = datetime.now(UTC).isoformat()


def enumerate_channel_videos(
    channel_id: str,
    max_videos: int | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
    output_path: Path | None = None,
) -> ChannelManifest:
    """
    Enumerate all videos from a YouTube channel using yt-dlp.

    Uses ``yt-dlp --flat-playlist --dump-json`` to list every video on
    the channel without downloading any media.

    Args:
        channel_id: YouTube channel ID (e.g. ``UCbPq2w41ZaJSWtpCq4BE6Dg``).
        max_videos: Optional limit on the number of videos to retrieve.
        date_after: Optional YYYYMMDD — only include videos uploaded after this date.
        date_before: Optional YYYYMMDD — only include videos uploaded before this date.
        output_path: If provided, save the manifest JSON to this path.

    Returns:
        A :class:`ChannelManifest` containing all discovered videos.

    Raises:
        RuntimeError: If yt-dlp exits with a non-zero status.
    """
    # Enumerate across the channel's tabs (videos + streams + shorts) and union the
    # results, because the Uploads playlist (UU...) form is truncated to ~100 entries
    # by YouTube. The /videos and /streams tabs together cover the full library.
    if channel_id.startswith("UC") and len(channel_id) == 24:
        base = f"https://www.youtube.com/channel/{channel_id}"
        urls = [f"{base}/videos", f"{base}/streams", f"{base}/shorts"]
        logger.info("Enumerating channel %s across tabs: videos, streams, shorts", channel_id)
    else:
        urls = [f"https://www.youtube.com/channel/{channel_id}"]
        logger.info("Enumerating videos for channel %s", channel_id)

    base_cmd: list[str] = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--ignore-errors",
        # Modern browser User-Agent avoids YouTube 403s during scraping (AGENTS.md).
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ]
    if date_after:
        base_cmd.extend(["--dateafter", date_after])
    if date_before:
        base_cmd.extend(["--datebefore", date_before])
    if max_videos:
        base_cmd.extend(["--playlist-end", str(max_videos)])

    videos: list[VideoInfo] = []
    seen: set[str] = set()
    start_time = time.monotonic()
    for url in urls:
        cmd = [*base_cmd, url]
        logger.debug("Running command: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp timed out enumerating %s", url)
            continue
        if result.returncode != 0 and not result.stdout.strip():
            logger.warning(
                "yt-dlp tab %s failed (exit %d): %s", url, result.returncode, result.stderr[:200]
            )
            continue
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                video = _parse_video_entry(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON line: %s", exc)
                continue
            if video and video.id not in seen:
                seen.add(video.id)
                videos.append(video)
                if max_videos and len(videos) >= max_videos:
                    break
        if max_videos and len(videos) >= max_videos:
            break

    elapsed = time.monotonic() - start_time
    logger.info("yt-dlp enumeration completed in %.1fs across %d tab(s)", elapsed, len(urls))

    manifest = ChannelManifest(
        channel_id=channel_id,
        total_videos=len(videos),
        videos=videos,
    )

    logger.info("Found %d videos on channel %s", len(videos), channel_id)

    if output_path:
        save_channel_manifest(manifest, output_path)

    return manifest


def _parse_video_entry(entry: dict) -> VideoInfo | None:
    """Parse a single yt-dlp JSON entry into a VideoInfo."""
    video_id = entry.get("id") or entry.get("url")
    if not video_id:
        return None

    # yt-dlp --flat-playlist sometimes gives just the ID in 'url' field
    # Strip any URL prefix to get just the ID
    video_id = str(video_id)
    # Handle full YouTube URLs: extract ID from watch?v= pattern
    match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", video_id)
    if match:
        video_id = match.group(1)
    elif "/" in video_id:
        video_id = video_id.rsplit("/", 1)[-1]

    return VideoInfo(
        id=video_id,
        title=entry.get("title", ""),
        upload_date=entry.get("upload_date", ""),
        duration=entry.get("duration"),
        description=entry.get("description", ""),
        view_count=entry.get("view_count"),
    )


def save_channel_manifest(manifest: ChannelManifest, path: Path) -> None:
    """
    Save a channel manifest to a JSON file.

    Args:
        manifest: The manifest to save.
        path: Destination file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "channel_id": manifest.channel_id,
        "channel_url": manifest.channel_url,
        "enumerated_at": manifest.enumerated_at,
        "total_videos": manifest.total_videos,
        "videos": [asdict(v) for v in manifest.videos],
    }

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved channel manifest to %s (%d videos)", path, manifest.total_videos)


def load_channel_manifest(path: Path) -> ChannelManifest:
    """
    Load a previously saved channel manifest from a JSON file.

    Args:
        path: Path to the manifest JSON file.

    Returns:
        A :class:`ChannelManifest` populated from the file.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    path = Path(path)
    logger.info("Loading channel manifest from %s", path)

    data = json.loads(path.read_text(encoding="utf-8"))
    videos = [VideoInfo(**v) for v in data.get("videos", [])]

    manifest = ChannelManifest(
        channel_id=data.get("channel_id", ""),
        channel_url=data.get("channel_url", ""),
        enumerated_at=data.get("enumerated_at", ""),
        total_videos=data.get("total_videos", len(videos)),
        videos=videos,
    )

    logger.info("Loaded manifest with %d videos", manifest.total_videos)
    return manifest
