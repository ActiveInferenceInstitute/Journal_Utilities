#!/usr/bin/env python3
"""
Derive the transcription worklist from the journal repo — no database.

Status is computed, never stored: an item needs transcription when it lacks
transcript.txt; it's a WhisperX-upgrade candidate when its transcript has no
speaker labels and no diarization CSVs. Private/unlisted content (items with
no public video id, and ids registered in private_videos.json) is excluded —
no transcription is created for it, by policy. New channel videos without a
journal item are listed separately.

Usage:
    python scripts/transcription_status.py            # summary to stdout
    python scripts/transcription_status.py --report worklist.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JOURNAL = REPO.parent / "ActiveInferenceJournal"
SRC_PREFIX = "data/video/activeinferenceinstitute"
MANIFEST = REPO / "data/output/channel_videos.json"


def item_status(item_dir: Path) -> str:
    transcript = item_dir / "transcript.txt"
    if not transcript.exists():
        return "missing"
    has_csv = (
        any((item_dir / "assets" / "csv").glob("*.sentences.csv"))
        if (item_dir / "assets" / "csv").is_dir()
        else False
    )
    head = transcript.read_text(encoding="utf-8", errors="replace")[:200_000]
    has_speakers = "SPEAKER_" in head or has_csv
    return "diarized" if has_speakers else "captions_only"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=JOURNAL)
    parser.add_argument("--report", type=Path, help="write full JSON worklist here")
    args = parser.parse_args()

    from datetime import date as _date

    today = _date.today().isoformat()

    root = args.journal / SRC_PREFIX
    private_path = root / "private_videos.json"
    private = (
        json.loads(private_path.read_text(encoding="utf-8")).get("videos", [])
        if private_path.exists()
        else []
    )
    private_ids = {v["video_id"] for v in private if v.get("video_id")}

    buckets = {"missing": [], "captions_only": [], "diarized": [], "scheduled": [], "excluded": []}
    covered_ids: set[str] = set()
    for meta_path in sorted(root.rglob("metadata.json")):
        item_dir = meta_path.parent
        rel = str(item_dir.relative_to(root))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for part in meta.get("parts", []):
            if part.get("video_id"):
                covered_ids.add(part["video_id"])
        if meta.get("duplicate_of"):
            continue  # content lives at the curated item
        status = item_status(item_dir)
        dates = [meta.get("date", "")] + [p.get("date", "") for p in meta.get("parts", [])]
        if status == "missing":
            if max(filter(None, dates), default="") > today:
                status = "scheduled"  # future stream — nothing to transcribe yet
            elif not any(
                p.get("video_id") and p["video_id"] not in private_ids
                for p in meta.get("parts", [])
            ):
                status = "excluded"  # private/unlisted — no transcription by policy
        buckets[status].append(rel)

    manifest_videos = json.loads(MANIFEST.read_text(encoding="utf-8")).get("videos", [])
    no_item = [
        {"video_id": v["id"], "title": v.get("title", "")}
        for v in manifest_videos
        if v.get("id") and v["id"] not in covered_ids
    ]

    print(f"journal items:          {sum(len(b) for b in buckets.values())}")
    print(f"  diarized (done):      {len(buckets['diarized'])}")
    print(f"  captions only:        {len(buckets['captions_only'])}  (WhisperX upgrade candidates)")
    print(f"  missing transcript:   {len(buckets['missing'])}  (needs transcription)")
    print(
        f"  excluded:             {len(buckets['excluded'])}  (private/unlisted — no transcription by policy)"
    )
    print(f"  scheduled (future):   {len(buckets['scheduled'])}  {buckets['scheduled']}")
    from datetime import date

    manifest_age = date.fromtimestamp(MANIFEST.stat().st_mtime).isoformat()
    print(
        f"channel videos w/o item:{len(no_item):>4}  (manifest from {manifest_age} — re-enumerate for newer videos)"
    )
    print(f"registered private ids: {len(private):>4}")
    for rel in buckets["missing"]:
        print(f"  MISSING  {rel}")
    for rel in buckets["excluded"]:
        print(f"  EXCLUDED {rel}")
    for row in no_item:
        print(f"  NO-ITEM  {row['video_id']}  {row['title'][:70]}")

    if args.report:
        args.report.write_text(
            json.dumps(
                {
                    "missing": buckets["missing"],
                    "excluded": buckets["excluded"],
                    "scheduled": buckets["scheduled"],
                    "captions_only": buckets["captions_only"],
                    "diarized_count": len(buckets["diarized"]),
                    "no_item": no_item,
                    "private": private,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"full worklist -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
