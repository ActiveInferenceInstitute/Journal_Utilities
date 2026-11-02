#!/usr/bin/env python3
"""
Regenerate journal transcript.txt from transcript.json + parts[].speakers.

Per docs/SCHEMA.md "Transcripts — raw vs derived": transcript.json is the
immutable raw diarization layer (labels stay SPEAKER_NN forever) and
transcript.txt is a derived view — segments grouped into speaker-labeled
paragraphs, labels replaced with human names where the journal-owned
``parts[].speakers`` mapping identifies them. Unmapped labels remain
SPEAKER_NN and are reported as to-dos. Re-running is idempotent; fixing a
wrong name is editing metadata.json and re-running.

When an item's existing transcript.txt has no speaker structure (YouTube
captions or legacy prose), it is salvaged to captions/youtube_captions.txt
before being replaced, so the caption text stays in the working tree.

Items whose transcript.json is not the whisperx block format (legacy
AssemblyAI responses) are skipped and reported.

Usage:
    python scripts/apply_speaker_names.py                 # dry run: show plan
    python scripts/apply_speaker_names.py --apply         # regenerate
    python scripts/apply_speaker_names.py --item GuestStream/GuestStream_128 --apply
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC_PREFIX = "data/video/activeinferenceinstitute"
SALVAGE_NAME = "youtube_captions.txt"


def load_blocks(tj_path: Path) -> list | None:
    """Parse transcript.json; None when absent or not whisperx block format."""
    if not tj_path.exists():
        return None
    try:
        blocks = json.loads(tj_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(blocks, list):
        return None
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("segments"), list):
            return None
        if not any(isinstance(s, dict) and s.get("speaker") for s in block["segments"]):
            return None  # no diarization — nothing to derive
    return blocks or None


def speaker_mapping(meta: dict, video_id: str) -> dict[str, str]:
    """Mapping for one video block; sess-split ids fall back to the base video."""
    base = re.sub(r"_sess\d+$", "", video_id)
    for part in meta.get("parts", []):
        if part.get("video_id") in (video_id, base):
            return part.get("speakers") or {}
    merged: dict[str, str] = {}
    for part in meta.get("parts", []):
        merged.update(part.get("speakers") or {})
    return merged


def render_block(segments: list, mapping: dict[str, str]) -> str:
    """Speaker-labeled text, grouping consecutive segments by mapped name.

    Mirrors TranscriptionService.output_text so regenerated text matches
    freshly transcribed output byte-for-byte when no names are mapped.
    """
    out, prev = "", None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = mapping.get(seg.get("speaker"), seg.get("speaker") or "UNKNOWN")
        if speaker != prev:
            out += f"\n{speaker}:\n"
            prev = speaker
        out += text + "\n\n"
    return out.strip()


def render_txt(blocks: list, meta: dict) -> tuple[str, set[str]]:
    """Full transcript.txt content + the set of unmapped labels."""
    sections, unmapped = [], set()
    for block in blocks:
        vid = block.get("video_id", "")
        mapping = speaker_mapping(meta, vid)
        unmapped |= {
            s.get("speaker")
            for s in block["segments"]
            if s.get("speaker") and s["speaker"] not in mapping
        }
        text = render_block(block["segments"], mapping)
        sections.append(text if len(blocks) == 1 else f"## {vid}\n\n{text}")
    return "\n\n".join(sections) + "\n", unmapped


def has_speaker_structure(text: str) -> bool:
    """True when the text already carries 'Label:'-style speaker lines."""
    for line in text.splitlines()[:50]:
        line = line.strip()
        if not line or line.startswith("## "):
            continue
        return bool(re.fullmatch(r"\S[^:\n]{0,78}:", line))
    return False


def process_item(item_dir: Path, meta: dict, apply: bool) -> dict | None:
    blocks = load_blocks(item_dir / "transcript.json")
    if blocks is None:
        if (item_dir / "transcript.json").exists():
            return {"action": "skip-legacy-json", "unmapped": set()}
        return None

    new_txt, unmapped = render_txt(blocks, meta)
    tx_path = item_dir / "transcript.txt"
    old_txt = tx_path.read_text(encoding="utf-8") if tx_path.exists() else None

    if old_txt == new_txt:
        return {"action": "unchanged", "unmapped": unmapped}
    if old_txt is None:
        action = "new"
    elif has_speaker_structure(old_txt) or "SPEAKER_" in old_txt[:200_000]:
        action = "update"
    else:
        action = "upgrade+salvage"

    if apply:
        if action == "upgrade+salvage":
            captions_dir = item_dir / "captions"
            captions_dir.mkdir(exist_ok=True)
            salvage = captions_dir / SALVAGE_NAME
            if not salvage.exists():
                salvage.write_text(old_txt, encoding="utf-8")
        tx_path.write_text(new_txt, encoding="utf-8")
    return {"action": action, "unmapped": unmapped}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--journal", type=Path, default=REPO.parent / "ActiveInferenceJournal")
    parser.add_argument("--item", help="single item (path relative to the source root)")
    parser.add_argument(
        "--apply", action="store_true", help="write transcript.txt (default: dry-run plan)"
    )
    args = parser.parse_args()

    root = args.journal / SRC_PREFIX
    targets = (
        [root / args.item / "metadata.json"] if args.item else sorted(root.rglob("metadata.json"))
    )

    counts: dict[str, int] = {}
    for meta_path in targets:
        if not meta_path.exists():
            print(f"no such item: {meta_path.parent}")
            return 1
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("duplicate_of"):
            continue
        result = process_item(meta_path.parent, meta, args.apply)
        if result is None:
            continue
        counts[result["action"]] = counts.get(result["action"], 0) + 1
        if result["action"] != "unchanged":
            rel = meta_path.parent.relative_to(root)
            todo = (
                f"  [unmapped: {', '.join(sorted(result['unmapped']))}]"
                if result["unmapped"] and result["action"] != "skip-legacy-json"
                else ""
            )
            print(f"{result['action']:16} {rel}{todo}")

    print(
        "\nsummary:", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nothing to do"
    )
    if not args.apply:
        print("dry run — pass --apply to write")
    else:
        print("regenerate indexes + validate before committing (see SCHEMA.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
