"""Secret-free weekly enumeration: yt-dlp channel manifest -> ingest worklist.

The Data API path (:mod:`journal_utilities.ingest.enumerate`) needs
``YOUTUBE_API_KEY``. This module is the secret-free replacement the journal's
weekly-ingest workflow uses, built on the existing yt-dlp enumeration
(:mod:`journal_utilities.youtube.channel`) so no key and no quota are involved.

A flat yt-dlp channel manifest carries id/title/upload_date/duration/description
but not privacy/upload/broadcast status, and flat entries cannot distinguish an
upcoming premiere from a published video. The adapter therefore:

1. takes the flat channel enumeration (one yt-dlp pass, no key);
2. diffs it against the journal ``INDEX.json`` to find **new** videos;
3. resolves every **new** video with one full per-video yt-dlp extraction, which
   does report ``availability`` and ``live_status`` (bounded work: the weekly
   delta, capped by ``--max-new``);
4. records ``"unknown"`` for every field the extractor cannot determine.

Evidence rules (see ``docs/m3-ingest.md``):

- ``scheduled`` requires premiere evidence (``live_status == "is_upcoming"``);
- ``published`` requires availability evidence (``availability`` public or
  unlisted) plus a broadcast state that is explicitly not upcoming;
- anything else is ``unknown``. A field recorded as ``unknown`` can never
  produce ``published``, and no status is ever inferred from the flat pass.

``upload_status`` is **permanently unknown** on this path: yt-dlp has no
equivalent of the Data API's ``status.uploadStatus``. The field stays in the
worklist schema (the API path fills it) and the scaffolder treats it as
unknown, so scheduling relies on ``broadcast_status``.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from journal_utilities.ingest.enumerate import (
    DEFAULT_CHANNEL_ID,
    UNKNOWN,
    ChannelVideo,
    Worklist,
    diff_against_index,
    load_index_video_ids,
)
from journal_utilities.youtube.channel import (
    ChannelManifest,
    VideoInfo,
    enumerate_channel_videos,
    load_channel_manifest,
    save_channel_manifest,
)

logger = logging.getLogger(__name__)

#: yt-dlp ``live_status`` -> Data API ``liveBroadcastContent`` equivalent.
_BROADCAST_BY_LIVE_STATUS = {
    "is_upcoming": "upcoming",
    "is_live": "live",
    "post_live": "none",
    "was_live": "none",
    "not_live": "none",
}

#: Modern browser UA: YouTube 403s plain library requests (see AGENTS.md).
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class VideoDetailRunner(Protocol):
    """Full per-video extraction; ``None`` means "could not determine"."""

    def video_details(self, video_id: str) -> dict[str, Any] | None: ...


@dataclass
class SubprocessYtDlpRunner:
    """Full per-video extraction through the yt-dlp CLI (read-only, no media)."""

    timeout: int = 180
    user_agent: str = _BROWSER_UA

    def video_details(self, video_id: str) -> dict[str, Any] | None:
        """Return yt-dlp's full metadata for one video, or ``None`` on failure."""
        cmd = [
            "yt-dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            "--user-agent",
            self.user_agent,
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("yt-dlp full extraction failed for %s: %s", video_id, exc)
            return None
        if result.returncode != 0:
            logger.warning(
                "yt-dlp full extraction failed for %s (exit %d): %s",
                video_id,
                result.returncode,
                (result.stderr or "").strip()[:200],
            )
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            logger.warning("yt-dlp returned malformed JSON for %s: %s", video_id, exc)
            return None
        return payload if isinstance(payload, dict) else None


@dataclass
class DirectoryVideoDetailRunner:
    """Replay saved full extractions (offline runs, fixtures, CI without network)."""

    directory: Path

    def video_details(self, video_id: str) -> dict[str, Any] | None:
        path = Path(self.directory) / f"{video_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("No usable saved extraction at %s: %s", path, exc)
            return None
        return payload if isinstance(payload, dict) else None


def _entry_field(entry: VideoInfo | dict[str, Any], name: str, default: Any = "") -> Any:  # noqa: ANN401
    """Read a field from a ``VideoInfo`` or a raw manifest dict."""
    if isinstance(entry, dict):
        value = entry.get(name, default)
    else:
        value = getattr(entry, name, default)
    return default if value is None else value


def _date_from_upload_date(value: str) -> str:
    """``YYYYMMDD`` -> ``YYYY-MM-DD``; anything else stays empty (no guessing)."""
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return ""


def _iso_from_epoch(value: Any) -> str:  # noqa: ANN401 — yt-dlp JSON is untyped
    """Unix timestamp -> ISO 8601 UTC (``...Z``); 0/absent/garbage -> empty."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return ""
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _privacy_from_availability(value: Any) -> str:  # noqa: ANN401 — untyped JSON
    """Map yt-dlp ``availability`` to the Data API privacy vocabulary."""
    text = str(value or "").strip()
    if text in {"public", "unlisted", "private"}:
        return text
    return UNKNOWN


def _broadcast_from_live_status(value: Any) -> str:  # noqa: ANN401 — untyped JSON
    """Map yt-dlp ``live_status`` to ``liveBroadcastContent``; else ``unknown``."""
    return _BROADCAST_BY_LIVE_STATUS.get(str(value or "").strip(), UNKNOWN)


def video_from_manifest_entry(entry: VideoInfo | dict[str, Any]) -> ChannelVideo:
    """Adapt one flat yt-dlp manifest entry to the ingest ``ChannelVideo``.

    Status fields start as ``unknown``: the flat pass carries no evidence about
    them, and ``upload_status`` stays unknown even after a full extraction.
    """
    duration = _entry_field(entry, "duration", None)
    return ChannelVideo(
        video_id=str(_entry_field(entry, "id", "")).strip(),
        title=str(_entry_field(entry, "title", "")),
        published_at=_date_from_upload_date(str(_entry_field(entry, "upload_date", ""))),
        duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
        privacy_status=UNKNOWN,
        upload_status=UNKNOWN,
        broadcast_status=UNKNOWN,
        description=str(_entry_field(entry, "description", "")),
    )


def apply_full_details(video: ChannelVideo, details: dict[str, Any]) -> ChannelVideo:
    """Fold a full per-video extraction into a flat entry (evidence only).

    Fields the extraction does not report keep their previous value (and status
    fields keep ``unknown``); nothing is inferred from absence.
    """
    duration = details.get("duration")
    published_at = (
        _iso_from_epoch(details.get("timestamp"))
        or _iso_from_epoch(details.get("release_timestamp"))
        or video.published_at
    )
    return ChannelVideo(
        video_id=video.video_id,
        title=str(details.get("title") or video.title),
        published_at=published_at,
        duration_seconds=int(duration)
        if isinstance(duration, (int, float))
        else video.duration_seconds,
        privacy_status=_privacy_from_availability(details.get("availability")),
        upload_status=UNKNOWN,
        broadcast_status=_broadcast_from_live_status(details.get("live_status")),
        description=str(details.get("description") or video.description),
    )


@dataclass
class AdapterResult:
    """Worklist plus the resolution counts the CI log should show."""

    worklist: Worklist
    resolved: int = 0
    unresolved: int = 0


def build_worklist_from_manifest(
    manifest: ChannelManifest,
    index_ids: set[str],
    runner: VideoDetailRunner | None = None,
    max_new: int = 50,
) -> AdapterResult:
    """Diff a flat channel manifest against the index and resolve the delta.

    Args:
        manifest: Flat yt-dlp enumeration of the channel.
        index_ids: Video ids already referenced by the journal ``INDEX.json``.
        runner: Full per-video extractor for new videos; ``None`` skips
            resolution (every status field stays ``unknown``).
        max_new: Cap on full extractions per run; videos past the cap stay
            unresolved (``unknown``) rather than being guessed at.

    Returns:
        :class:`AdapterResult` with the worklist and the resolved/unresolved
        counts. Unresolved videos are still listed, with status ``unknown``.
    """
    videos = [video_from_manifest_entry(entry) for entry in manifest.videos]
    new_videos = diff_against_index(videos, index_ids)
    resolved = 0
    unresolved = 0
    for position, video in enumerate(new_videos):
        if runner is None or position >= max_new:
            unresolved += 1
            continue
        details = runner.video_details(video.video_id)
        if details is None:
            unresolved += 1
            continue
        new_videos[position] = apply_full_details(video, details)
        resolved += 1
    if unresolved:
        logger.warning(
            "%d of %d new videos were not fully resolved (cap=%d); their status "
            "fields stay '%s' and must not be treated as published",
            unresolved,
            len(new_videos),
            max_new,
            UNKNOWN,
        )
    return AdapterResult(
        worklist=Worklist(
            channel_id=manifest.channel_id or DEFAULT_CHANNEL_ID,
            index_video_count=len(index_ids),
            channel_video_count=len(videos),
            new_videos=new_videos,
        ),
        resolved=resolved,
        unresolved=unresolved,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: secret-free enumeration + delta resolution. Dry-run is the default."""
    parser = argparse.ArgumentParser(
        prog="journal_utilities.ingest.ytdlp",
        description=(
            "Enumerate the channel with yt-dlp (no API key), diff it against the "
            "journal INDEX.json, and resolve new videos with full per-video "
            "extractions. Unknown fields are recorded as 'unknown'."
        ),
    )
    parser.add_argument("--channel-id", default=DEFAULT_CHANNEL_ID)
    parser.add_argument(
        "--channel-manifest",
        type=Path,
        help="Reuse a saved yt-dlp channel manifest instead of enumerating live",
    )
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
    parser.add_argument(
        "--channel-output",
        type=Path,
        help=(
            "Copy the flat channel manifest here (only with --no-dry-run) — the "
            "artifact the reconciliation gate consumes"
        ),
    )
    parser.add_argument(
        "--details-dir",
        type=Path,
        help="Read saved full extractions from <dir>/<video_id>.json instead of yt-dlp",
    )
    parser.add_argument(
        "--max-new",
        type=int,
        default=50,
        help="Cap full extractions per run (default 50); past the cap stays unknown",
    )
    parser.add_argument(
        "--no-resolve",
        dest="resolve",
        action="store_false",
        help="Skip full extractions entirely (every status field stays 'unknown')",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually write the worklist/manifest files (default: dry-run)",
    )
    parser.set_defaults(resolve=True, dry_run=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.details_dir is not None and not args.resolve:
        parser.error("--details-dir and --no-resolve are mutually exclusive")
    if args.max_new < 0:
        parser.error("--max-new must be >= 0")

    index_path = args.journal / "INDEX.json"
    index_ids = load_index_video_ids(index_path)
    if not index_ids:
        raise SystemExit(
            f"No video ids could be read from {index_path} — refusing to diff "
            "against an empty index. Check the --journal path."
        )

    if args.channel_manifest is not None:
        manifest = load_channel_manifest(args.channel_manifest)
    else:
        manifest = enumerate_channel_videos(args.channel_id)

    runner: VideoDetailRunner | None = None
    if args.resolve:
        runner = (
            DirectoryVideoDetailRunner(args.details_dir)
            if args.details_dir is not None
            else SubprocessYtDlpRunner()
        )

    result = build_worklist_from_manifest(manifest, index_ids, runner, args.max_new)
    worklist = result.worklist
    print(f"channel videos: {worklist.channel_video_count}")
    print(f"index video ids: {worklist.index_video_count}")
    print(f"new videos: {len(worklist.new_videos)}")
    print(f"resolved with full extraction: {result.resolved}")
    print(f"status unknown: {result.unresolved}")
    for video in worklist.new_videos:
        print(
            f"  {video.video_id}  [{video.publication_state}]  "
            f"{video.published_date or 'date-unknown'}  {video.title}"
        )

    if args.output is not None or args.channel_output is not None:
        if args.dry_run:
            for target in (args.output, args.channel_output):
                if target is not None:
                    print(f"dry-run: would write {target}")
        else:
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(worklist.to_dict(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                print(f"wrote worklist to {args.output}")
            if args.channel_output is not None:
                args.channel_output.parent.mkdir(parents=True, exist_ok=True)
                save_channel_manifest(manifest, args.channel_output)
                print(f"wrote channel manifest to {args.channel_output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
