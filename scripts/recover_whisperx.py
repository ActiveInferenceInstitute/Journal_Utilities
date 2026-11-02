#!/usr/bin/env python3
"""
Recover pre-reorg WhisperX transcripts from journal git history.

Before the June 2026 reorg, speaker-diarized WhisperX outputs lived as
``<item>.<part>_<video_id>.simple.txt/.json`` under per-item ``Metadata/``
folders. The reorg kept YouTube captions as ``transcript.txt`` and dropped
those outputs from the working tree — but they survive in git history.

This script extracts them from a pre-reorg commit and writes them per the
raw/derived transcript design:

- ``transcript.json`` — immutable raw diarization (``SPEAKER_NN``), an array
  of ``{"video_id", "segments"}`` blocks
- ``transcript.txt`` — speaker-labeled text (``SPEAKER_NN`` until names are
  mapped via ``parts[].speakers`` + apply_speaker_names.py)

Only caption-only items fully covered by whole-video outputs are written.
Items that are partial, already diarized, session-split, or already carry a
root transcript.json are reported and skipped. Extracted blobs are cached in
--work-dir (same layout as transcribe_worklist's cache).

Usage:
    python scripts/recover_whisperx.py                 # dry run: show plan
    python scripts/recover_whisperx.py --apply         # write into the journal
    python scripts/recover_whisperx.py --item "GuestStream/GuestStream_040"
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

SRC_PREFIX = "data/video/activeinferenceinstitute"
PRE_REORG_COMMIT = "9da92662668f9cbc063b8aaeb0f3d40aad0bed00"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def git_show(journal: Path, commit: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(journal), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def index_old_outputs(journal: Path, commit: str) -> dict[str, dict]:
    """Map video_id -> {"txt": path, "json": path} for whole-video outputs.

    Session-split files (``<video_id>_sessNN``) are ignored — every item they
    cover is already diarized in the current tree.
    """
    listing = subprocess.run(
        ["git", "-C", str(journal), "ls-tree", "-r", "--name-only", commit],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    index: dict[str, dict] = {}
    for path in listing:
        m = re.match(r"(.+)\.simple\.(txt|json)$", path)
        if not m:
            continue
        stem, ext = m.groups()
        if re.search(r"_sess\d+$", stem):
            continue
        if stem.endswith("]") and "[" in stem:
            vid = stem[stem.rindex("[") + 1 : -1]
        else:
            vid = stem[-11:]
        if not VIDEO_ID.fullmatch(vid):
            continue
        index.setdefault(vid, {})[ext] = path
    return {v: p for v, p in index.items() if "txt" in p and "json" in p}


def plan_items(journal: Path, old: dict[str, dict], only_item: str = "") -> list[dict]:
    """Classify every non-duplicate item against the recovered outputs."""
    from transcription_status import item_status

    plan = []
    for meta_path in sorted((journal / SRC_PREFIX).rglob("metadata.json")):
        item_dir = meta_path.parent
        rel = str(item_dir.relative_to(journal / SRC_PREFIX))
        if only_item and rel != only_item:
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("duplicate_of"):
            continue
        status = item_status(item_dir)
        vids = [p["video_id"] for p in meta.get("parts", []) if p.get("video_id")]
        have = [v for v in vids if v in old]
        if status != "captions_only":
            action = f"skip ({status})" if have else None
        elif not have:
            action = None
        elif len(have) < len(vids):
            action = f"skip (partial: {len(have)}/{len(vids)} parts recovered)"
        elif (item_dir / "transcript.json").exists():
            action = "skip (transcript.json already present)"
        else:
            action = "recover"
        if action:
            plan.append({"rel": rel, "dir": item_dir, "vids": vids, "action": action})
    return plan


def extract_to_cache(
    journal: Path, commit: str, old: dict[str, dict], vid: str, work_dir: Path
) -> None:
    for ext in ("txt", "json"):
        dest = work_dir / f"{vid}.simple.{ext}"
        if dest.exists():
            continue
        content = git_show(journal, commit, old[vid][ext])
        if ext == "json":
            segments = json.loads(content)
            if not any(seg.get("speaker") for seg in segments):
                raise ValueError(f"{old[vid]['json']}: no speaker fields")
        elif "SPEAKER_" not in content:
            raise ValueError(f"{old[vid]['txt']}: no SPEAKER_ labels")
        dest.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--journal", type=Path, default=REPO.parent / "ActiveInferenceJournal")
    parser.add_argument(
        "--commit", default=PRE_REORG_COMMIT, help="pre-reorg commit holding the *.simple.* outputs"
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=REPO / "data/output/whisperx-recovered",
        help="cache for extracted per-video outputs",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write into the journal (default: dry-run plan)"
    )
    parser.add_argument("--item", default="", help="single item (path relative to source root)")
    args = parser.parse_args()

    old = index_old_outputs(args.journal, args.commit)
    print(f"whole-video WhisperX outputs at {args.commit[:7]}: {len(old)}")

    plan = plan_items(args.journal, old, args.item)
    recover = [p for p in plan if p["action"] == "recover"]
    skipped = [p for p in plan if p["action"] != "recover"]
    print(f"recoverable items: {len(recover)}   skipped-with-coverage: {len(skipped)}\n")
    for p in skipped:
        print(f"  {p['action']:48}  {p['rel']}")
    for p in recover:
        print(f"  recover ({len(p['vids'])} video(s))                              {p['rel']}")

    if not args.apply:
        print("\ndry run — pass --apply to write transcript.json/.txt into the journal")
        return 0

    from transcribe_worklist import write_journal_transcript

    args.work_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for p in recover:
        try:
            for vid in p["vids"]:
                extract_to_cache(args.journal, args.commit, old, vid, args.work_dir)
            write_journal_transcript(p["dir"], p["vids"], args.work_dir)
            done += 1
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            print(f"FAILED {p['rel']}: {exc}")
    print(
        f"\nwritten: {done}/{len(recover)} items — review the journal diff, "
        "then regenerate indexes + validate before committing"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
