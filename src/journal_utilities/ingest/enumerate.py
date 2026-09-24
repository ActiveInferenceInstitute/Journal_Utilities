"""Weekly channel enumeration via the YouTube Data API (read-only).

Replaces the weekly yt-dlp scrape for the ingest gate: ``playlistItems.list``
over the channel's uploads playlist + batched ``videos.list`` calls for
snippet/duration/status. All writes are forbidden here by design — this module
never mutates YouTube state (Rule 1/2).

Quota per weekly run against the 10,000/day budget (see
``journal_utilities.youtube.client.QUOTA_COSTS``):
- ``channels.list`` (uploads playlist id): 1 unit
- ``playlistItems.list``: 1 unit per page of 50 (~16 pages for ~750 videos)
- ``videos.list``: 1 unit per batch of 50 ids (~15 batches)

~32 units/run — two orders of magnitude under budget.

The journal's ``INDEX.json`` is the source of truth for what is already
ingested: every ``items[].parts[]`` entry is a video id. The diff emits the
new-video worklist the scaffolder consumes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from journal_utilities.youtube.client import YouTubeClient

logger = logging.getLogger(__name__)

#: @ActiveInference channel (as used across scripts/).
DEFAULT_CHANNEL_ID = "UCbPq2w41ZaJSWtpCq4BE6Dg"

_INDEX_FILENAME = "INDEX.json"

_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_iso8601_duration(value: str) -> int | None:
    """Parse an ISO-8601 duration (``PT1H2M3S``) into whole seconds.

    Returns ``None`` for absent/malformed values (callers must not guess).
    """
    if not value:
        return None
    match = _ISO_DURATION_RE.match(value)
    if not match:
        return None
    parts = match.groupdict()
    if not any(parts.values()):
        return None
    return int(
        86400 * int(parts["days"] or 0)
        + 3600 * int(parts["hours"] or 0)
        + 60 * int(parts["minutes"] or 0)
        + int(parts["seconds"] or 0)
    )


@dataclass
class ChannelVideo:
    """One enumerated upload, normalized for diffing and scaffolding."""

    video_id: str
    title: str
    published_at: str = ""
    duration_seconds: int | None = None
    privacy_status: str = ""
    upload_status: str = ""
    broadcast_status: str = ""
    description: str = ""

    @property
    def published_date(self) -> str:
        """``YYYY-MM-DD`` date part of ``published_at`` (empty if unknown)."""
        return self.published_at[:10] if self.published_at else ""

    @property
    def is_scheduled(self) -> bool:
        """True for premieres/upcoming broadcasts not yet publicly viewable."""
        return self.broadcast_status == "upcoming" or self.upload_status == "unpublished"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = asdict(self)
        data["published_date"] = self.published_date
        data["is_scheduled"] = self.is_scheduled
        data["url"] = self.url
        return data


def load_index_video_ids(index_path: Path) -> set[str]:
    """Collect every video id referenced by the journal's ``INDEX.json``.

    Tolerant by design: a malformed/missing index yields an empty set (the
    caller decides whether that is fatal), never an exception mid-pipeline.
    """
    try:
        index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot read INDEX.json at %s: %s", index_path, exc)
        return set()
    items = index.get("items") if isinstance(index, dict) else None
    ids: set[str] = set()
    if not isinstance(items, list):
        return ids
    for entry in items:
        if not isinstance(entry, dict):
            continue
        parts = entry.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, str) and part.strip():
                ids.add(part.strip())
    return ids


def _enumerate_upload_items(client: YouTubeClient, channel_id: str) -> list[dict[str, Any]]:
    """Fetch uploads-playlist items via the injected (possibly fake) client."""
    uploads_playlist = client.get_uploads_playlist_id(channel_id)
    if not uploads_playlist:
        raise RuntimeError(
            f"Could not resolve uploads playlist for channel {channel_id} "
            "(channels.list returned nothing) — check YOUTUBE_API_KEY/network."
        )
    return client.list_playlist_items(uploads_playlist)


def _fetch_video_details(
    client: YouTubeClient, video_ids: list[str], batch_size: int = 50
) -> dict[str, dict[str, Any]]:
    """Batched videos.list (part=snippet,contentDetails,status), 1 unit/batch."""
    details: dict[str, dict[str, Any]] = {}
    for start in range(0, len(video_ids), batch_size):
        batch = video_ids[start : start + batch_size]
        try:
            response = (
                client.service.videos()
                .list(part="snippet,contentDetails,status", id=",".join(batch))
                .execute()
            )
        except Exception as exc:  # googleapiclient HttpError family
            logger.warning("videos.list batch failed (%d ids): %s", len(batch), exc)
            continue
        for item in response.get("items", []):
            if isinstance(item, dict) and item.get("id"):
                details[str(item["id"])] = item
    return details


def enumerate_channel_videos(
    client: YouTubeClient, channel_id: str = DEFAULT_CHANNEL_ID
) -> list[ChannelVideo]:
    """Enumerate the channel's uploads playlist via the Data API (read-only).

    Args:
        client: YouTube client with an injected real or fake service.
        channel_id: Channel to enumerate.

    Returns:
        Videos in upload-playlist order (newest first), one unit of quota
        per 50 playlist items / 50 video details.

    Raises:
        RuntimeError: If the uploads playlist cannot be resolved.
    """
    items = _enumerate_upload_items(client, channel_id)
    playlist_order: list[str] = []
    fallback_titles: dict[str, str] = {}
    fallback_dates: dict[str, str] = {}
    for item in items:
        snippet = item.get("snippet") or {}
        content = item.get("contentDetails") or {}
        video_id = str(content.get("videoId") or snippet.get("resourceId", {}).get("videoId") or "")
        if not video_id or video_id in fallback_titles:
            continue
        playlist_order.append(video_id)
        fallback_titles[video_id] = str(snippet.get("title") or "")
        fallback_dates[video_id] = str(item.get("contentDetails", {}).get("videoPublishedAt") or "")

    details = _fetch_video_details(client, playlist_order)

    videos: list[ChannelVideo] = []
    for video_id in playlist_order:
        detail = details.get(video_id)
        snippet = (detail or {}).get("snippet") or {}
        content = (detail or {}).get("contentDetails") or {}
        status = (detail or {}).get("status") or {}
        videos.append(
            ChannelVideo(
                video_id=video_id,
                title=str(snippet.get("title") or fallback_titles.get(video_id, "")),
                published_at=str(snippet.get("publishedAt") or fallback_dates.get(video_id, "")),
                duration_seconds=parse_iso8601_duration(str(content.get("duration") or "")),
                privacy_status=str(status.get("privacyStatus") or ""),
                upload_status=str(status.get("uploadStatus") or ""),
                broadcast_status=str(snippet.get("liveBroadcastContent") or ""),
                description=str(snippet.get("description") or ""),
            )
        )
    logger.info(
        "Enumerated %d playlist items for %s (%d resolved via videos.list)",
        len(playlist_order),
        channel_id,
        len(details),
    )
    return videos


def diff_against_index(videos: list[ChannelVideo], index_video_ids: set[str]) -> list[ChannelVideo]:
    """Return channel videos whose id is absent from the journal index."""
    return [video for video in videos if video.video_id not in index_video_ids]


@dataclass
class Worklist:
    """New-video worklist emitted for the scaffolder (and CI artifacts)."""

    channel_id: str
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    index_video_count: int = 0
    channel_video_count: int = 0
    new_videos: list[ChannelVideo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "generated_at": self.generated_at,
            "index_video_count": self.index_video_count,
            "channel_video_count": self.channel_video_count,
            "new_video_count": len(self.new_videos),
            "new_videos": [video.to_dict() for video in self.new_videos],
        }


def build_worklist(
    client: YouTubeClient,
    index_path: Path,
    channel_id: str = DEFAULT_CHANNEL_ID,
) -> Worklist:
    """Enumerate the channel and diff it against the journal index."""
    videos = enumerate_channel_videos(client, channel_id)
    index_ids = load_index_video_ids(index_path)
    return Worklist(
        channel_id=channel_id,
        index_video_count=len(index_ids),
        channel_video_count=len(videos),
        new_videos=diff_against_index(videos, index_ids),
    )


def _build_client(api_key: str | None) -> YouTubeClient:
    """Build a read-only client; an explicit/inherited key is required."""
    key = api_key or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit(
            "YOUTUBE_API_KEY is not set — live enumeration is unavailable. "
            "Set the key, or run scripts/diff-based reconciliation "
            "(journal_utilities.ingest.diff) which needs no API access."
        )
    return YouTubeClient(api_key=key)


def main(argv: list[str] | None = None) -> int:
    """CLI: weekly enumeration + worklist emission. Dry-run is the default."""
    parser = argparse.ArgumentParser(
        prog="journal_utilities.ingest.enumerate",
        description=(
            "Enumerate the Active Inference channel via the YouTube Data API "
            "(read-only) and diff it against the journal INDEX.json."
        ),
    )
    parser.add_argument("--channel-id", default=DEFAULT_CHANNEL_ID)
    parser.add_argument(
        "--journal",
        type=Path,
        required=True,
        help="Journal checkout root (INDEX.json is read from it)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Worklist JSON destination (only written with --no-dry-run)",
    )
    parser.add_argument("--api-key", default=None, help="Defaults to $YOUTUBE_API_KEY")
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually write the worklist file (default: dry-run)",
    )
    parser.set_defaults(dry_run=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    index_path = args.journal / "INDEX.json"
    index_ids = load_index_video_ids(index_path)
    if not index_ids:
        # A missing/malformed INDEX would make every channel video look "new";
        # refuse rather than mint scaffolds for the whole catalog.
        raise SystemExit(
            f"No video ids could be read from {index_path} — refusing to diff "
            "against an empty index. Check the --journal path."
        )
    videos = enumerate_channel_videos(_build_client(args.api_key), args.channel_id)
    worklist = Worklist(
        channel_id=args.channel_id,
        index_video_count=len(index_ids),
        channel_video_count=len(videos),
        new_videos=diff_against_index(videos, index_ids),
    )
    payload = worklist.to_dict()
    print(f"channel videos: {worklist.channel_video_count}")
    print(f"index video ids: {worklist.index_video_count}")
    print(f"new videos: {len(worklist.new_videos)}")
    for video in worklist.new_videos:
        state = "scheduled" if video.is_scheduled else "published"
        print(f"  {video.video_id}  [{state}]  {video.published_date}  {video.title}")
    if args.output is not None:
        if args.dry_run:
            print(f"dry-run: would write worklist to {args.output}")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"wrote worklist to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
