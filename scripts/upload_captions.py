#!/usr/bin/env python3
"""Preview or upload reviewed English captions generated from Journal WhisperX transcripts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from journal_utilities.ingest.enumerate import DEFAULT_CHANNEL_ID
from journal_utilities.youtube.captions import derive_srt_for_video, parse_name_fix
from journal_utilities.youtube.client import QUOTA_COSTS, QuotaLedger

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
STAGING_DIR = DATA_DIR / "output/captions_upload"
BACKUP_DIR = DATA_DIR / "output/yt_backup"
RECEIPTS_FILE = DATA_DIR / "output/captions_uploaded.jsonl"
DEFAULT_JOURNAL = REPO_ROOT.parent / "ActiveInferenceJournal"
DEFAULT_BUDGET = 10_000
DEFAULT_MAX_UPLOADS = 22
TRACK_NAME = "English (Active Inference Journal)"
TRACK_LANGUAGE = "en"

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_ENGLISH = re.compile(r"en(?:-[a-z0-9]{2,8})*", re.IGNORECASE)
_VIDEO_COST = sum(QUOTA_COSTS[key] for key in ("videos.list", "captions.list", "captions.insert"))
logger = logging.getLogger(__name__)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def has_blocking_track(tracks: list[dict[str, Any]]) -> bool:
    """Protect existing English tracks and any track with unverified type or language."""
    for track in tracks:
        snippet = track.get("snippet") if isinstance(track, dict) else None
        if not isinstance(snippet, dict) or snippet.get("name") == TRACK_NAME:
            return True
        kind, language = snippet.get("trackKind"), snippet.get("language")
        if not isinstance(kind, str) or kind.casefold() not in {
            "asr",
            "forced",
            "standard",
            "nonasr",
        }:
            return True
        if kind.casefold() != "asr" and (
            not isinstance(language, str)
            or not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", language)
            or language.casefold() == "und"
            or _ENGLISH.fullmatch(language)
        ):
            return True
    return False


def load_worklist_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temp = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def _load_receipts(path: Path) -> tuple[bytes, set[tuple[str, str]]]:
    if not path.exists():
        return b"", set()
    if path.is_symlink():
        raise ValueError("caption upload receipts must be an ordinary local file")
    payload = path.read_bytes()
    keys = set()
    for line in payload.splitlines():
        row = json.loads(line)
        vid = row.get("video_id") if isinstance(row, dict) else None
        sha = row.get("srt_sha256") if isinstance(row, dict) else None
        if not isinstance(vid, str) or not _VIDEO_ID.fullmatch(vid):
            raise ValueError("invalid video ID in caption upload receipts")
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise ValueError("invalid SRT digest in caption upload receipts")
        keys.add((vid, sha))
    return payload, keys


@contextmanager
def _lock_receipts(path: Path) -> Iterator[None]:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    if lock.is_symlink():
        raise ValueError("caption upload lock must be an ordinary local file")
    # This lock protects the whole live run, from its first receipt read to its final write.
    with lock.open("a", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another caption upload is using these receipts") from exc
        yield


@dataclass
class UploadContext:
    """Settings and counters for one caption batch."""

    client: Any  # noqa: ANN401 — real YouTube client or a test double
    ledger: QuotaLedger
    journal_dir: Path
    apply: bool
    backup_dir: Path = BACKUP_DIR
    staging_dir: Path = STAGING_DIR
    receipts_path: Path = RECEIPTS_FILE
    max_uploads: int = DEFAULT_MAX_UPLOADS
    name_fixes: dict[str, str] = field(default_factory=dict)
    uploads_done: int = 0
    upload_attempts: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


def _backup_before_write(
    ctx: UploadContext,
    video_id: str,
    tracks: list[dict[str, Any]],
    meta: bytes,
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = ctx.backup_dir / video_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{stamp}-captions.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "backed_up_at": stamp,
                    "video_id": video_id,
                    "captions_list": tracks,
                    "metadata_json": meta.decode("utf-8"),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _caption_language(videos: list[dict[str, Any]], video_id: str) -> str:
    if len(videos) != 1 or videos[0].get("id") != video_id:
        raise ValueError("YouTube did not return the exact selected video")
    video = videos[0]
    snippet, status = video.get("snippet"), video.get("status")
    if (
        not isinstance(snippet, dict)
        or snippet.get("channelId") != DEFAULT_CHANNEL_ID
        or not isinstance(status, dict)
        or status.get("privacyStatus") != "public"
    ):
        raise ValueError("the selected video must be public and owned by @ActiveInference")
    audio, metadata = snippet.get("defaultAudioLanguage"), snippet.get("defaultLanguage")
    if (
        not isinstance(audio, str)
        or not isinstance(metadata, str)
        or not _ENGLISH.fullmatch(audio)
        or audio.casefold() != metadata.casefold()
    ):
        raise ValueError("live video audio and metadata must have the same English language tag")
    return audio


def _read_metadata(path: Path, video_id: str) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink():
        raise ValueError("item metadata must be an ordinary file")
    original = path.read_bytes()
    meta = json.loads(original.decode("utf-8"))
    parts = meta.get("parts") if isinstance(meta, dict) else None
    if not isinstance(parts, list) or not any(
        isinstance(part, dict) and part.get("video_id") == video_id for part in parts
    ):
        raise ValueError("item metadata does not identify the selected video")
    if not isinstance(meta.setdefault("captions_uploaded", {}), dict):
        raise ValueError("existing caption provenance is unreadable")
    return original, meta


def _upload(
    ctx: UploadContext,
    video_id: str,
    metadata_path: Path,
    srt: str,
    sha: str,
) -> dict[str, Any]:
    from journal_utilities.youtube.client import YouTubeReadError

    if ctx.upload_attempts >= ctx.max_uploads:
        return {"action": "skipped", "reason": f"upload attempt cap reached ({ctx.max_uploads})"}
    if ctx.ledger.remaining < _VIDEO_COST:
        return {"action": "skipped", "reason": "insufficient quota for one verified upload"}
    raw_receipts, receipt_keys = _load_receipts(ctx.receipts_path)
    original, metadata = _read_metadata(metadata_path, video_id)
    if (video_id, sha) in receipt_keys or video_id in metadata["captions_uploaded"]:
        return {"action": "skipped", "reason": "the journal already records an uploaded track"}

    try:
        videos = ctx.client.list_videos(
            [video_id], part="snippet,status", strict=True, ledger=ctx.ledger
        )
        language = _caption_language(videos, video_id)
        tracks = ctx.client.list_captions(video_id, strict=True, ledger=ctx.ledger)
    except (ValueError, YouTubeReadError) as exc:
        return {"action": "skipped", "reason": str(exc)}
    if has_blocking_track(tracks):
        return {"action": "skipped", "reason": "existing non-ASR or unverified caption track"}

    backup = _backup_before_write(ctx, video_id, tracks, original)
    srt_file = ctx.staging_dir / f"{video_id}.{sha}.en.srt"
    srt_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(srt_file, srt.encode("utf-8"))
    ctx.ledger.spend("captions.insert")
    ctx.upload_attempts += 1
    response = ctx.client.insert_caption(
        video_id, TRACK_NAME, language, str(srt_file), is_draft=False
    )
    track_id = response.get("id") if isinstance(response, dict) else None
    if not isinstance(track_id, str) or not track_id:
        return {"action": "skipped", "reason": "caption insert failed or returned no track ID"}

    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    record = {
        "track_name": TRACK_NAME,
        "language": language,
        "is_draft": False,
        "uploaded_at": stamp,
        "srt_source": "whisperx:transcript.json",
        "srt_sha256": sha,
        "srt_path": str(srt_file),
        "caption_track_id": track_id,
        "provenance": {
            "generated_by": "scripts/upload_captions.py",
            "generated_at": stamp,
            "journal": str(ctx.journal_dir),
            "item": metadata.get("item", ""),
            "backup": str(backup),
        },
    }
    receipt = json.dumps({"video_id": video_id, **record}, ensure_ascii=False).encode("utf-8")
    ctx.receipts_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = raw_receipts.rstrip(b"\n") + b"\n" if raw_receipts else b""
    _atomic_write(ctx.receipts_path, prefix + receipt + b"\n")
    if metadata_path.read_bytes() != original:
        raise ValueError("upload recorded in receipts. Journal metadata changed during upload.")
    metadata["captions_uploaded"][video_id] = record
    _atomic_write(
        metadata_path,
        (json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        stat.S_IMODE(metadata_path.stat().st_mode),
    )
    return {"action": "uploaded", "caption_track_id": track_id}


def upload_captions_for_video(ctx: UploadContext, row: dict[str, str]) -> dict[str, Any]:
    """Plan one reviewed Journal source or apply it through the live captions safeguards."""
    video_id, item_path = row.get("video_id", ""), row.get("item_path", "")
    base = {"video_id": video_id, "action": "skipped"}
    if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id) or not item_path:
        return {**base, "reason": "invalid video ID or missing Journal item path"}
    root = ctx.journal_dir.resolve()
    item_dir = (root / item_path).resolve()
    if Path(item_path).is_absolute() or item_dir == root or not item_dir.is_relative_to(root):
        return {**base, "reason": "item path is outside the Journal checkout"}
    srt = derive_srt_for_video(item_dir, video_id, name_fixes=ctx.name_fixes)
    if not srt:
        return {**base, "reason": "no usable WhisperX transcript for this video"}
    sha = sha256_text(srt)
    if row.get("srt_sha256") and row["srt_sha256"] != sha:
        return {**base, "reason": "generated SRT differs from the reviewed digest"}
    if ctx.apply:
        return {**base, **_upload(ctx, video_id, item_dir / "metadata.json", srt, sha)}
    return {
        **base,
        "action": "planned",
        "reason": f"SRT SHA-256 {sha}",
        "srt_sha256": sha,
        "cue_count": srt.count("\n\n") + 1,
    }


def run(ctx: UploadContext, rows: list[dict[str, str]]) -> dict[str, int]:
    """Process the selected rows, reporting duplicate video selections once."""
    counts = {"uploaded": 0, "planned": 0, "skipped": 0}
    seen = set()
    for row in rows:
        video_id = row.get("video_id", "")
        if video_id in seen:
            result = {
                "video_id": video_id,
                "action": "skipped",
                "reason": "duplicate worklist video",
            }
        else:
            seen.add(video_id)
            result = upload_captions_for_video(ctx, row)
        action = result["action"]
        counts[action] += 1
        ctx.results.append(result)
        logger.info("[%s] %s %s", action, video_id, result.get("reason", "ok"))
        if action == "uploaded":
            ctx.uploads_done += 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL, help="Journal checkout")
    parser.add_argument("--apply", action="store_true", help="Upload selected worklist rows")
    parser.add_argument(
        "--worklist", type=Path, help="Reviewed caption CSV (required with --apply)"
    )
    parser.add_argument(
        "--quota-budget", type=int, default=DEFAULT_BUDGET, help="Quota units per run"
    )
    parser.add_argument(
        "--max-uploads-per-day",
        type=int,
        default=DEFAULT_MAX_UPLOADS,
        help="Cap caption insert attempts in this run",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to examine (0 is all)")
    parser.add_argument("--fix", action="append", default=[], help="Repeatable OLD=NEW name fix")
    parser.add_argument("--backup-dir", type=Path, default=BACKUP_DIR, help="Pre-upload backups")
    parser.add_argument(
        "--receipts", type=Path, default=RECEIPTS_FILE, help="JSONL upload receipts"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from captions_worklist import build_worklist, load_views_map

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.limit < 0 or args.quota_budget < 1 or args.max_uploads_per_day < 1:
        parser.error("limit must be nonnegative and quota and upload caps must be positive")
    if args.apply and args.worklist is None:
        parser.error("--apply requires an explicit reviewed --worklist")
    if args.worklist is not None and not args.worklist.is_file():
        parser.error("--worklist must name an existing CSV")
    if not (args.journal / "INDEX.json").is_file():
        parser.error("--journal must name the exact checkout containing INDEX.json")
    try:
        fixes = dict(parse_name_fix(value) for value in args.fix)
    except ValueError as exc:
        parser.error(str(exc))
    rows = (
        load_worklist_csv(args.worklist)
        if args.worklist
        else build_worklist(args.journal, load_views_map(DATA_DIR / "output/channel_videos.json"))
    )
    if args.limit:
        rows = rows[: args.limit]
    ctx = UploadContext(
        client=None,
        ledger=QuotaLedger(budget=args.quota_budget),
        journal_dir=args.journal,
        apply=args.apply,
        backup_dir=args.backup_dir,
        receipts_path=args.receipts,
        max_uploads=args.max_uploads_per_day,
        name_fixes=fixes,
    )

    try:
        if args.apply:
            from journal_utilities.youtube.client import YouTubeClient

            with _lock_receipts(args.receipts):
                _load_receipts(args.receipts)
                ctx.client = YouTubeClient(
                    client_secrets_path=os.environ.get("YOUTUBE_CLIENT_SECRETS"),
                    token_path=os.environ.get("YOUTUBE_TOKEN_PATH"),
                )
                ctx.client.require_channel(DEFAULT_CHANNEL_ID, ledger=ctx.ledger)
                counts = run(ctx, rows)
        else:
            counts = run(ctx, rows)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.error("Caption run stopped. %s", exc)
        return 1
    logger.info(
        "Caption results %s. Quota used %d/%d.", counts, ctx.ledger.spent, ctx.ledger.budget
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
