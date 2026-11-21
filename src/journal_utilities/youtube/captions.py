"""Generate reviewable English captions from one Journal WhisperX video part."""

from __future__ import annotations

import json
import logging
import math
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 42
MAX_CUE_LINES = 2
MAX_CUE_SECONDS = 7.0
NAME_FIXES = {
    "Carl Friston": "Karl Friston",
    "Ian McGilchrist": "Iain McGilchrist",
    "Darius Parvizi Wayne": "Darius Parvizi-Wayne",
}

_SPEAKER_RE = re.compile(r"SPEAKER_(\d+)$")
_SESS_SUFFIX_RE = re.compile(r"_sess\d+$")
_LABEL_RE = re.compile(r"^(?:>> )?\S[^:\n]{0,78}:")
_SENTENCE_END = re.compile(r"""[.!?]+["'”’\)\]]*$""")
_ABBREVIATIONS = {"dr.", "mr.", "mrs.", "ms.", "prof.", "e.g.", "i.e.", "vs."}


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float
    speaker: str | None


def srt_timestamp(seconds: float) -> str:
    """Format seconds as SRT HH:MM:SS,mmm with carry across milliseconds."""
    total_ms = round(max(0.0, seconds) * 1000)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clean_text(text: str) -> str:
    """Remove BOM/NUL and collapse whitespace."""
    return " ".join(text.replace("\ufeff", "").replace("\x00", " ").split())


def humanize_speaker(raw: str) -> str:
    """Use a readable default for a diarization label."""
    match = _SPEAKER_RE.fullmatch(raw)
    return f"Speaker {int(match.group(1))}" if match else raw


def speaker_mapping(meta: dict[str, Any], video_id: str) -> dict[str, str]:
    """Use the matching video part's reviewed speaker names."""
    parts = meta.get("parts", []) if isinstance(meta, dict) else []
    if not isinstance(parts, list):
        return {}
    mappings = {}
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("video_id"), str):
            continue
        speakers = part.get("speakers")
        mappings[part["video_id"]] = (
            {key: name for key, name in speakers.items() if isinstance(name, str) and name.strip()}
            if isinstance(speakers, dict)
            else {}
        )
    for candidate in (video_id, _SESS_SUFFIX_RE.sub("", video_id)):
        if candidate in mappings:
            return mappings[candidate]
    return {key: name for mapping in mappings.values() for key, name in mapping.items()}


def parse_name_fix(value: str) -> tuple[str, str]:
    """Parse one explicit OLD=NEW correction."""
    old, separator, new = value.partition("=")
    old, new = clean_text(old), clean_text(new)
    if not separator or not old or not new:
        raise ValueError("a name correction requires nonempty OLD=NEW text")
    return old, new


def wrap_lines(text: str, width: int = MAX_LINE_CHARS) -> list[str]:
    """Word-wrap to the requested width, including oversized unbroken words."""
    return textwrap.wrap(clean_text(text), width=width, break_on_hyphens=False)


def _correct(text: str, pattern: re.Pattern[str], fixes: dict[str, str]) -> tuple[str, bool]:
    positions_match = True

    def replace(match: re.Match[str]) -> str:
        nonlocal positions_match
        original = match.group()
        replacement = fixes[original]
        positions_match &= len(original.split()) == len(replacement.split())
        return replacement

    return pattern.sub(replace, text), positions_match


def _seconds(value: object) -> float | None:
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (ValueError, OverflowError):
        return None
    # Such a value cannot describe a video and may overflow millisecond rounding.
    return max(0.0, parsed) if math.isfinite(parsed * 1000) else None


def _speaker(raw: object, mapping: dict[str, str]) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return clean_text(mapping.get(raw, humanize_speaker(raw)))
    return None


def _timed_words(
    raw: object, original: str, corrected: str, speaker: str | None, mapping: dict[str, str]
) -> list[_Word]:
    if not isinstance(raw, list) or not raw or any(not isinstance(word, dict) for word in raw):
        return []
    tokens = [clean_text(str(word.get("word", ""))) for word in raw]
    if " ".join(tokens) != original or len(corrected.split()) != len(tokens):
        return []
    words = []
    for word, token in zip(raw, corrected.split(), strict=True):
        start = _seconds(word.get("start"))
        end = _seconds(word.get("end"))
        if start is None or end is None or end <= start:
            return []
        words.append(_Word(token, start, end, _speaker(word.get("speaker"), mapping) or speaker))
    return words


def _prefix(speaker: str | None, previous: str | None) -> str:
    return f">> {speaker}: " if speaker and speaker != previous else ""


def _split_cue(text: str, start: float, end: float, width: int) -> list[dict[str, Any]]:
    lines = wrap_lines(text, width)
    chunks = [lines[index : index + MAX_CUE_LINES] for index in range(0, len(lines), MAX_CUE_LINES)]
    sizes = [sum(len(line) + 1 for line in chunk) for chunk in chunks]
    total = sum(sizes)
    current = start
    used = 0
    cues = []
    for chunk, size in zip(chunks, sizes, strict=True):
        used += size
        boundary = start + (end - start) * (used / total)
        cues.append({"start": current, "end": boundary, "lines": chunk})
        current = boundary
    return cues


