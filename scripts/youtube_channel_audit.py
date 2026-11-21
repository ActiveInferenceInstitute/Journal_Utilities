#!/usr/bin/env python3
"""Audit the Institute channel and apply reviewed, description-only repairs."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from journal_utilities.ingest.enumerate import DEFAULT_CHANNEL_ID
from journal_utilities.youtube.channel_audit import (
    CLASSES,
    INSTITUTE_HOSTS,
    VIDEO_ID,
    audit_channel,
    description_changes,
    is_completed_public,
    journal_backlink,
    read_index,
    split_url,
    stable_digest,
)
from journal_utilities.youtube.client import (
    QuotaBudgetExceededError,
    QuotaLedger,
    VideoSnippet,
    YouTubeClient,
    YouTubeReadError,
)

PLAN_VERSION = 1


def _write_private_json(path: Path, value: object) -> None:
    """Publish a complete locally owned report with private file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _classes(value: str) -> frozenset[str]:
    values = frozenset(value.split(","))
    if not values or not values <= CLASSES:
        raise argparse.ArgumentTypeError(
            f"Expected comma-separated values from {', '.join(sorted(CLASSES))}"
        )
    return values


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return parsed


def _cached_oauth() -> YouTubeClient:
    token = os.environ.get("YOUTUBE_TOKEN_PATH")
    if not token or not Path(token).is_file():
        raise ValueError("Set YOUTUBE_TOKEN_PATH to the authorized local OAuth token")
    # This path must never start a new consent flow.
    return YouTubeClient(token_path=token)


def _link_http_status(link: str) -> int | None:
    """Check a known Institute host without transmitting query data or redirects."""
    parts = split_url(link)
    if parts is None or parts.hostname is None or parts.hostname not in INSTITUTE_HOSTS:
        return None
    connection = http.client.HTTPSConnection(parts.hostname, timeout=5)
    try:
        connection.request("HEAD", parts.path or "/")
        return connection.getresponse().status
    except (OSError, UnicodeError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def _audit(args: argparse.Namespace) -> int:
    index, index_digest = read_index(args.journal / "INDEX.json")
    if args.owner:
        client = _cached_oauth()
    else:
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise ValueError("Set YOUTUBE_API_KEY for public inventory or choose --owner")
        client = YouTubeClient(api_key=key)
    ledger = QuotaLedger(args.quota_budget)
    if args.owner:
        client.require_channel(args.channel_id, ledger=ledger)
    worklist, findings, repairs, unavailable = audit_channel(
        client,
        args.channel_id,
        ledger,
        index,
        args.classes if args.plan else frozenset(),
        ZoneInfo(args.timezone),
        link_status=_link_http_status if args.check_http else None,
    )
    if args.plan:
        _write_private_json(
            args.plan,
            {
                "version": PLAN_VERSION,
                "generated_at": worklist.generated_at,
                "channel_id": args.channel_id,
                "index_sha256": index_digest,
                "classes": sorted(args.classes),
                "repairs": repairs,
            },
        )
        print(f"Repair plan SHA-256 {hashlib.sha256(args.plan.read_bytes()).hexdigest()}")
    if args.worklist:
        _write_private_json(args.worklist, worklist.to_dict())
    counts: dict[str, int] = {}
    for finding in findings:
        kind = finding["kind"]
        counts[kind] = counts.get(kind, 0) + 1
    report = {
        "channel_id": args.channel_id,
        "generated_at": worklist.generated_at,
        "index_sha256": index_digest,
        "discovered_video_ids": worklist.channel_video_count,
        "unavailable_video_details": unavailable,
        "quota_spent": ledger.spent,
        "findings_by_kind": counts,
        "findings": findings,
    }
    if args.report:
        _write_private_json(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key != "findings"}))
    return int(args.fail_on_findings and bool(findings))


def _load_reviewed_plan(
    args: argparse.Namespace, index_digest: str
) -> tuple[frozenset[str], list[dict[str, Any]]]:
    raw = args.plan.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.plan_sha256:
        raise ValueError("Repair plan SHA-256 does not match the reviewed file")
    plan = json.loads(raw)
    if (
        not isinstance(plan, dict)
        or plan.get("version") != PLAN_VERSION
        or plan.get("channel_id") != args.channel_id
        or plan.get("index_sha256") != index_digest
        or not isinstance(plan.get("classes"), list)
        or not isinstance(plan.get("repairs"), list)
    ):
        raise ValueError("Repair plan does not match the current Journal index and channel")
    classes = _classes(",".join(plan["classes"]))
    seen: set[str] = set()
    rows: list[dict[str, Any]] = plan["repairs"]
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("video_id"), str)
            or not VIDEO_ID.fullmatch(row["video_id"])
            or row["video_id"] in seen
            or not isinstance(row.get("before_sha256"), str)
            or not isinstance(row.get("before"), str)
            or not isinstance(row.get("after"), str)
            or len(row["after"].encode()) > 5000
        ):
            raise ValueError("Repair plan has an invalid or duplicate video or description")
        seen.add(row["video_id"])
    return classes, rows


