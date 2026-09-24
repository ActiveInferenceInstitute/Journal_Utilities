#!/usr/bin/env python3
"""READ-ONLY audit of live YouTube video descriptions (Data API only).

Scans the channel's uploads playlist and flags videos whose live description
contains the dead ``/blob/main/transcripts/`` link pattern (Y1/E1/I1) or the
``RESOURCES & TRANSCRIPT`` block emitted by the metadata sync. Never writes to
YouTube: API-key reads only, no OAuth, no captions/playlists access.

Usage:
    YOUTUBE_API_KEY=... uv run python scripts/audit_live_descriptions.py
    uv run python scripts/audit_live_descriptions.py --report data/output/audit.json

Quota: channels.list 1 + playlistItems.list 1/page + videos.list 1/50 videos
(~16 units for a 757-video channel). No key -> clear setup note, exit 1.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from journal_utilities.youtube.client import YouTubeClient

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHANNEL_ID = "UCbPq2w41ZaJSWtpCq4BE6Dg"  # @ActiveInference
DEFAULT_REPORT = REPO_ROOT / "data/output/audit_live_descriptions.json"

DEAD_TRANSCRIPT_PATTERN = "/blob/main/transcripts/"
RESOURCES_BLOCK_PATTERN = "RESOURCES & TRANSCRIPT"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("audit_live_descriptions")


def build_client() -> YouTubeClient:
    """Build the vendored read-only client; exits with a setup note if no key."""
    from journal_utilities.youtube.client import YouTubeClient

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print(
            "\nYouTube Data API key required (reads only; no OAuth needed):\n"
            "  1. Create a Google Cloud project and enable 'YouTube Data API v3'.\n"
            "  2. Create an API key (Credentials -> Create credentials -> API key).\n"
            "  3. Run: YOUTUBE_API_KEY=<key> uv run python scripts/audit_live_descriptions.py\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return YouTubeClient(api_key=api_key)


def audit_channel(client: YouTubeClient, channel_id: str) -> dict[str, Any]:
    """Scan uploads playlist descriptions; returns the report payload."""
    uploads_playlist = client.get_uploads_playlist_id(channel_id)
    if not uploads_playlist:
        logger.error("Could not resolve uploads playlist for channel %s", channel_id)
        sys.exit(2)

    items = client.list_playlist_items(uploads_playlist)
    video_ids = []
    for entry in items:
        video_id = entry.get("contentDetails", {}).get("videoUploadId") or entry.get(
            "contentDetails", {}
        ).get("videoId")
        if video_id:
            video_ids.append(video_id)
    logger.info("Playlist %s: %d uploads to inspect.", uploads_playlist, len(video_ids))

    snippets = client.get_video_snippets(video_ids)

    flagged: list[dict[str, object]] = []
    for video_id in video_ids:
        snippet = snippets.get(video_id)
        if snippet is None:
            continue
        reasons = []
        if DEAD_TRANSCRIPT_PATTERN in snippet.description:
            reasons.append("dead_transcript_link")
        if RESOURCES_BLOCK_PATTERN in snippet.description:
            reasons.append("resources_and_transcript_block")
        if reasons:
            flagged.append({"video_id": video_id, "title": snippet.title, "reasons": reasons})

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channel_id": channel_id,
        "uploads_playlist": uploads_playlist,
        "videos_scanned": len(snippets),
        "flagged_count": len(flagged),
        "flagged": flagged,
        "patterns": {
            "dead_transcript_link": DEAD_TRANSCRIPT_PATTERN,
            "resources_and_transcript_block": RESOURCES_BLOCK_PATTERN,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channel", default=DEFAULT_CHANNEL_ID, help="Channel ID to audit")
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT, help="Report JSON output path"
    )
    args = parser.parse_args()

    client = build_client()
    report = audit_channel(client, args.channel)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Scanned {report['videos_scanned']} videos; {report['flagged_count']} flagged.")
    for entry in report["flagged"][:20]:
        print(f"  {entry['video_id']}  {entry['title']}  {', '.join(entry['reasons'])}")
    if len(report["flagged"]) > 20:
        print(f"  ... and {len(report['flagged']) - 20} more (see {args.report})")
    print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
