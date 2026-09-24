"""Channel-vs-manifest-vs-INDEX reconciliation report (quota-free).

Compares three video-id sets and reports every gap:

- **channel** — videos in a saved channel manifest JSON (shape produced by
  ``journal_utilities.youtube.channel.save_channel_manifest``) or a Data API
  worklist (``new_videos``/``channel videos`` key layout from
  :mod:`journal_utilities.ingest.enumerate`); if neither is given, the
  module can enumerate live via the Data API when ``YOUTUBE_API_KEY`` is set.
- **manifest** — the per-video download manifest files under
  ``data/output/`` (``<video_id>.json`` / ``<video_id>.simple.json``).
- **index** — video ids referenced by the journal ``INDEX.json``.

No Data API calls are made unless a live enumeration is explicitly requested,
so this report is safe to run in CI with zero quota. Read-only by definition:
dry-run is the default and there is no ``--no-dry-run`` flag at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Reconciliation:
    """Result of the three-way reconciliation."""

    channel_ids: set[str] = field(default_factory=set)
    manifest_ids: set[str] = field(default_factory=set)
    index_ids: set[str] = field(default_factory=set)
    # video_id -> item paths referencing it (duplicates = len > 1)
    index_id_paths: dict[str, list[str]] = field(default_factory=dict)

    @property
    def in_channel_not_manifest(self) -> set[str]:
        return self.channel_ids - self.manifest_ids

    @property
    def in_channel_not_index(self) -> set[str]:
        return self.channel_ids - self.index_ids

    @property
    def in_manifest_not_channel(self) -> set[str]:
        return self.manifest_ids - self.channel_ids

    @property
    def in_manifest_not_index(self) -> set[str]:
        return self.manifest_ids - self.index_ids

    @property
    def in_index_not_channel(self) -> set[str]:
        """Ids the journal references but the channel does not list."""
        return self.index_ids - self.channel_ids

    @property
    def duplicate_video_ids(self) -> dict[str, list[str]]:
        """INDEX ids referenced by >1 canonical item (validate_journal errors).

        Paths annotated ``[duplicate_of]`` are legitimate mirrors and don't
        count; the raw lists stay in ``index_id_paths`` for the report.
        """
        return {
            video_id: paths
            for video_id, paths in self.index_id_paths.items()
            if sum(1 for p in paths if "[duplicate_of]" not in p) > 1
        }

    @property
    def fully_reconciled(self) -> bool:
        return (
            self.channel_ids == self.manifest_ids == self.index_ids and not self.duplicate_video_ids
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": {
                "channel": len(self.channel_ids),
                "manifest": len(self.manifest_ids),
                "index": len(self.index_ids),
                "channel_not_manifest": len(self.in_channel_not_manifest),
                "channel_not_index": len(self.in_channel_not_index),
                "manifest_not_channel": len(self.in_manifest_not_channel),
                "manifest_not_index": len(self.in_manifest_not_index),
                "index_not_channel": len(self.in_index_not_channel),
            },
            "reconciled": self.fully_reconciled,
            "duplicate_video_ids": self.duplicate_video_ids,
            "channel_not_manifest": sorted(self.in_channel_not_manifest),
            "channel_not_index": sorted(self.in_channel_not_index),
            "manifest_not_channel": sorted(self.in_manifest_not_channel),
            "manifest_not_index": sorted(self.in_manifest_not_index),
            "index_not_channel": sorted(self.in_index_not_channel),
        }


def load_index_item_paths(index_path: Path) -> dict[str, list[str]]:
    """Map every INDEX video id to the item paths referencing it.

    ``validate_journal`` errors on the same video id appearing in multiple
    *canonical* items; per-talk uploads canonical via ``sessions[].video_id``
    and ``duplicate_of`` mirrors are legitimate. Items carrying
    ``duplicate_of`` are annotated in the path list rather than counted as
    hard duplicates (the reconciled gate only fires on unannotated dupes).
    """
    try:
        payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read INDEX.json at {index_path}: {exc}") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise SystemExit(f"INDEX.json at {index_path} has no items list")
    ids: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("path", "<no-path>"))
        parts = item.get("parts")
        if not isinstance(parts, list):
            continue
        is_duplicate_of = bool(item.get("duplicate_of"))
        for part in parts:
            video_id = (
                part
                if isinstance(part, str)
                else part.get("video_id")
                if isinstance(part, dict)
                else None
            )
            if isinstance(video_id, str) and video_id.strip():
                entry = f"{item_path} [duplicate_of]" if is_duplicate_of else item_path
                ids.setdefault(video_id, []).append(entry)
    return ids


def _ids_from_channel_source(payload: dict[str, Any]) -> set[str]:
    """Extract video ids from a channel manifest or worklist JSON."""
    videos = payload.get("videos")
    if isinstance(videos, list):  # channel manifest shape
        return {
            str(v["id"])
            for v in videos
            if isinstance(v, dict) and isinstance(v.get("id"), str) and v["id"].strip()
        }
    new_videos = payload.get("new_videos")
    if isinstance(new_videos, list):  # worklist shape
        return {
            str(v["video_id"])
            for v in new_videos
            if isinstance(v, dict) and isinstance(v.get("video_id"), str) and v["video_id"].strip()
        }
    return set()


def load_channel_ids(path: Path) -> set[str]:
    """Load channel video ids from a saved manifest or worklist JSON."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot read channel source %s: %s", path, exc)
        return set()
    if not isinstance(payload, dict):
        return set()
    return _ids_from_channel_source(payload)