def _apply(args: argparse.Namespace) -> int:
    index, digest = read_index(args.journal / "INDEX.json")
    classes, rows = _load_reviewed_plan(args, digest)
    if not rows:
        print("The reviewed repair plan is empty")
        return 0
    client = _cached_oauth()
    ledger = QuotaLedger(args.quota_budget)
    client.require_channel(args.channel_id, ledger=ledger)
    skipped = 0
    updated = 0
    for row in rows[: args.limit]:
        video_id = row["video_id"]
        video = client.list_videos([video_id], part="snippet,status", strict=True, ledger=ledger)
        if len(video) != 1 or not is_completed_public(video[0], args.channel_id):
            raise YouTubeReadError(f"Could not verify public ownership for {video_id}")
        live = VideoSnippet.from_api(video[0])
        if live.description == row["after"]:
            skipped += 1
            continue
        if (
            stable_digest(live.to_body()) != row["before_sha256"]
            or live.description != row["before"]
        ):
            raise ValueError(f"The live snippet changed since review for {video_id}")
        journal_url, has_transcript = journal_backlink(video_id, index)
        proposed, _ = description_changes(
            live.description, journal_url, classes, has_transcript=has_transcript
        )
        if proposed != row["after"] or proposed == live.description:
            raise ValueError(
                f"The reviewed description does not match the current rules for {video_id}"
            )
        if ledger.remaining < 51:
            raise QuotaBudgetExceededError("Insufficient quota for one write and verification")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        _write_private_json(
            args.backup_dir / video_id / f"{stamp}.json",
            {"channel_id": args.channel_id, "snapshot": live.to_body()},
        )
        intended = replace(live, description=proposed)
        ledger.spend("videos.update")
        result = client.update_video_snippet(intended, dry_run=False)
        if not result.success:
            raise YouTubeReadError(f"Update outcome requires readback for {video_id}")
        observed = client.list_videos([video_id], part="snippet,status", strict=True, ledger=ledger)
        if (
            len(observed) != 1
            or not is_completed_public(observed[0], args.channel_id)
            or VideoSnippet.from_api(observed[0]) != intended
        ):
            raise YouTubeReadError(f"Update could not be verified for {video_id}")
        updated += 1
        print(f"Verified description update for {video_id}")
    print(
        json.dumps(
            {"verified_updates": updated, "already_current": skipped, "quota_spent": ledger.spent}
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    audit = sub.add_parser(
        "audit", help="Collect public QA findings and optionally prepare a repair plan"
    )
    apply = sub.add_parser("apply", help="Apply an exact reviewed description repair plan")
    for command in (audit, apply):
        command.add_argument(
            "--journal", required=True, type=Path, help="ActiveInferenceJournal checkout"
        )
        command.add_argument("--channel-id", default=DEFAULT_CHANNEL_ID)
        command.add_argument("--quota-budget", type=_positive, default=10_000)
    audit.add_argument(
        "--owner", action="store_true", help="Read with the verified cached channel OAuth grant"
    )
    audit.add_argument("--worklist", type=Path, help="Write a private public-ingest worklist")
    audit.add_argument("--report", type=Path, help="Write a private QA report")
    audit.add_argument(
        "--plan", type=Path, help="Write a private description repair plan for review"
    )
    audit.add_argument(
        "--check-http", action="store_true", help="Check HTTP status for Institute links"
    )
    audit.add_argument(
        "--classes", type=_classes, default=frozenset({"dead", "legacy", "backlink"})
    )
    audit.add_argument(
        "--timezone", default="America/Los_Angeles", help="Timezone for dates in titles"
    )
    audit.add_argument("--fail-on-findings", action="store_true")
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--plan-sha256", required=True)
    apply.add_argument("--backup-dir", required=True, type=Path)
    apply.add_argument(
        "--limit", default=10, type=_positive, help="Consider at most this many repairs"
    )
    args = parser.parse_args(argv)
    try:
        if args.action == "audit":
            destinations = [
                p.resolve() for p in (args.plan, args.report, args.worklist) if p is not None
            ]
            if (
                len(set(destinations)) != len(destinations)
                or args.journal.joinpath("INDEX.json").resolve() in destinations
            ):
                raise ValueError("Choose distinct report destinations outside the Journal index")
            return _audit(args)
        return _apply(args)
    except (
        OSError,
        ValueError,
        TypeError,
        ZoneInfoNotFoundError,
        QuotaBudgetExceededError,
        YouTubeReadError,
    ) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
