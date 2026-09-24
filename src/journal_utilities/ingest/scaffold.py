"""Per-item metadata.json scaffolds for new channel videos.

Consumes the worklist from :mod:`journal_utilities.ingest.enumerate` and
emits one scaffold per new item under the journal's
``data/video/activeinferenceinstitute/<Series>/<Series_NNN>/`` layout
(SCHEMA.md conventions: core keys ``series, item, source, channel`` +
``parts[]`` with ``video_id, url, title``; ``duration``/``upload_date`` where
known).

Scaffold-only semantics (never overwrite):
- An existing ``metadata.json`` is never touched — the scaffolder only mints
  files for items that do not exist yet.
- ``transcript_kind: "youtube"`` — placeholders marking that the canonical
  transcript still comes from YouTube captions until WhisperX runs.
- Premieres/upcoming broadcasts get ``status: "scheduled"`` so the journal
  pipeline knows the item exists before its public date.
- Series/item naming reuses the categorizer so scaffolds match INDEX rows
  produced by ``generate_journal_indexes.py``.

Dry-run is the default: ``--no-dry-run`` is required before anything touches
disk.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from journal_utilities.ingest.enumerate import ChannelVideo
from journal_utilities.youtube.categorizer import categorize_name

logger = logging.getLogger(__name__)

#: Journal source root, relative to the journal checkout (A003 conventions).
SRC_PREFIX = Path("data/video/activeinferenceinstitute")


def _part_slug(title: str, max_length: int = 60) -> str:
    """Filesystem-safe slug of a title (mirrors renderer.slugify)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_length].strip("-") or "untitled"


@dataclass
class ScaffoldPlan:
    """One planned scaffold: destination path + the metadata payload."""

    journal: Path
    relative_dir: Path
    metadata: dict[str, Any]

    @property
    def metadata_path(self) -> Path:
        return self.journal / self.relative_dir / "metadata.json"

    @property
    def exists(self) -> bool:
        return self.metadata_path.is_file()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative_dir.as_posix(),
            "exists": self.exists,
            "metadata": self.metadata,
        }


@dataclass
class ScaffoldReport:
    """Outcome of a scaffold run (planned vs written vs skipped)."""

    journal: Path
    dry_run: bool = True
    planned: list[ScaffoldPlan] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    skipped_existing: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        mode = "dry-run" if self.dry_run else "applied"
        return (
            f"scaffold [{mode}]: {len(self.planned)} planned, "
            f"{len(self.written)} written, {len(self.skipped_existing)} skipped-existing"
        )


def _classify(video: ChannelVideo) -> tuple[str | None, str | None, str | None]:
    """Categorize a video title into (category, series, episode)."""
    return categorize_name(video.title, is_unique_event_name=False)


def _infer_series_and_item(
    video: ChannelVideo,
) -> tuple[str, str, str | None, str | None]:
    """Derive (series, item, category, episode) folder names for a video.

    Falls back to a dateless slug item under ``Other`` when no stream pattern
    matches — mirrors the journal's existing "Other" series convention.
    """
    category, series, episode = _classify(video)
    if series:
        # Numbered streams: series dir is the bare category ("GuestStream"),
        # item is the counter name ("GuestStream_141") — matches INDEX rows.
        # Textbook categories carry a slash root ("TextbookGroup/Namjoshi2026/
        # Cohort_1"); the series dir collapses it to a single folder segment.
        if category and "/" in category:
            root = category.rsplit("/", 1)[0].replace("/", "_")
            return root, series, category, episode
        return category or "Other", series, category, episode
    return "Other", _part_slug(video.title), category, episode


def _dedupe_item_name(series: str, item: str, journal: Path, taken: set[str]) -> str:
    """Return ``item``, or a ``_2``/``_3``… suffix if that item is already used.

    ``taken`` holds relative item dirs planned earlier in the same run, so two
    distinct videos with the same slug never merge into one item directory.
    """
    base_dir = journal / SRC_PREFIX / series
    candidate = item
    counter = 2
    while (
        (base_dir / candidate).is_dir()
        or (base_dir / candidate / "metadata.json").is_file()
        or (SRC_PREFIX / series / candidate).as_posix() in taken
    ):
        candidate = f"{item}_{counter}"
        counter += 1
    return candidate


