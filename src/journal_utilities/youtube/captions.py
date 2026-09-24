"""Derive uploadable SRT captions from journal ``transcript.json``.

WhisperX ``transcript.json`` is a list of blocks, one per video part::

    [{"video_id": "N5H5I6cvcrQ",
      "segments": [{"start": 4.537, "end": 5.218, "text": " Excellent.",
                    "speaker": "SPEAKER_00",
                    "words": [...]}]},
     ...]

This module turns one block into a human-quality SRT for the captions.upload
pipeline (M5):

- real formatting: ``HH:MM:SS,mmm`` timestamps, cues wrapped to at most two
  lines of 42 characters (Netflix-style), speaker labels rendered when the
  speaker changes (mapped names from metadata ``parts[].speakers``; unmapped
  ``SPEAKER_NN`` is humanized to ``Speaker N``);
- long text is split across sequential cues with time proportional to the
  character share, so no cue ever exceeds the two-line budget;
- speaker mapping follows ``scripts/apply_speaker_names.py`` semantics
  (``_sessNN``-suffixed video ids fall back to the base video; missing
  mapping merges all parts).

The journal is the source of truth: nothing here calls the YouTube Data API.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Maximum characters per caption line and per cue (two lines).
MAX_LINE_CHARS = 42
MAX_CUE_LINES = 2

_SPEAKER_RE = re.compile(r"SPEAKER_(\d+)$")
_SESS_SUFFIX_RE = re.compile(r"_sess\d+$")
# Speaker label rendered before text on a speaker change, e.g. "Karl Friston:".
_LABEL_RE = re.compile(r"^\S[^:\n]{0,78}:")


def _srt_timestamp(seconds: float) -> str:
    """Format float seconds as SRT ``HH:MM:SS,mmm``."""
    seconds = max(0.0, seconds)
    # Round to milliseconds FIRST, then decompose — ms rounding can carry
    # into the seconds/minutes digits (e.g. 59.9996 -> 00:01:00,000).
    total_ms = round(seconds * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clean_text(text: str) -> str:
    """Normalize a segment for captions: strip BOM, collapse whitespace."""
    return " ".join(text.replace("\ufeff", "").replace("\x00", " ").split())


def humanize_speaker(raw: str) -> str:
    """``SPEAKER_00`` -> ``Speaker 0``; anything else passes through."""
    match = _SPEAKER_RE.match(raw)
    if match:
        return f"Speaker {int(match.group(1))}"
    return raw


def speaker_mapping(meta: dict[str, Any], video_id: str) -> dict[str, str]:
    """Mapping for one video block; ``_sessNN`` ids fall back to the base video.

    Mirrors ``scripts/apply_speaker_names.py``: find the part matching the
    video id (or its base id without the session suffix); when no part matches,
    merge every part's mapping.
    """
    parts = meta.get("parts", []) if isinstance(meta, dict) else []
    base = _SESS_SUFFIX_RE.sub("", video_id)
    for part in parts:
        if isinstance(part, dict) and part.get("video_id") in (video_id, base):
            return dict(part.get("speakers") or {})
    merged: dict[str, str] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part.get("speakers") or {})
    return merged


def wrap_lines(text: str, width: int = MAX_LINE_CHARS) -> list[str]:
    """Word-wrap text into lines of at most ``width`` characters."""
    text = clean_text(text)
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            # A single word longer than ``width`` is hard-split below.
            if not current and len(word) > width:
                # consume the long word in width-sized chunks
                for i in range(0, len(word), width):
                    chunk = word[i : i + width]
                    if i + width < len(word):
                        lines.append(chunk)
                    else:
                        current = chunk
                continue
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_cues(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert transcript segments to timed cues with speaker-change labels.

    Returns dicts ``{start, end, lines}`` where ``lines`` is at most
    ``MAX_CUE_LINES`` strings of at most ``MAX_LINE_CHARS`` characters.
    Segments whose wrapped text needs more lines are split into sequential
    cues; the split duration is proportional to character share.
    """
    cues: list[dict[str, Any]] = []
    prev_speaker: str | None = None
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = clean_text(str(seg.get("text", "")))
        if not text:
            continue
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 1.0
        speaker = seg.get("speaker")
        label = None
        if speaker and speaker != prev_speaker:
            label = humanize_speaker(str(speaker))
        prev_speaker = speaker

        raw = f"{label}: {text}" if label else text
        lines = wrap_lines(raw)
        if not lines:
            continue

        for i in range(0, len(lines), MAX_CUE_LINES):
            cue_lines = lines[i : i + MAX_CUE_LINES]
            # proportional split of the segment duration across cue chunks
            char_total = sum(len(ln) for ln in lines) + len(lines)
            char_before = sum(len(ln) for ln in lines[:i]) + i
            char_chunk = sum(len(ln) for ln in cue_lines) + len(cue_lines)
            cue_start = start + (end - start) * (char_before / char_total)
            cue_end = start + (end - start) * ((char_before + char_chunk) / char_total)
            cues.append(
                {"start": cue_start, "end": max(cue_end, cue_start + 0.1), "lines": cue_lines}
            )
    return cues


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    """Render timed cues as standard SRT text (LF line endings, no BOM)."""
    cues = build_cues(segments)
    out: list[str] = []
    for idx, cue in enumerate(cues, 1):
        out.append(str(idx))
        out.append(f"{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}")
        out.extend(cue["lines"])
        out.append("")
    if not out:
        return ""
    return "\n".join(out)


