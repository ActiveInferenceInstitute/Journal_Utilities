#!/usr/bin/env python3
"""
Print identification cues for unmapped speakers in a journal item.

For each SPEAKER_NN in transcript.json: first appearance, the longest
utterance (best moment to identify someone — first appearances are often
one-word interjections), total talk time, and clickable YouTube links that
jump straight to those timestamps (&t=Ns). Watch, note who it is, record
{"SPEAKER_NN": "Name"} in the part's ``speakers`` in metadata.json, then run
apply_speaker_names.py --apply.

Already-mapped labels are shown with their names for reference.

Usage:
    python scripts/speaker_cues.py --item TextbookGroup/Namjoshi2026/Cohort_1/Session_024
    python scripts/speaker_cues.py            # list items that still need mapping
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

SRC_PREFIX = "data/video/activeinferenceinstitute"


def mmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cues_for_item(item_dir: Path, meta: dict) -> None:
    from apply_speaker_names import load_blocks, speaker_mapping

    blocks = load_blocks(item_dir / "transcript.json")
    if blocks is None:
        print("  no whisperx transcript.json — nothing to map")
        return
    for block in blocks:
        vid = block.get("video_id", "")
        base = re.sub(r"_sess\d+$", "", vid)
        mapping = speaker_mapping(meta, vid)
        stats: dict[str, dict] = {}
        for seg in block["segments"]:
            label = seg.get("speaker")
            text = (seg.get("text") or "").strip()
            if not label or not text:
                continue
            dur = (seg.get("end") or 0) - (seg.get("start") or 0)
            st = stats.setdefault(label, {"first": seg, "longest": seg, "talk": 0.0})
            st["talk"] += max(dur, 0)
            if dur > ((st["longest"].get("end") or 0) - (st["longest"].get("start") or 0)):
                st["longest"] = seg
        print(f"\n  video {vid}  https://www.youtube.com/watch?v={base}")
        for label in sorted(stats):
            st = stats[label]
            name = f"  -> {mapping[label]}" if label in mapping else "  (unmapped)"
            first, longest = st["first"], st["longest"]
            snippet = (longest.get("text") or "").strip()[:90]
            print(f"    {label}{name}   talk {mmss(st['talk'])}")
            print(
                f"      first   {mmss(first['start']):>8}  "
                f"https://www.youtube.com/watch?v={base}&t={int(first['start'])}s"
            )
            print(
                f"      longest {mmss(longest['start']):>8}  "
                f"https://www.youtube.com/watch?v={base}&t={int(longest['start'])}s"
                f'  "{snippet}"'
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--journal", type=Path, default=REPO.parent / "ActiveInferenceJournal")
    parser.add_argument("--item", help="item path relative to the source root")
    args = parser.parse_args()

    from apply_speaker_names import load_blocks, render_txt

    root = args.journal / SRC_PREFIX
    if args.item:
        meta_path = root / args.item / "metadata.json"
        if not meta_path.exists():
            print(f"no such item: {meta_path.parent}")
            return 1
        print(args.item)
        cues_for_item(meta_path.parent, json.loads(meta_path.read_text(encoding="utf-8")))
        return 0

    print("items with unmapped speakers (pass --item for cues):")
    for meta_path in sorted(root.rglob("metadata.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("duplicate_of"):
            continue
        blocks = load_blocks(meta_path.parent / "transcript.json")
        if blocks is None:
            continue
        _, unmapped = render_txt(blocks, meta)
        if unmapped:
            rel = meta_path.parent.relative_to(root)
            print(f"  {rel}  ({len(unmapped)} unmapped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