def build_scaffold(
    video: ChannelVideo,
    series: str,
    item: str,
    category: str | None = None,
    episode: str | None = None,
) -> dict[str, Any]:
    """Build the canonical metadata payload for one new item.

    Matches the journal's metadata.json core keys (docs/SCHEMA.md:
    series/item/source/channel/category/episode + parts[]); the
    ingest-specific additions are ``status`` (``scheduled`` for premieres)
    and ``transcript_kind: "youtube"`` placeholders.
    """
    part: dict[str, Any] = {
        "video_id": video.video_id,
        "url": video.url,
        "title": video.title,
        "transcript_kind": "youtube",
    }
    if video.published_date:
        part["published"] = video.published_date
    if video.duration_seconds is not None:
        part["duration"] = video.duration_seconds

    scaffold: dict[str, Any] = {
        "series": series,
        "item": item,
        "source": "youtube",
        "channel": "ActiveInferenceInstitute",
        "category": category or series.split("_")[0],
        "title": video.title,
        "status": "scheduled" if video.is_scheduled else "published",
        "transcript_kind": "youtube",
        "parts": [part],
    }
    if episode:
        scaffold["episode"] = episode
    return scaffold


def plan_scaffolds(
    videos: list[ChannelVideo],
    journal: Path,
    *,
    skip_existing: bool = True,
) -> list[ScaffoldPlan]:
    """Plan one scaffold per video; optionally skip items that already exist.

    No filesystem writes here — callers decide (dry-run default).
    """
    plans: list[ScaffoldPlan] = []
    for video in videos:
        series, item, category, episode = _infer_series_and_item(video)
        # The categorizer's item name is canonical for numbered streams
        # (GuestStream_141 etc.) — never renumber with _next_item_name, or a
        # re-run after a gap would clobber canonical episode numbers.
        if series == "Other":
            # Unmatched video: de-duplicate the slug item against both the
            # journal tree and paths planned earlier in this same run, so two
            # distinct videos never merge into one item dir.
            item = _dedupe_item_name(
                series, item, journal, taken={p.relative_dir.as_posix() for p in plans}
            )
        plan = ScaffoldPlan(
            journal=journal,
            relative_dir=SRC_PREFIX / series / item,
            metadata=build_scaffold(video, series, item, category, episode),
        )
        if skip_existing and plan.exists:
            logger.info("Skipping existing item: %s", plan.relative_dir)
            continue
        plans.append(plan)
    return plans


def write_scaffolds(plans: list[ScaffoldPlan], *, dry_run: bool = True) -> ScaffoldReport:
    """Write planned scaffolds to disk unless ``dry_run`` (the default)."""
    report = ScaffoldReport(journal=plans[0].journal if plans else Path("."), dry_run=dry_run)
    report.planned = plans
    for plan in plans:
        if plan.exists:
            report.skipped_existing.append(plan.metadata_path)
            continue
        if dry_run:
            logger.info("[dry-run] would scaffold %s", plan.relative_dir)
            continue
        plan.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        plan.metadata_path.write_text(
            json.dumps(plan.metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report.written.append(plan.metadata_path)
        logger.info("Scaffolded %s", plan.relative_dir)
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI: emit scaffolds for a worklist. Dry-run is the default."""
    parser = argparse.ArgumentParser(
        prog="journal_utilities.ingest.scaffold",
        description=(
            "Emit per-item metadata.json scaffolds for new channel videos "
            "(transcript_kind=youtube placeholders; status=scheduled for premieres)."
        ),
    )
    parser.add_argument("--journal", type=Path, required=True, help="Journal checkout root")
    parser.add_argument(
        "--worklist",
        type=Path,
        help="Worklist JSON from ingest.enumerate (default: read stdin)",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Plan scaffolds even for items whose metadata.json already exists",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually write scaffolds (default: dry-run)",
    )
    parser.set_defaults(dry_run=True, skip_existing=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        raw = args.worklist.read_text(encoding="utf-8") if args.worklist else sys.stdin.read()
        worklist = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read worklist JSON: {exc}") from exc

    new_videos = [
        ChannelVideo(
            video_id=str(entry["video_id"]),
            title=str(entry.get("title") or ""),
            published_at=str(entry.get("published_at") or ""),
            duration_seconds=entry.get("duration_seconds"),
            privacy_status=str(entry.get("privacy_status") or ""),
            upload_status=str(entry.get("upload_status") or ""),
            broadcast_status=str(entry.get("broadcast_status") or ""),
        )
        for entry in worklist.get("new_videos", [])
        if isinstance(entry, dict) and entry.get("video_id")
    ]
    plans = plan_scaffolds(new_videos, args.journal, skip_existing=args.skip_existing)
    report = write_scaffolds(plans, dry_run=args.dry_run)
    for plan in plans:
        state = "exists" if plan.exists else "planned"
        print(f"  {state}: {plan.relative_dir}")
    print(report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