def load_manifest_ids(data_dir: Path) -> set[str]:
    """Collect video ids from per-video download manifests in ``data_dir``.

    A video counts as present when ``<id>.json`` exists (the downloader's
    full-metadata artifact); ``.simple.json`` companions are ignored because
    they always accompany the full file.
    """
    root = Path(data_dir)
    if not root.is_dir():
        return set()
    return {
        path.name[: -len(".json")]
        for path in root.glob("*.json")
        if not path.name.endswith(".simple.json")
    }


def build_reconciliation(
    channel_ids: set[str],
    manifest_ids: set[str],
    index_ids: set[str],
    index_id_paths: dict[str, list[str]] | None = None,
) -> Reconciliation:
    """Assemble the reconciliation from three id sets (pure, no I/O)."""
    return Reconciliation(
        channel_ids=set(channel_ids),
        manifest_ids=set(manifest_ids),
        index_ids=set(index_ids),
        index_id_paths=index_id_paths or {},
    )


def render_text_report(recon: Reconciliation) -> str:
    """Render a human-readable report block (CI log friendly)."""
    data = recon.to_dict()
    lines = [
        "=== Channel-vs-manifest-vs-INDEX reconciliation ===",
        f"channel videos:    {data['counts']['channel']}",
        f"manifest videos:   {data['counts']['manifest']}",
        f"index video ids:   {data['counts']['index']}",
        f"channel→manifest gaps: {data['counts']['channel_not_manifest']}",
        f"channel→INDEX gaps:    {data['counts']['channel_not_index']}",
        f"manifest→channel gaps: {data['counts']['manifest_not_channel']}",
        f"manifest→INDEX gaps:   {data['counts']['manifest_not_index']}",
        f"INDEX→channel (extra in journal): {data['counts']['index_not_channel']}",
        f"reconciled: {data['reconciled']}",
    ]
    for label, ids in (
        ("in channel, missing from manifest", data["channel_not_manifest"]),
        ("in channel, missing from INDEX", data["channel_not_index"]),
        ("in manifest, missing from channel", data["manifest_not_channel"]),
        ("in manifest, missing from INDEX", data["manifest_not_index"]),
        ("in INDEX but not on channel (renamed/removed/duplicate_of)", data["index_not_channel"]),
    ):
        if ids:
            lines.append(f"  {label} ({len(ids)}):")
            for video_id in ids:
                lines.append(f"    {video_id}")
    duplicates = data["duplicate_video_ids"]
    if duplicates:
        lines.append(f"INDEX duplicate video ids: {len(duplicates)}")
        for video_id, paths in duplicates.items():
            lines.append(f"    {video_id} -> {', '.join(paths)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: reconciliation report. Read-only — no writes, no quota by default."""
    parser = argparse.ArgumentParser(
        prog="journal_utilities.ingest.diff",
        description=(
            "Reconcile the channel manifest vs per-video download manifests "
            "vs journal INDEX.json. Quota-free and read-only."
        ),
    )
    parser.add_argument("--journal", type=Path, required=True, help="Journal checkout root")
    parser.add_argument(
        "--channel-manifest",
        type=Path,
        help=(
            "Saved channel manifest (channel_videos.json) or Data API worklist "
            "JSON. Omit to load nothing (index-vs-manifest only) — live "
            "enumeration requires YOUTUBE_API_KEY via ingest.enumerate."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory of per-video download manifests (default: <journal>/data/output)",
    )
    parser.add_argument("--output", type=Path, help="Write the JSON report here")
    parser.add_argument("--api-key", default=None, help="Defaults to $YOUTUBE_API_KEY")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    index_paths = load_index_item_paths(args.journal / "INDEX.json")
    index_ids = set(index_paths)
    if not index_ids:
        raise SystemExit(
            f"No video ids could be read from {args.journal / 'INDEX.json'} — "
            "refusing to reconcile against an empty index. Check --journal."
        )

    channel_ids: set[str] = set()
    if args.channel_manifest is not None:
        channel_ids = load_channel_ids(args.channel_manifest)
        if not channel_ids:
            raise SystemExit(
                f"No video ids could be read from {args.channel_manifest} — a broken "
                "or wrong-shaped channel manifest would fake full reconciliation. "
                "Check the path (expects channel_videos.json or a worklist JSON)."
            )

    data_dir = args.data_dir or (args.journal / "data" / "output")
    manifest_ids = load_manifest_ids(data_dir)

    recon = build_reconciliation(channel_ids, manifest_ids, index_ids, index_paths)
    print(render_text_report(recon))

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(recon.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote report to {args.output}")

    # Nonzero exit flags unresolved gaps for CI; `--lenient` would downgrade,
    # but the handoff wants the gate strict by default.
    return 0 if recon.fully_reconciled else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
