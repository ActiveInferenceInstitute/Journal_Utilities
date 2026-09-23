"""
YouTube video description and chapter formatter for Journal Utilities.

Combines:
- Paper citation & abstract information (already in video description)
- Formatted chapter timestamps (e.g. 00:00 Introduction) inserted between abstract and link block
- GitHub repository transcript & resource links
- Standard canonical Active Inference Institute link block

Generates clean, idempotent descriptions suitable for updating via YouTube Data API.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

CHAPTERS_MARKER_START = "--- TIMESTAMPS & CHAPTERS ---"
CHAPTERS_MARKER_END = "--- RESOURCES & TRANSCRIPT ---"
INSTITUTE_MARKER_START = "--- ACTIVE INFERENCE INSTITUTE ---"

JOURNAL_GITHUB_TREE_BASE = (
    "https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/tree/main"
)

STANDARD_INSTITUTE_LINKBLOCK = """Active Inference Institute information:
Website: https://www.activeinference.institute/
Activities: https://activities.activeinference.institute/
Discord: https://discord.activeinference.institute/
Donate: http://donate.activeinference.institute/
YouTube: https://www.youtube.com/c/ActiveInference/
X: https://x.com/InferenceActive
Active Inference Livestreams: https://video.activeinference.institute/""".strip()


def format_seconds_to_timestamp(seconds: float | int) -> str:
    """Convert duration in seconds to standard YouTube timestamp (MM:SS or HH:MM:SS)."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# Characters YouTube rejects in descriptions: control chars except tab/newline,
# plus other known-problematic codepoints.
_YT_REPLACEMENTS = {
    "\u000b": " ",  # vertical tab
    "\u000c": " ",  # form feed
    "\u00a0": " ",  # nbsp
    "\u200b": "",  # zero-width space
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",  # BOM
}


def sanitize_for_youtube(text: str) -> str:
    """Strip control characters, angle brackets, and invalid Unicode YouTube rejects from a description.

    YouTube unconditionally rejects raw '<' and '>' characters in metadata snippets.
    Keeps newlines and tabs; removes other control characters and replaces
    invisible characters that trigger invalidDescription.
    """
    # Replace literal angle brackets that cause invalidDescription
    text = text.replace("<", "[").replace(">", "]")
    out: list[str] = []
    for ch in text:
        if ch in ("\n", "\t", "\r"):
            out.append(ch)
            continue
        code = ord(ch)
        if code < 32 or code == 127:
            out.append(" ")
            continue
        if 128 <= code <= 159:  # C1 controls
            out.append(" ")
            continue
        out.append(_YT_REPLACEMENTS.get(ch, ch))
    cleaned = "".join(out)
    # Collapse runs of blank-space-only lines left by removals, trim trailing junk.
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    return cleaned.strip()


@dataclass
class ChapterEntry:
    """Represents a single video chapter / timestamp entry."""

    start: float  # seconds
    title: str

    def to_youtube_line(self) -> str:
        ts = format_seconds_to_timestamp(self.start)
        return f"{ts} {self.title.strip()}"


def build_journal_item_url(item_path: str) -> str:
    """Build the GitHub tree URL for a journal item directory (``INDEX.json`` items[].path).

    This is the per-item source tree (metadata, transcripts, captions) — never a
    guessed ``blob/main/transcripts/<video_id>.md`` path, which does not exist.
    """
    return f"{JOURNAL_GITHUB_TREE_BASE}/{item_path}"


def build_video_item_index(index_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map every video ID in journal ``INDEX.json`` items[].parts to its item record."""
    index: dict[str, dict[str, Any]] = {}
    for item in index_items:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        for video_id in item.get("parts") or []:
            if isinstance(video_id, str) and video_id:
                index[video_id] = item
    return index


def resolve_video_journal_url(
    video_id: str,
    video_item_index: dict[str, dict[str, Any]],
    *,
    has_transcript: bool | None = None,
) -> str | None:
    """Resolve a video ID to its journal item tree URL, or ``None`` if unmapped.

    ``has_transcript`` overrides the item's INDEX flag when given; the link is
    only emitted for items the INDEX marks as having a transcript.
    """
    item = video_item_index.get(video_id)
    if item is None or not item.get("path"):
        return None
    if has_transcript is None:
        has_transcript = bool(item.get("has_transcript"))
    if not has_transcript:
        return None
    return build_journal_item_url(str(item["path"]))