def load_blocks(transcript_path: Path) -> list[dict[str, Any]] | None:
    """Parse a whisperx block-format ``transcript.json``; ``None`` if absent/other."""
    if not transcript_path.is_file():
        return None
    try:
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, list):
        return None
    return [b for b in data if isinstance(b, dict) and isinstance(b.get("segments"), list)]


def segments_for_video(blocks: list[dict[str, Any]] | None, video_id: str) -> list[dict[str, Any]]:
    """Segments for one part; ``_sessNN`` suffix falls back to the base id."""
    if not blocks:
        return []
    base = _SESS_SUFFIX_RE.sub("", video_id)
    for block in blocks:
        if block.get("video_id") in (video_id, base):
            return list(block.get("segments") or [])
    return []


def derive_srt_for_video(
    item_dir: Path, video_id: str, *, width: int = MAX_LINE_CHARS
) -> str | None:
    """Derive the uploadable SRT for one part of a journal item.

    Reads ``item_dir/transcript.json`` and ``item_dir/metadata.json`` (for
    speaker names). Returns ``None`` when the transcript is missing, is not
    whisperx block format, or has no segments for ``video_id``.
    """
    blocks = load_blocks(item_dir / "transcript.json")
    segments = segments_for_video(blocks, video_id)
    if not segments:
        return None
    meta: dict[str, Any] = {}
    meta_path = item_dir / "metadata.json"
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except (json.JSONDecodeError, OSError):
            logger.warning("Unreadable metadata.json in %s; speaker names skipped.", item_dir)
    mapping = speaker_mapping(meta, video_id)
    # Apply mapped names before rendering; humanize what stays unmapped.
    named: list[dict[str, Any]] = []
    for seg in segments:
        seg = dict(seg) if isinstance(seg, dict) else {}
        raw_speaker = seg.get("speaker")
        if raw_speaker:
            seg["speaker"] = mapping.get(raw_speaker, humanize_speaker(str(raw_speaker)))
        named.append(seg)
    _ = width  # width is fixed at MAX_LINE_CHARS for journal caption standards
    return segments_to_srt(named)


def is_speaker_change_line(line: str) -> bool:
    """True when ``line`` starts with a ``Label:`` speaker-change prefix."""
    return bool(_LABEL_RE.match(line.strip()))
