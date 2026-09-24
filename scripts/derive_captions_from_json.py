#!/usr/bin/env python3
"""
Derive base English captions/*.srt files from diarized transcript.json for items
that currently lack caption SRTs.

Timestamp formatting delegates to the canonical implementation in
``journal_utilities.youtube.captions`` (which also adds speaker labels and
42-char two-line wrapping for the upload path — this script writes the plain
per-segment form the journal captions/ dirs hold).

Usage:
    python scripts/derive_captions_from_json.py --journal ../ActiveInferenceJournal
    python scripts/derive_captions_from_json.py --journal ../ActiveInferenceJournal --apply
"""

import argparse
import json
import sys
from pathlib import Path

from journal_utilities.youtube.captions import srt_timestamp as sec_to_srt_time


def segments_to_srt(segments: list[dict]) -> str:
    """Convert a list of segment dicts with start, end, text to standard SRT text."""
    lines = []
    cue_idx = 1
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 1.0))
        if end <= start:
            end = start + 1.0
        lines.append(str(cue_idx))
        lines.append(f"{sec_to_srt_time(start)} --> {sec_to_srt_time(end)}")
        lines.append(text)
        lines.append("")
        cue_idx += 1
    return "\n".join(lines)


def derive_captions(journal_dir: Path, apply: bool = False) -> dict[str, int]:
    index_path = journal_dir / "INDEX.json"
    if not index_path.exists():
        raise FileNotFoundError(f"INDEX.json not found at {index_path}")

    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    items = index_data.get("items", [])

    created_count = 0
    skipped_count = 0

    for it in items:
        item_path = journal_dir / it.get("path", "")
        cap_dir = item_path / "captions"
        existing_srts = list(cap_dir.glob("*.srt")) if cap_dir.exists() else []
        if existing_srts:
            skipped_count += 1
            continue

        tj_path = item_path / "transcript.json"
        if not tj_path.exists():
            continue

        try:
            data = json.loads(tj_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
        except Exception:
            continue

        meta_path = item_path / "metadata.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        item_id = meta.get("item") or it.get("item", item_path.name)
        parts = meta.get("parts", [])

        # Map blocks to video titles/parts
        for idx, block in enumerate(data):
            if not isinstance(block, dict) or not isinstance(block.get("segments"), list):
                continue
            segs = block["segments"]
            if not segs:
                continue

            vid = block.get("video_id", "")
            part_title = ""
            for p in parts:
                if p.get("video_id") == vid:
                    part_title = p.get("title", "")
                    break

            # Construct clean srt filename
            if part_title:
                clean_name = f"{part_title}.eng(transcribed).srt"
            elif len(data) > 1:
                clean_name = f"{item_id}_part{idx + 1}_{vid}.eng(transcribed).srt"
            else:
                clean_name = f"{item_id}_{vid}.eng(transcribed).srt"

            # sanitize filename
            clean_name = clean_name.replace("/", "_").replace(":", " -")
            srt_content = segments_to_srt(segs)

            if srt_content.strip():
                if apply:
                    cap_dir.mkdir(parents=True, exist_ok=True)
                    (cap_dir / clean_name).write_text(srt_content, encoding="utf-8")
                created_count += 1

    return {"created": created_count, "skipped": skipped_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Write .srt files to disk")
    args = parser.parse_args()

    stats = derive_captions(args.journal, apply=args.apply)
    mode = "Applied" if args.apply else "Preview (dry-run)"
    print(
        f"{mode}: {stats['created']} caption SRTs derived from transcript.json ({stats['skipped']} items already had SRTs)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