def _is_sentence_end(token: str) -> bool:
    return (
        bool(_SENTENCE_END.search(token))
        and token.casefold() not in _ABBREVIATIONS
        and not re.fullmatch(r"[A-Z]\.", token)
    )


def _word_cues(
    words: list[_Word], previous: str | None, width: int
) -> tuple[list[dict[str, Any]], str | None]:
    group = [words[0]]
    cues = []
    for word in words[1:]:
        left = group[0]
        text = _prefix(left.speaker, previous) + " ".join(w.text for w in group)
        if (
            word.speaker != left.speaker
            or _is_sentence_end(group[-1].text)
            or word.end - left.start > MAX_CUE_SECONDS
            or len(wrap_lines(f"{text} {word.text}", width)) > MAX_CUE_LINES
        ):
            cues.extend(_split_cue(text, left.start, group[-1].end, width))
            previous = left.speaker
            group = []
        group.append(word)
    left = group[0]
    text = _prefix(left.speaker, previous) + " ".join(w.text for w in group)
    cues.extend(_split_cue(text, left.start, group[-1].end, width))
    return cues, left.speaker


def build_cues(
    segments: list[dict[str, Any]],
    *,
    width: int = MAX_LINE_CHARS,
    speakers: dict[str, str] | None = None,
    name_fixes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Prefer aligned word boundaries, with segment timing as a text-preserving fallback."""
    if not 1 <= width <= MAX_LINE_CHARS:
        raise ValueError(f"caption width must be between 1 and {MAX_LINE_CHARS}")
    fixes = {**NAME_FIXES, **(name_fixes or {})}
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(fixes, key=len, reverse=True))) + r")(?!\w)"
    )
    mapping = speakers or {}
    mapping = {key: _correct(value, pattern, fixes)[0] for key, value in mapping.items()}
    cues: list[dict[str, Any]] = []
    previous: str | None = None
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            continue
        original = clean_text(segment["text"])
        if not original:
            continue
        start = _seconds(segment.get("start"))
        end = _seconds(segment.get("end"))
        if start is None or end is None or end <= start:
            continue
        text, positions_match = _correct(original, pattern, fixes)
        speaker = _speaker(segment.get("speaker"), mapping)
        words = (
            _timed_words(segment.get("words"), original, text, speaker, mapping)
            if positions_match
            else []
        )
        if words:
            aligned, previous = _word_cues(words, previous, width)
            cues.extend(aligned)
        else:
            cues.extend(_split_cue(_prefix(speaker, previous) + text, start, end, width))
            previous = speaker

    end_ms = 0
    for cue in cues:
        start_ms = max(end_ms, round(cue["start"] * 1000))
        end_ms = max(start_ms + 1, round(cue["end"] * 1000))
        cue["start"], cue["end"] = start_ms / 1000, end_ms / 1000
    return cues


def segments_to_srt(
    segments: list[dict[str, Any]],
    *,
    width: int = MAX_LINE_CHARS,
    speakers: dict[str, str] | None = None,
    name_fixes: dict[str, str] | None = None,
) -> str:
    """Render sequential cues as UTF-8-compatible, LF-separated SubRip text."""
    cues = build_cues(segments, width=width, speakers=speakers, name_fixes=name_fixes)
    out = [
        "\n".join(
            [
                str(idx),
                f"{srt_timestamp(cue['start'])} --> {srt_timestamp(cue['end'])}",
                *cue["lines"],
            ]
        )
        for idx, cue in enumerate(cues, 1)
    ]
    return "\n\n".join(out) + "\n" if out else ""


def load_blocks(transcript_path: Path) -> list[dict[str, Any]] | None:
    """Parse the Journal's per-video WhisperX block format."""
    try:
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, list):
        return None
    return [b for b in data if isinstance(b, dict) and isinstance(b.get("segments"), list)]


def segments_for_video(blocks: list[dict[str, Any]] | None, video_id: str) -> list[dict[str, Any]]:
    """Select a unique exact video block or the base for a session-suffixed ID."""
    for candidate in dict.fromkeys((video_id, _SESS_SUFFIX_RE.sub("", video_id))):
        matches = [
            block["segments"] for block in blocks or [] if block.get("video_id") == candidate
        ]
        if matches:
            return list(matches[0]) if len(matches) == 1 else []
    return []


def derive_srt_for_video(
    item_dir: Path,
    video_id: str,
    *,
    width: int = MAX_LINE_CHARS,
    name_fixes: dict[str, str] | None = None,
) -> str | None:
    """Render one Journal video part from its transcript and optional reviewer speaker map."""
    segments = segments_for_video(load_blocks(item_dir / "transcript.json"), video_id)
    if not segments:
        return None
    meta: dict[str, Any] = {}
    try:
        loaded = json.loads((item_dir / "metadata.json").read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            meta = loaded
    except FileNotFoundError:
        pass
    except (ValueError, OSError):
        logger.warning("Unreadable metadata.json in %s; speaker names skipped.", item_dir)
    return (
        segments_to_srt(
            segments, width=width, speakers=speaker_mapping(meta, video_id), name_fixes=name_fixes
        )
        or None
    )


def is_speaker_change_line(line: str) -> bool:
    """Return whether a caption line opens with a speaker label."""
    return bool(_LABEL_RE.match(line.strip()))
