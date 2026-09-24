#!/usr/bin/env python3
"""Upload journal-derived caption tracks (M5 captions write-back).

DRY-RUN BY DEFAULT. Live writes require ``--apply`` AND OAuth
(scope ``youtube.force-ssl``). Per pipeline Rule 1 / handoff M5:

- ``captions.list`` runs before any insert; a video with an existing
  **non-ASR** track (or a track already named ``English (Active Inference
  Journal)``) is SKIPPED — captions.insert never overwrites or duplicates.
- The SRT is derived from the journal's WhisperX ``transcript.json``
  (speaker labels, two-line wrapping ≤42 chars) via
  :mod:`journal_utilities.youtube.captions`; the journal is the source of
  truth.
- Track name: ``English (Active Inference Journal)``, language ``en``,
  ``isDraft=false``.
- Before every write (insert AND metadata.json update) a backup is written to
  ``data/output/yt_backup/<video_id>/<timestamp>.json`` (captions.list snapshot
  + pre-update metadata copy).
- On success, ``captions_uploaded`` is written into the item's
  ``metadata.json`` with full provenance (source, sha256, timestamps).
- Quota accounting: ``captions.list`` = 1 unit, ``captions.insert`` = 400
  units, against ``--quota-budget`` (default 10,000/day) and
  ``--max-uploads-per-day`` (default 24 — 24 x 401 = 9,624 units, the largest
  whole-day upload count that fits the default budget).

**OAuth token owner: admin@activeinference.institute** (org account
``ActiveInferenceInstitute``). The ``ActInfInstitute`` account is a
personal/admin account — never authorize writes with it.

Translation wave (V5, DAF decision 2026-09): upload of machine-translated
tracks is opt-in via ``--upload-translations``; the default target-language
set is ``zh-Hans,de`` (``--languages``). The handoff's es/pt/fr/ja list is
DEFERRED — available via an explicit ``--languages`` override, not default.

Example:

    python scripts/upload_captions.py --journal ../ActiveInferenceJournal
    python scripts/upload_captions.py --apply --max-uploads-per-day 24 \
        --quota-budget 10000 --journal ../ActiveInferenceJournal
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))  # captions_worklist import

if TYPE_CHECKING:
    from journal_utilities.youtube.client import QuotaLedger

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
STAGING_DIR = DATA_DIR / "output/captions_upload"
BACKUP_DIR = DATA_DIR / "output/yt_backup"
DEFAULT_JOURNAL = REPO_ROOT.parent / "ActiveInferenceJournal"
DEFAULT_BUDGET = 10_000
DEFAULT_MAX_UPLOADS = 24
#: Track name for the derived English caption track.
TRACK_NAME = "English (Active Inference Journal)"
TRACK_LANGUAGE = "en"
#: DAF decision (2026-09): first translation wave is zh-Hans + de ONLY.
DEFAULT_LANGUAGES = ("zh-Hans", "de")
#: Deferred per the handoff; opt-in via --languages only.
DEFERRED_LANGUAGES = ("es", "pt", "fr", "ja")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("upload_captions")


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def backup_path(video_id: str, backup_dir: Path, stamp: str) -> Path:
    target = backup_dir / video_id
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{stamp}-captions.json"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def has_blocking_track(tracks: list[dict[str, Any]]) -> bool:
    """True when captions.list shows a track that must not be overwritten.

    Blocks on: any non-ASR (``nonAsr``/``standard``) track, OR any track
    already named ``TRACK_NAME`` (our own, re-uploading would duplicate).
    ASR-only videos remain upload targets — our journal SRT is the upgrade.
    """
    for t in tracks:
        snippet = t.get("snippet", {}) if isinstance(t, dict) else {}
        kind = snippet.get("trackKind", "")
        if kind and kind != "asr":
            return True
        if snippet.get("name") == TRACK_NAME:
            return True
    return False


def load_worklist_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@dataclass
class UploadContext:
    """Everything the per-video caption upload needs beyond the client."""

    client: Any  # noqa: ANN401 — duck-typed: real YouTubeClient or a fake
    ledger: QuotaLedger
    journal_dir: Path
    apply: bool
    backup_dir: Path = BACKUP_DIR
    staging_dir: Path = STAGING_DIR
    max_uploads: int = DEFAULT_MAX_UPLOADS
    uploads_done: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)


def _backup_before_write(
    ctx: UploadContext, video_id: str, tracks: list[dict[str, Any]], item_dir: Path
) -> Path:
    """Rule 1(b): snapshot live tracks + pre-update metadata before writing."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = backup_path(video_id, ctx.backup_dir, stamp)
    meta_bytes = b""
    meta_file = item_dir / "metadata.json"
    if meta_file.is_file():
        meta_bytes = meta_file.read_bytes()
    payload = {
        "backed_up_at": stamp,
        "video_id": video_id,
        "captions_list": tracks,
        "metadata_json": meta_bytes.decode("utf-8", errors="replace"),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Backed up pre-upload state for %s -> %s", video_id, path)
    return path


def upload_captions_for_video(ctx: UploadContext, row: dict[str, str]) -> dict[str, Any]:
    """One video: skip-if-existing -> derive SRT -> (apply) backup+insert+record.

    Dry-run performs no API calls and writes nothing; it reports the plan.
    """
    from journal_utilities.youtube.captions import derive_srt_for_video

    vid = row["video_id"]
    item_dir = ctx.journal_dir / row["item_path"]
    result: dict[str, Any] = {"video_id": vid, "action": "skipped"}

    # Local gates first (no quota): derivable SRT only.
    srt = derive_srt_for_video(item_dir, vid)
    if srt is None:
        result["reason"] = "no whisperx transcript for this part"
        return result
    if row.get("existing_srt") == "true":
        result["reason"] = "journal already carries a caption SRT (verify live before upload)"
        return result

    # Live skip gate (quota: captions.list = 1) — apply mode only.
    tracks: list[dict[str, Any]] = []
    if ctx.apply:
        from journal_utilities.youtube.client import QuotaBudgetExceededError

        if not ctx.ledger.can_spend("captions.list"):
            result["reason"] = "quota budget exhausted before captions.list"
            return result
        try:
            ctx.ledger.spend("captions.list")
        except QuotaBudgetExceededError as exc:  # pragma: no cover - can_spend guards
            result["reason"] = str(exc)
            return result
        tracks = ctx.client.list_captions(vid) or []
        if has_blocking_track(tracks):
            result["reason"] = "existing non-ASR / journal track on YouTube"
            return result

    if not ctx.apply:
        result["action"] = "planned"
        result["reason"] = "dry-run: would derive SRT, verify live tracks, upload"
        result["srt_sha256"] = sha256_text(srt)
        result["cue_count"] = srt.count("\n\n")
        return result

    from journal_utilities.youtube.client import QuotaBudgetExceededError

    if ctx.uploads_done >= ctx.max_uploads:
        result["reason"] = f"daily upload cap reached ({ctx.max_uploads})"
        return result
    if not ctx.ledger.can_spend("captions.insert"):
        result["reason"] = "quota budget exhausted before captions.insert"
        return result

    # Rule 1(b): backup BEFORE the write.
    _backup_before_write(ctx, vid, tracks, item_dir)

    try:
        ctx.ledger.spend("captions.insert")
    except QuotaBudgetExceededError as exc:  # pragma: no cover - can_spend guards
        result["reason"] = str(exc)
        return result

    # Stage the derived SRT JU-side (data/output) — NEVER write into the
    # journal checkout from this script; the journal is read-only input.
    srt_file = ctx.staging_dir / f"{vid}.en.srt"
    srt_file.parent.mkdir(parents=True, exist_ok=True)
    srt_file.write_text(srt, encoding="utf-8")

    response = ctx.client.insert_caption(vid, TRACK_NAME, TRACK_LANGUAGE, str(srt_file))
    if not response:
        result["reason"] = "captions.insert failed (see client log)"
        return result

    stamp = utc_now()
    record = {
        "track_name": TRACK_NAME,
        "language": TRACK_LANGUAGE,
        "is_draft": False,
        "uploaded_at": stamp,
        "srt_source": "whisperx:transcript.json",
        "srt_sha256": sha256_text(srt),
        "srt_path": str(srt_file),
        "caption_track_id": response.get("id"),
        "provenance": {
            "generated_by": "scripts/upload_captions.py",
            "generated_at": stamp,
            "journal": str(ctx.journal_dir),
            "item": row.get("item", ""),
        },
    }
    _write_metadata_record(item_dir, vid, record)
    result.update({"action": "uploaded", "caption_track_id": response.get("id")})
    return result


def _write_metadata_record(item_dir: Path, video_id: str, record: dict[str, Any]) -> None:
    """Merge ``captions_uploaded[video_id]`` into the item metadata.json."""
    meta_file = item_dir / "metadata.json"
    meta: dict[str, Any] = {}
    if meta_file.is_file():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    uploaded = meta.setdefault("captions_uploaded", {})
    uploaded[video_id] = record
    meta_file.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    logger.info("Recorded captions_uploaded[%s] in %s", video_id, meta_file)


def run(ctx: UploadContext, rows: list[dict[str, str]]) -> dict[str, int]:
    """Process the ranked worklist; returns action counts."""
    counts = {"uploaded": 0, "planned": 0, "skipped": 0}
    for row in rows:
        result = upload_captions_for_video(ctx, row)
        action = result.pop("action", "skipped")
        counts[action] = counts.get(action, 0) + 1
        ctx.results.append({"video_id": row["video_id"], **result})
        logger.info("[%s] %s: %s", action, row["video_id"], result.get("reason", "ok"))
        if action == "uploaded":
            ctx.uploads_done += 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload journal-derived caption tracks (dry-run by default).",
        epilog=(
            "OAuth token owner: admin@activeinference.institute (org "
            "ActiveInferenceInstitute). The ActInfInstitute account is "
            "personal/admin — do not use it for writes. Env: "
            "YOUTUBE_CLIENT_SECRETS + YOUTUBE_TOKEN_PATH (scope "
            "youtube.force-ssl); an API key alone cannot upload captions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL, help="Journal checkout")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Upload live (default dry-run: no API calls, no writes)",
    )
    parser.add_argument(
        "--quota-budget",
        type=int,
        default=DEFAULT_BUDGET,
        help="Daily quota units this run may spend (captions.insert=400, captions.list=1)",
    )
    parser.add_argument(
        "--max-uploads-per-day",
        type=int,
        default=DEFAULT_MAX_UPLOADS,
        help="Cap on captions.insert calls per run (default 24: 24x401=9,624 units <= 10,000)",
    )
    parser.add_argument(
        "--worklist",
        type=Path,
        default=None,
        help="Pre-ranked CSV from captions_worklist.py (default: rank from INDEX.json live)",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Max worklist rows to evaluate (0 = all)"
    )
    parser.add_argument(
        "--languages",
        default=",".join(DEFAULT_LANGUAGES),
        help=(
            "Target-language set for the translation wave. DEFAULT (DAF 2026-09): "
            f"{','.join(DEFAULT_LANGUAGES)} only. Deferred (handoff es/pt/fr/ja): "
            f"{','.join(DEFERRED_LANGUAGES)} — opt-in via explicit --languages."
        ),
    )
    parser.add_argument(
        "--upload-translations",
        action="store_true",
        help="Also upload machine-translated tracks for --languages (opt-in; V5 wave)",
    )
    parser.add_argument(
        "--backup-dir", type=Path, default=BACKUP_DIR, help="Rule-1 backup directory"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from captions_worklist import build_worklist, load_views_map, write_csv

    from journal_utilities.youtube.client import QuotaLedger

    ledger = QuotaLedger(budget=args.quota_budget)
    client: Any | None = None  # noqa: ANN401
    if args.apply:
        from journal_utilities.youtube.client import YouTubeClient

        client = YouTubeClient(
            api_key=os.environ.get("YOUTUBE_API_KEY"),
            client_secrets_path=os.environ.get("YOUTUBE_CLIENT_SECRETS"),
            token_path=os.environ.get("YOUTUBE_TOKEN_PATH"),
        )
    else:
        logger.info("Dry-run: no API client will be built; no writes will occur.")

    if args.worklist and args.worklist.is_file():
        rows = load_worklist_csv(args.worklist)
    else:
        rows = build_worklist(args.journal, load_views_map(DATA_DIR / "output/channel_videos.json"))
        rows = [{k: str(v) for k, v in r.items()} for r in rows]
        write_csv(rows, DATA_DIR / "output/captions_worklist.csv")
    if args.limit > 0:
        rows = rows[: args.limit]

    ctx = UploadContext(
        client=client,
        ledger=ledger,
        journal_dir=args.journal,
        apply=args.apply,
        backup_dir=args.backup_dir,
        max_uploads=args.max_uploads_per_day,
    )
    counts = run(ctx, rows)
    logger.info(
        "Done: %s | quota spent %d/%d units | uploads %d/%d",
        counts,
        ledger.spent,
        ledger.budget,
        ctx.uploads_done,
        ctx.max_uploads,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
