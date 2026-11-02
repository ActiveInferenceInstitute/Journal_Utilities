#!/usr/bin/env python3
"""
Fetch YouTube chapter lists (timestamped video descriptions) for every channel
video and cache them to data/input/video_chapters.json.

Chapters are the upstream source of truth for the journal's ``sessions[]``
seed data — see enrich_metadata.py. Incremental: already-fetched video ids
are skipped, so reruns only pull new videos. Videos without chapters are
cached as [] to avoid refetching.

Usage:
    python scripts/fetch_chapters.py              # fetch all missing
    python scripts/fetch_chapters.py --limit 20   # bounded run
"""

import argparse
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "data/output/channel_videos.json"
CACHE = REPO / "data/input/video_chapters.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch_chapters")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="max videos to fetch this run")
    args = parser.parse_args()

    import yt_dlp

    videos = json.loads(MANIFEST.read_text(encoding="utf-8")).get("videos", [])
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [v for v in videos if v.get("id") and v["id"] not in cache]
    if args.limit:
        todo = todo[: args.limit]
    logger.info("%d cached, %d to fetch", len(cache), len(todo))

    # sleep_interval_requests keeps us under YouTube's metadata rate limit;
    # a full-channel sweep without it gets blocked partway ("try again later").
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "sleep_interval_requests": 2,
    }
    fetched = failed = 0
    with yt_dlp.YoutubeDL(opts) as ydl:
        for i, video in enumerate(todo, 1):
            vid = video["id"]
            try:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
                chapters = [
                    {
                        "start": float(c.get("start_time") or 0),
                        "title": (c.get("title") or "").strip(),
                    }
                    for c in (info.get("chapters") or [])
                ]
                cache[vid] = chapters
                fetched += 1
                if chapters:
                    logger.info("[%d/%d] %s: %d chapters", i, len(todo), vid, len(chapters))
            except Exception as exc:  # noqa: BLE001 — private/removed videos etc.
                logger.warning("[%d/%d] %s failed: %s", i, len(todo), vid, exc)
                failed += 1
            if fetched and fetched % 25 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False) + "\n", encoding="utf-8")

    CACHE.write_text(json.dumps(cache, ensure_ascii=False) + "\n", encoding="utf-8")
    with_chapters = sum(1 for c in cache.values() if c)
    logger.info(
        "done: %d fetched, %d failed; cache %d videos (%d with chapters)",
        fetched,
        failed,
        len(cache),
        with_chapters,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
