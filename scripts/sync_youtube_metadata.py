#!/usr/bin/env python3
"""Closed-loop YouTube metadata synchronizer.

Dry-run by default; live writes require ``--apply`` AND a live snippet fetched
from the Data API in the same run (pipeline Rule 1):

- The yt-dlp/manifest fallback is gone: if ``videos.list`` fails or the video
  is unknown, the script refuses to write (a fallback write erased abstracts
  and credits on 2026-08 batch, see handoff Y3).
- A backup of the live snippet is written to
  ``data/output/yt_backup/<video_id>/<timestamp>.json`` before every write.
- ``--quota-budget`` accounts every Data API call (videos.update=50,
  captions.insert=400, playlistItems.insert=50, list=1); the batch stops when
  the budget is exhausted instead of guessing.

Transcript links resolve via the journal ``INDEX.json`` items[].parts — never
the dead ``blob/main/transcripts/<id>.md`` pattern (Y1/E1/I1). ``has_transcript``
comes from the INDEX, not local files.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from journal_utilities.youtube.client import QuotaLedger, VideoSnippet, YouTubeClient

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CHANNEL_VIDEOS = DATA_DIR / "output/channel_videos.json"
CHAPTERS_FILE = DATA_DIR / "input/video_chapters.json"
BACKUP_DIR = DATA_DIR / "output/yt_backup"
DEFAULT_JOURNAL = REPO_ROOT.parent / "ActiveInferenceJournal"
DEFAULT_BUDGET = 10_000

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sync_youtube_metadata")


def derive_video_tags(raw_title: str, existing_tags: list[str] | None = None) -> list[str]:
    tags_set = set(existing_tags or [])
    tags_set.update(
        ["Active Inference", "Active Inference Institute", "Neuroscience", "Free Energy Principle"]
    )
    title_lower = raw_title.lower()
    if "livestream" in title_lower:
        tags_set.add("Active Inference Livestream")
    if "gueststream" in title_lower:
        tags_set.add("GuestStream")
    if "modelstream" in title_lower:
        tags_set.add("ModelStream")
    if "mathstream" in title_lower:
        tags_set.add("MathStream")
    if "symposium" in title_lower:
        tags_set.add("Symposium")
    if "textbook" in title_lower:
        tags_set.add("Textbook Group")

    sorted_tags = sorted(tags_set)
    final_tags = []
    total_len = 0
    for t in sorted_tags:
        if total_len + len(t) + 1 <= 480:
            final_tags.append(t)
            total_len += len(t) + 1
    return final_tags


@dataclass
class SyncContext:
    """Everything the per-video sync needs beyond the client."""

    client: YouTubeClient
    ledger: QuotaLedger
    item_index: dict[str, dict[str, Any]]  # video_id -> INDEX.json item record
    chapters_map: dict[str, list[dict[str, Any]]]
    apply: bool
    verify: bool
    chapter_gen: Any | None = None
    api_fetched: set[str] = field(default_factory=set)
    backup_dir: Path = BACKUP_DIR


def load_json(path: Path) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        logger.warning("Error loading %s: %s", path, exc)
        return {}


def load_journal_index(journal_dir: Path) -> dict[str, dict[str, Any]]:
    """Load INDEX.json and build the video_id -> item map (mandatory input)."""
    index_path = journal_dir / "INDEX.json"
    if not index_path.is_file():
        logger.error(
            "INDEX.json not found at %s — refusing to run: transcript links must "
            "resolve against the journal INDEX (pass --journal).",
            index_path,
        )
        sys.exit(1)
    from journal_utilities.youtube.metadata_formatter import build_video_item_index

    items: list[dict[str, Any]] = load_json(index_path).get("items", [])
    index: dict[str, dict[str, Any]] = build_video_item_index(items)
    return index


def backup_snippet(video_id: str, snippet: VideoSnippet, backup_dir: Path = BACKUP_DIR) -> Path:
    """Write the pre-update backup required by Rule 1; returns the file path."""
    from dataclasses import asdict

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / video_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{timestamp}.json"
    payload = {"backed_up_at": timestamp, "video_id": video_id, "snippet": asdict(snippet)}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Backed up live snippet for %s -> %s", video_id, path)
    return path


def build_target_description(
    video_id: str,
    base_description: str,
    ctx: SyncContext,
) -> str:
    """Assemble the new description; transcript URL resolves via INDEX only."""
    from journal_utilities.youtube.metadata_formatter import (
        assemble_video_description,
        resolve_video_journal_url,
    )

    item = ctx.item_index.get(video_id)
    transcript_url = None
    if item is not None:
        transcript_url = resolve_video_journal_url(video_id, ctx.item_index)
    else:
        logger.warning(
            "%s is not in journal INDEX.json items[].parts — no transcript link "
            "will be emitted (never guess one).",
            video_id,
        )

    chapters: list[dict[str, Any]] = ctx.chapters_map.get(video_id, [])
    new_description: str = assemble_video_description(
        base_description=base_description,
        chapters=chapters,
        github_transcript_url=transcript_url,
    )
    return new_description


def sync_videos(ctx: SyncContext, targets: list[dict]) -> int:
    """Run the pull-assemble-push loop. Returns the number of live updates."""
    from journal_utilities.youtube.client import QuotaBudgetExceededError
    from journal_utilities.youtube.metadata_formatter import CHAPTERS_MARKER_END

    updated_count = 0
    for i, v in enumerate(targets, 1):
        vid = v.get("id")
        if not vid:
            continue

        # ---------------------------------------------------------- 1. PULL
        # Rule 1(a): the live snippet MUST come from the Data API in this
        # run. A failed read means no write, no preview built from fallback
        # data, no exceptions swallowed into a wipe.
        if not ctx.ledger.can_spend("videos.list"):
            logger.error("Quota budget exhausted before reading %s; stopping.", vid)
            break
        try:
            ctx.ledger.spend("videos.list")
        except QuotaBudgetExceededError as exc:
            logger.error("Quota budget exhausted: %s", exc)
            break
        live_snippet = ctx.client.get_video_snippet(vid)
        if live_snippet is None:
            logger.error(
                "[%d/%d] %s: no Data API snippet (fetch failed or video absent) — "
                "refusing to write. No fallback is used (Rule 1).",
                i,
                len(targets),
                vid,
            )
            continue
        ctx.api_fetched.add(vid)

        raw_title = live_snippet.title or v.get("title", "")
        existing_tags = live_snippet.tags or v.get("tags", [])
        raw_desc = live_snippet.description

        # ------------------------------------------------ 2. CHAPTERS/TRANSCRIPT
        chapters = ctx.chapters_map.get(vid, [])
        transcript_json_path = DATA_DIR / "output/transcripts" / f"{vid}.json"
        if not chapters and transcript_json_path.is_file() and ctx.chapter_gen is not None:
            logger.info("[%d/%d] Generating LLM chapters for %s...", i, len(targets), vid)
            try:
                segments = json.loads(transcript_json_path.read_text(encoding="utf-8"))
                chapters = ctx.chapter_gen.generate_chapters(
                    title=raw_title, transcript_segments=segments
                )
                if chapters:
                    logger.info("Generated %d chapters for %s", len(chapters), vid)
                    ctx.chapters_map[vid] = [{"start": c.start, "title": c.title} for c in chapters]
            except Exception as exc:
                logger.warning("LLM chapter generation failed for %s: %s", vid, exc)

        new_description = build_target_description(vid, raw_desc, ctx)
        new_tags = derive_video_tags(raw_title, existing_tags)

        from journal_utilities.youtube.client import VideoSnippet

        snippet = VideoSnippet(
            video_id=vid,
            title=raw_title,
            description=new_description,
            category_id=live_snippet.category_id,
            tags=new_tags,
        )

        logger.info(
            "[%d/%d] %s — chapters: %d, tags: %d, mode: %s",
            i,
            len(targets),
            vid,
            len(chapters),
            len(new_tags),
            "APPLY" if ctx.apply else "dry-run",
        )

        if not ctx.apply:
            print(f"=================== DRY RUN PREVIEW: {vid} ===================")
            print(f"Title: {snippet.title}")
            print(f"Tags ({len(snippet.tags)}): {', '.join(snippet.tags)}")
            print("--- CURRENT (live) DESCRIPTION ---")
            print(raw_desc)
            print("--- PROPOSED DESCRIPTION ---")
            print(snippet.description)
            print(
                f"(on --apply, the live description is backed up to {ctx.backup_dir / vid}/<timestamp>.json)"
            )
            print("==============================================================")
            continue

        # --------------------------------------------------------- 3. PUSH
        # Rule 1(b): backup before every write. Rule 1 guard: only snippets
        # fetched via the Data API in this run may be written.
        assert vid in ctx.api_fetched
        if not ctx.ledger.can_spend("videos.update"):
            logger.error("Quota budget exhausted before updating %s; stopping.", vid)
            break
        backup_snippet(vid, live_snippet, backup_dir=ctx.backup_dir)
        try:
            ctx.ledger.spend("videos.update")
        except QuotaBudgetExceededError as exc:
            logger.error("Quota budget exhausted: %s", exc)
            break
        result = ctx.client.update_video_snippet(snippet, dry_run=False)
        if not result.success:
            logger.error("Failed update for %s: %s", vid, result.error)
            continue
        updated_count += 1

        # ------------------------------------------------------ 4. VERIFY
        if ctx.verify:
            time.sleep(5)
            logger.info("Verifying update on YouTube for %s...", vid)
            try:
                ctx.ledger.spend("videos.list")
                verified = ctx.client.get_video_snippet(vid)
                if verified and CHAPTERS_MARKER_END in verified.description:
                    logger.info("Verification PASSED for %s", vid)
                else:
                    logger.warning("Verification check inconclusive for %s", vid)
            except Exception as exc:
                logger.warning("Verification read failed for %s: %s", vid, exc)

    return updated_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize YouTube video metadata")
    parser.add_argument("--video-id", type=str, help="Single YouTube video ID to process")
    parser.add_argument("--limit", type=int, default=0, help="Max videos to process (0 = all)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates live (default is dry-run; writes also require a "
        "Data API-fetched snippet in this run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Deprecated no-op: dry-run is already the default (kept for older callers)",
    )
    parser.add_argument(
        "--journal", type=Path, default=DEFAULT_JOURNAL, help="ActiveInferenceJournal checkout"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Re-fetch metadata from YouTube after update to verify",
    )
    parser.add_argument(
        "--quota-budget",
        type=int,
        default=DEFAULT_BUDGET,
        help="Daily quota units this run may spend",
    )
    parser.add_argument(
        "--llm-backend",
        choices=["none", "ollama", "openrouter"],
        default="none",
        help="LLM backend to generate chapters from transcript JSON if missing",
    )
    parser.add_argument(
        "--llm-model", type=str, default=None, help="Model override for LLM chapter generation"
    )
    args = parser.parse_args()

    from journal_utilities.youtube.client import QuotaLedger, YouTubeClient

    client = YouTubeClient(
        api_key=os.environ.get("YOUTUBE_API_KEY"),
        client_secrets_path=os.environ.get("YOUTUBE_CLIENT_SECRETS"),
        token_path=os.environ.get("YOUTUBE_TOKEN_PATH"),
    )
    item_index = load_journal_index(args.journal)
    ledger = QuotaLedger(budget=args.quota_budget)

    videos: list[dict] = []
    if CHANNEL_VIDEOS.is_file():
        videos = load_json(CHANNEL_VIDEOS).get("videos", [])

    chapters_map: dict[str, list] = load_json(CHAPTERS_FILE)
    if not isinstance(chapters_map, dict):
        chapters_map = {}

    if args.video_id:
        targets = [v for v in videos if v.get("id") == args.video_id]
        if not targets:
            targets = [{"id": args.video_id, "title": f"Video {args.video_id}"}]
    else:
        targets = videos
    if args.limit > 0:
        targets = targets[: args.limit]

    logger.info("Found %d target video(s) to evaluate.", len(targets))

    chapter_gen = None
    if args.llm_backend != "none":
        from journal_utilities.youtube.chapter_generator import ChapterGenerator

        chapter_gen = ChapterGenerator(backend=args.llm_backend, model=args.llm_model)

    ctx = SyncContext(
        client=client,
        ledger=ledger,
        item_index=item_index,
        chapters_map=chapters_map,
        apply=args.apply,
        verify=args.verify and args.apply,
        chapter_gen=chapter_gen,
    )
    updated = sync_videos(ctx, targets)
    logger.info(
        "Completed: %d live update(s); quota spent %d/%d units.",
        updated,
        ledger.spent,
        ledger.budget,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
