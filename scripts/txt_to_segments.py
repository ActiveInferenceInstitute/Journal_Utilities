"""Convert timestamp-free plain-text transcripts into pseudo-timed segments.

Plain-text transcripts (``data/output/transcripts/<id>.txt``) carry no
timestamps. This module splits the text into ~30-second chunks (~80 words at
the default speaking rate) and assigns deterministic linear timestamps so the
result can be fed to ``ChapterGenerator`` as transcript segments.

The synthesized timings drift from real wall-clock positions by roughly
1-2 minutes per hour of speech at typical speaking rates, which is accurate
enough for topic-level chapters.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_WPM: int = 160
WORDS_PER_SEGMENT: int = 80


def parse_txt_to_segments(
    txt_path: str | Path, wpm: int = DEFAULT_WPM
) -> list[dict[str, float | str]]:
    """Split a plain-text transcript into ~30-second pseudo-timed segments.

    Args:
        txt_path: Path to a plain-text transcript file.
        wpm: Assumed speaking rate in words per minute used to derive timing.

    Returns:
        A list of ``{"text": str, "start": float, "duration": float}`` dicts,
        chronologically ordered and starting at 0.0. Empty file yields [].
    """
    raw = Path(txt_path).read_text(encoding="utf-8", errors="replace")
    normalized = re.sub(r"\s+", " ", raw).strip()
    if not normalized:
        return []

    words = normalized.split(" ")
    seconds_per_word = 60.0 / float(wpm)

    segments: list[dict[str, float | str]] = []
    start = 0.0
    for i in range(0, len(words), WORDS_PER_SEGMENT):
        chunk_words = words[i : i + WORDS_PER_SEGMENT]
        duration = round(len(chunk_words) * seconds_per_word, 3)
        segments.append(
            {
                "text": " ".join(chunk_words),
                "start": round(start, 3),
                "duration": duration,
            }
        )
        start += duration
    return segments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a plain-text transcript into pseudo-timed segment JSON."
    )
    parser.add_argument("input", help="Path to the plain-text transcript (.txt)")
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Optional output JSON path (defaults to printing to stdout)",
    )
    parser.add_argument(
        "--wpm", type=int, default=DEFAULT_WPM, help="Speaking rate in words per minute"
    )
    args = parser.parse_args(argv)

    segments = parse_txt_to_segments(args.input, wpm=args.wpm)
    payload = json.dumps(segments, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