def format_chapters_block(chapters: Sequence[ChapterEntry | dict[str, Any]]) -> str:
    """Format a list of chapters into YouTube-compliant description lines."""
    if not chapters:
        return ""

    parsed: list[ChapterEntry] = []
    for c in chapters:
        if isinstance(c, ChapterEntry):
            parsed.append(c)
        elif isinstance(c, dict):
            raw_start = c.get("start", c.get("start_time"))
            start = float(raw_start) if raw_start is not None else 0.0
            title = str(c.get("title", "")).strip()
            if title:
                parsed.append(ChapterEntry(start=start, title=title))

    parsed.sort(key=lambda x: x.start)
    if parsed and parsed[0].start > 0:
        parsed.insert(0, ChapterEntry(start=0.0, title="Introduction"))

    lines = [c.to_youtube_line() for c in parsed]
    return "\n".join(lines)


_TIMESTAMP_LINE_RE = re.compile(r"^\s*(\d{1,2}:){1,2}\d{2}\s+")


def _strip_timestamp_runs(text: str, min_run: int = 3) -> str:
    """Remove runs of >= min_run consecutive legacy timestamp/chapter lines.

    Legacy descriptions sometimes embed a full chapter list (lines like
    '00:00 Introduction'). Stripping such runs keeps assemble_video_description
    idempotent: the freshly generated --- TIMESTAMPS & CHAPTERS --- block is the
    only timestamp list in the assembled description.
    """
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if _TIMESTAMP_LINE_RE.match(lines[i]):
            j = i
            while j < n and _TIMESTAMP_LINE_RE.match(lines[j]):
                j += 1
            if j - i >= min_run:
                i = j
                continue
            out.extend(lines[i:j])
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def split_base_description(description: str) -> tuple[str, str]:
    """Split existing YouTube description into (abstract_or_paper_info, links_or_footer).

    Finds where institute info / links block begins so timestamps can be inserted
    seamlessly between the paper's abstract/metadata and the link block.
    """
    if not description:
        return "", ""

    # Canonical assembly markers are checked first so re-assembly of an
    # already-assembled description cuts at the generated structure rather
    # than the trailing institute block (which would keep stale timestamps
    # and resource lines in paper_info and duplicate them).
    link_header_patterns = [
        r"(?i)\n*---\s*TIMESTAMPS",
        r"(?i)\n*---\s*RESOURCES",
        r"(?i)\n*---\s*ACTIVE INFERENCE",
        r"(?i)\n*(?:---+\s*)?(?:Active Inference Institute (?:information|links):?|Follow us:|Links & Resources:?)",
        r"(?i)\n*Website:\s*https?://",
    ]

    for pat in link_header_patterns:
        match = re.search(pat, description)
        if match:
            paper_info = _strip_timestamp_runs(description[: match.start()]).strip()
            link_block = description[match.start() :].strip()
            return paper_info, link_block

    return _strip_timestamp_runs(description).strip(), ""


def assemble_video_description(
    *,
    base_description: str = "",
    chapters: Sequence[ChapterEntry | dict[str, Any]] | None = None,
    github_transcript_url: str | None = None,
    slides_url: str | None = None,
    coda_url: str | None = None,
    category: str = "",
    series: str = "",
) -> str:
    """Assemble a complete, structured YouTube video description.

    Structure:
    1. Paper metadata / Abstract (preserved verbatim)
    2. Timestamps & Chapters (inserted right below abstract)
    3. Resources & GitHub Full Transcript links
    4. Canonical Active Inference Institute link block
    """
    sections: list[str] = []

    # 1. Paper metadata & abstract
    paper_info, _ = split_base_description(base_description)
    if paper_info:
        sections.append(paper_info)

    # 2. Timestamps & Chapters (inserted between abstract and links)
    if chapters:
        chapters_text = format_chapters_block(chapters)
        if chapters_text:
            sections.append(f"{CHAPTERS_MARKER_START}\n{chapters_text}")

    # 3. Resources & Transcript Links
    res_lines: list[str] = []
    if github_transcript_url:
        res_lines.append(f"📄 Full Transcript on GitHub:\n{github_transcript_url}")
    if slides_url:
        res_lines.append(f"📊 Presentation Slides:\n{slides_url}")
    if coda_url:
        res_lines.append(f"📋 Coda Workspace:\n{coda_url}")

    if res_lines:
        sections.append(f"{CHAPTERS_MARKER_END}\n" + "\n\n".join(res_lines))

    # 4. Standard updated Institute link block
    sections.append(STANDARD_INSTITUTE_LINKBLOCK)

    return sanitize_for_youtube("\n\n".join(sections))
