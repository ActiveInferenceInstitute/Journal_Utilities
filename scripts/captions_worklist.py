#!/usr/bin/env python3
"""Read-only captions worklist: rank videos for the M5 upload pilot.

Priority order from the pipeline handoff (M5, week 3+):

1. **Insights** — the named pilot series.
2. **Top by views** — videos with view data (from the Data API manifest when
   available; falls back to 0 with a ``views=unknown`` marker).
3. **Fundamentals 2026** — Fundamentals of Active Inference sessions
   (TextbookGroup/Namjoshi2026 items, handoff M5 "Fundamentals 2026: optional
   9/28 dual-track").
4. **Rest** — everything else by series then item.

Emits a CSV worklist with one row per video part:

    priority,series,item,video_id,transcript,existing_srt,srt_available,item_path

Read-only: no file is written outside ``--out``; nothing is uploaded, no API
call is made. The upload script (``upload_captions.py``) consumes this CSV and
re-verifies every row against the live channel (skip-if-existing-track) before
any write.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_journal() -> Path:
    """Locate the sibling ActiveInferenceJournal checkout.

    The documented layout is ``../ActiveInferenceJournal``; nested worktree
    checkouts (e.g. ``worktrees/<repo>/<branch>``) put the sibling higher,
    so walk up a bounded number of levels before giving up.
    """
    for parent in REPO_ROOT.parents[:3]:
        candidate = parent / "ActiveInferenceJournal"
        if candidate.is_dir():
            return candidate
    return REPO_ROOT.parent / "ActiveInferenceJournal"


DEFAULT_JOURNAL = _default_journal()
CHANNEL_VIDEOS = REPO_ROOT / "data/output/channel_videos.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("captions_worklist")

PRIORITY_INSIGHTS = 1
PRIORITY_TOP_VIEWS = 2
PRIORITY_FUNDAMENTALS = 3
PRIORITY_REST = 4

PRIORITY_NAMES = {
    PRIORITY_INSIGHTS: "insights",
    PRIORITY_TOP_VIEWS: "top-views",
    PRIORITY_FUNDAMENTALS: "fundamentals-2026",
    PRIORITY_REST: "rest",
}

_NAMJOHOSHI = re.compile(r"Namjoshi2026/")
_FUNDAMENTALS = re.compile(r"Fundamentals", re.IGNORECASE)


def resolve_journal_dir(root: Path) -> Path:
    """Resolve a journal checkout root for the sibling-worktree layout.

    When INDEX.json is absent at ``root`` but present one level down (branch
    checkouts like ``feat-m4-pages/``), use the most recently modified one
    and say so — silently reading a stale branch's INDEX is worse than
    surfacing the choice. Returns ``root`` unchanged when nothing resolves.
    """
    if (root / "INDEX.json").is_file():
        return root
    candidates = sorted(
        (p.parent for p in root.glob("*/INDEX.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        logger.warning(
            "INDEX.json not at %s; using most recent branch checkout %s", root, candidates[0]
        )
        return candidates[0]
    return root


def load_json(path: Path) -> Any:  # noqa: ANN401
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def has_existing_srt(item_dir: Path) -> bool:
    """True when the item already carries a non-translation caption SRT.

    Mirrors the journal layout: derived caption SRTs live under
    ``captions/``; ``Translations/`` holds machine-translated subs derived
    FROM captions, which do not count as existing caption tracks.
    """
    cap_dir = item_dir / "captions"
    if not cap_dir.is_dir():
        return False
    return any(p.suffix == ".srt" for p in cap_dir.iterdir() if p.is_file())


def has_transcript(item_dir: Path) -> bool:
    """True when a whisperx-style ``transcript.json`` exists."""
    tj = item_dir / "transcript.json"
    if not tj.is_file():
        return False
    try:
        data = json.loads(tj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, list) and any(
        isinstance(b, dict) and isinstance(b.get("segments"), list) for b in data
    )


def classify(series: str, item_path: str, views: int | None) -> int:
    """Assign the handoff priority bucket for one item."""
    if series == "Insights":
        return PRIORITY_INSIGHTS
    if views is not None and views > 0:
        return PRIORITY_TOP_VIEWS
    if "TextbookGroup" in item_path and (
        _NAMJOHOSHI.search(item_path) or _FUNDAMENTALS.search(item_path)
    ):
        return PRIORITY_FUNDAMENTALS
    return PRIORITY_REST


def build_worklist(journal_dir: Path, views_map: dict[str, int] | None) -> list[dict[str, Any]]:
    """One ranked row per video part across the journal INDEX."""
    index_path = journal_dir / "INDEX.json"
    data = load_json(index_path)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        logger.error("INDEX.json not found or unreadable at %s", index_path)
        return []
    rows: list[dict[str, Any]] = []
    for item in data["items"]:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        item_dir = journal_dir / item["path"]
        series = str(item.get("series", ""))
        transcript_ok = has_transcript(item_dir)
        existing_srt = has_existing_srt(item_dir)
        views_map = views_map or {}
        for vid in item.get("parts") or []:
            if not isinstance(vid, str) or not vid:
                continue
            views = views_map.get(vid)
            priority = classify(series, item["path"], views)
            rows.append(
                {
                    "priority": priority,
                    "priority_name": PRIORITY_NAMES[priority],
                    "series": series,
                    "item": item.get("item", ""),
                    "video_id": vid,
                    "views": "" if views is None else views,
                    "transcript": str(transcript_ok).lower(),
                    "existing_srt": str(existing_srt).lower(),
                    "srt_available": str(transcript_ok and not existing_srt).lower(),
                    "item_path": item["path"],
                }
            )
    rows.sort(
        key=lambda r: (
            r["priority"],
            -(r["views"] if isinstance(r["views"], int) else 0),
            r["series"],
            r["item"],
            r["video_id"],
        )
    )
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
        if isinstance(views, int) and views > 0:
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
            "Priority: insights > top-views > fundamentals-2026 > rest. "
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

    journal_dir = resolve_journal_dir(args.journal)
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
