#!/usr/bin/env python3
"""Rank English caption candidates from Journal transcripts and known view counts.

The CSV is a review artifact. Live channel and track checks belong to the
separate caption upload command.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from journal_utilities.youtube.captions import load_blocks, segments_for_video

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JOURNAL = REPO_ROOT.parent / "ActiveInferenceJournal"
CHANNEL_VIDEOS = REPO_ROOT / "data/output/channel_videos.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("captions_worklist")

PRIORITY_INSIGHTS = 1
PRIORITY_MODELSTREAM = 2
PRIORITY_TOP_VIEWS = 3
PRIORITY_REST = 4
TOP_VIEW_LIMIT = 100

PRIORITY_NAMES = {
    PRIORITY_INSIGHTS: "insights",
    PRIORITY_MODELSTREAM: "modelstream-001",
    PRIORITY_TOP_VIEWS: "top-views",
    PRIORITY_REST: "rest",
}


def load_json(path: Path) -> Any:  # noqa: ANN401
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def has_existing_srt(item_dir: Path) -> bool:
    """Report a local caption artifact independently of upload eligibility."""
    cap_dir = item_dir / "captions"
    if not cap_dir.is_dir():
        return False
    return any(p.suffix == ".srt" for p in cap_dir.iterdir() if p.is_file())


def classify(series: str, item: str, views: int | None, transcript: bool) -> int:
    """Assign an initial priority. Known views are meaningful with a transcript."""
    if not transcript:
        return PRIORITY_REST
    if series == "Insights":
        return PRIORITY_INSIGHTS
    if series == "ModelStream" and item == "ModelStream_001":
        return PRIORITY_MODELSTREAM
    if views is not None:
        return PRIORITY_TOP_VIEWS
    return PRIORITY_REST


def _rank(row: dict[str, Any]) -> tuple[int, int, str, str, str]:
    views = row["views"]
    return (
        row["priority"],
        -views if isinstance(views, int) else 1,
        row["series"],
        row["item"],
        row["video_id"],
    )


def build_worklist(journal_dir: Path, views_map: dict[str, int] | None) -> list[dict[str, Any]]:
    """One ranked row per video part across the journal INDEX."""
    journal_dir = journal_dir.resolve()
    index_path = journal_dir / "INDEX.json"
    data = load_json(index_path)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        logger.error("INDEX.json not found or unreadable at %s", index_path)
        return []
    rows: list[dict[str, Any]] = []
    views_by_video = views_map or {}
    for item in data["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        item_dir = (journal_dir / item["path"]).resolve()
        if item_dir == journal_dir or not item_dir.is_relative_to(journal_dir):
            continue
        series = str(item.get("series", ""))
        item_name = str(item.get("item", ""))
        blocks = load_blocks(item_dir / "transcript.json")
        existing_srt = has_existing_srt(item_dir)
        for vid in item.get("parts") or []:
            if not isinstance(vid, str) or not vid:
                continue
            views = views_by_video.get(vid)
            transcript_ok = bool(segments_for_video(blocks, vid))
            priority = classify(series, item_name, views, transcript_ok)
            rows.append(
                {
                    "priority": priority,
                    "priority_name": PRIORITY_NAMES[priority],
                    "series": series,
                    "item": item_name,
                    "video_id": vid,
                    "views": "" if views is None else views,
                    "transcript": str(transcript_ok).lower(),
                    "existing_srt": str(existing_srt).lower(),
                    "srt_available": str(transcript_ok).lower(),
                    "item_path": item["path"],
                }
            )
    rows.sort(key=_rank)
    top_view_rows = [row for row in rows if row["priority"] == PRIORITY_TOP_VIEWS]
    for row in top_view_rows[TOP_VIEW_LIMIT:]:
        row.update(priority=PRIORITY_REST, priority_name=PRIORITY_NAMES[PRIORITY_REST])
    rows.sort(key=_rank)
    return rows


def load_views_map(channel_videos_path: Path) -> dict[str, int]:
    """video_id -> view_count from the channel manifest (0 when unknown).

    The enumerated manifest typically lacks ``view_count`` (yt-dlp
    ``--flat-playlist``); rows then rank inside their bucket by series/item and
    ``views`` is emitted empty. A Data-API-refreshed manifest fills it.
    """
    data = load_json(channel_videos_path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for v in data.get("videos") or []:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        views = v.get("view_count")
        if isinstance(views, int) and not isinstance(views, bool) and views >= 0:
            out[str(v["id"])] = views
    return out


def fetch_views(journal_dir: Path, views_map: dict[str, int], cache_path: Path) -> dict[str, int]:
    """Fill ``views_map`` from the Data API, caching results on disk.

    videos.list is 1 unit per call regardless of size (up to 50 ids), so
    ~740 videos cost ~15 calls once; the cache makes every repeat run
    free. Read-only: an API key suffices, no OAuth, no writes to YouTube.
    """
    cached: dict[str, int] = {}
    if cache_path.is_file():
        cached = load_json(cache_path) or {}
        if not isinstance(cached, dict):
            cached = {}
    merged: dict[str, int] = dict(views_map)
    merged.update({k: int(v) for k, v in cached.items() if isinstance(v, int)})

    index = load_json(journal_dir / "INDEX.json") or {}
    ids: list[str] = []
    for item in index.get("items") or []:
        if isinstance(item, dict):
            ids.extend(v for v in item.get("parts") or [] if isinstance(v, str) and v)
    missing = [vid for vid in dict.fromkeys(ids) if vid not in merged]
    if not missing:
        return merged

    try:
        from journal_utilities.youtube.client import YouTubeClient

        client = YouTubeClient(api_key=os.environ.get("YOUTUBE_API_KEY"))
        calls = (len(missing) + 49) // 50
        logger.info("videos.list: %d ids in %d calls (1 unit each)", len(missing), calls)
        for item in client.list_videos(missing, part="statistics"):
            vid = item.get("id")
            views = (item.get("statistics") or {}).get("viewCount")
            if vid and views is not None:
                merged[str(vid)] = int(views)
    except Exception as exc:  # noqa: BLE001 — planning tool: degrade to manifest views
        logger.error("videos.list fetch failed (%s); ranking without new views", exc)
        return merged
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(merged, indent=1, sort_keys=True), encoding="utf-8")
    logger.info("views cache written: %s (%d ids)", cache_path, len(merged))
    return merged


def write_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "priority",
        "priority_name",
        "series",
        "item",
        "video_id",
        "views",
        "transcript",
        "existing_srt",
        "srt_available",
        "item_path",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank journal videos for caption upload (read-only).",
        epilog=(
            "Priority: Insights, ModelStream 001, top 100 remaining by known views, rest. "
            "The upload step re-verifies each row live (skip-if-existing-track); "
            "this CSV is a planning artifact, never a write authority."
        ),
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL, help="Journal checkout")
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data/output/captions_worklist.csv",
        help="CSV output path",
    )
    parser.add_argument(
        "--channel-videos",
        type=Path,
        default=CHANNEL_VIDEOS,
        help="Channel manifest for view counts (optional, heuristic)",
    )
    parser.add_argument(
        "--fetch-views",
        action="store_true",
        help=(
            "Fetch view counts via Data API videos.list (1 unit per call, "
            "50 ids per call, read-only API key suffices; handoff rule 10: "
            "Data API only, never yt-dlp). Results cached at --views-cache "
            "so repeat ranking runs cost 0 units."
        ),
    )
    parser.add_argument(
        "--views-cache",
        type=Path,
        default=REPO_ROOT / "data/output/captions_views_cache.json",
        help="JSON cache for --fetch-views (video_id -> viewCount)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Emit only the first N rows (0 = all)")
    args = parser.parse_args()

    journal_dir = args.journal
    if not (journal_dir / "INDEX.json").is_file():
        parser.error("--journal must name the exact checkout containing INDEX.json")
    views_map = load_views_map(args.channel_videos)
    if args.fetch_views:
        views_map = fetch_views(journal_dir, views_map, args.views_cache)
    rows = build_worklist(journal_dir, views_map)
    if not rows:
        return 1
    if args.limit > 0:
        rows = rows[: args.limit]
    write_csv(rows, args.out)

    derivable = sum(1 for r in rows if r["srt_available"] == "true")
    by_bucket: dict[str, int] = {}
    for r in rows:
        by_bucket[r["priority_name"]] = by_bucket.get(r["priority_name"], 0) + 1
    logger.info(
        "Wrote %d rows to %s (derivable SRTs: %d; buckets: %s)",
        len(rows),
        args.out,
        derivable,
        by_bucket,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
