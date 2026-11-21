#!/usr/bin/env python3
"""Render one English SRT from a Journal item directory for review."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from journal_utilities.youtube.captions import derive_srt_for_video, load_blocks, parse_name_fix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", type=Path, help="Journal directory containing transcript.json")
    parser.add_argument("--video-id", help="Exact video ID, required when there are multiple parts")
    parser.add_argument(
        "--fix", action="append", default=[], help="Repeatable OLD=NEW name correction"
    )
    parser.add_argument("--out", type=Path, help="Write to a new SRT file. Default is stdout.")
    args = parser.parse_args(argv)
    try:
        fixes = dict(parse_name_fix(value) for value in args.fix)
        video_id = args.video_id
        if video_id is None:
            ids = {
                block["video_id"]
                for block in load_blocks(args.item / "transcript.json") or []
                if isinstance(block.get("video_id"), str) and block["video_id"]
            }
            if len(ids) != 1:
                parser.error("--video-id is required when there is no unique transcript part")
            video_id = ids.pop()
        srt = derive_srt_for_video(args.item, video_id, name_fixes=fixes)
        if not srt:
            parser.error("no usable WhisperX transcript for the selected part")
        payload = srt.encode("utf-8")
        if args.out:
            with args.out.open("xb") as stream:
                stream.write(payload)
            print(f"{video_id} SHA-256 {hashlib.sha256(payload).hexdigest()}", file=sys.stderr)
        else:
            sys.stdout.buffer.write(payload)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
