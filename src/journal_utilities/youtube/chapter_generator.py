"""
LLM video chapter generation with a hard quality gate.

Generates timestamped YouTube chapters from transcript segments via a local
Ollama model or OpenRouter, then validates them against the journal chapter
contract (validate_chapters). Only chapters that pass the gate — or lists
whose ``source`` is ``youtube`` (human/creator-authored upstream) — are
trusted downstream: enrich_metadata.py seeds journal ``sessions[]`` from them,
and description writes embed them.

Every generated payload carries provenance: ``{"source", "model",
"generated_at"}`` alongside the chapter list (see ``save_generated_chapters``).

Usage:
    python scripts/generate_chapters.py --video-id <id> --duration <seconds>  # via run.py wiring
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from journal_utilities.youtube.metadata_formatter import (
    ChapterEntry,
    format_seconds_to_timestamp,
)

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_OLLAMA_MODEL = "gemma3:4b"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"

CHAPTER_LINE_PATTERN = re.compile(
    r"(?:^\s*(?:\d+[\.\)]\s*)?)(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?)\s*[-–—:]?\s*(.+)$"
)

# ---------------------------------------------------------------------------
# Chapter gate contract
# ---------------------------------------------------------------------------

MIN_CHAPTERS = 3
MIN_TITLE_WORDS = 3
MAX_TITLE_WORDS = 8
MAX_TITLE_CHARS = 60
MIN_GAP_SECONDS = 10.0
MIN_COVERAGE_FRACTION = 0.8
# Generation windows: 3-5 minute blocks over the FULL transcript.
WINDOW_SECONDS_MIN = 180.0
WINDOW_SECONDS_MAX = 300.0
# Filler/hesitation tokens that must not dominate a chapter title.
FILLER_WORDS = frozenset({"uh", "um", "so", "like"})
# Bare speaker-name titles: "Karl Friston", "Karl J. Friston:" — attribution
# noise, not a searchable topic. Every token must be a strictly capitalized
# alphabetic word AND at least one token must NOT be in the stop-word list
# below; concept vocabulary ("Predictive Coding") is not a speaker. The
# stop list is calibrated against the restored YouTube chapter corpus —
# heuristic by design: a residual false-positive rate on two-word concept
# titles is acceptable, and YouTube-sourced lists bypass this gate anyway.
SPEAKER_NAME_RE = re.compile(r"^[A-Z][A-Za-z'’.-]*$")
CONCEPT_STOP_WORDS = frozenset(
    {
        "active",
        "aims",
        "ai",
        "analysis",
        "approach",
        "approximation",
        "art",
        "attractor",
        "basic",
        "bayes",
        "bayesian",
        "blankets",
        "board",
        "chapter",
        "circuit",
        "coding",
        "cognitive",
        "collective",
        "comments",
        "conclusion",
        "construction",
        "continuous",
        "derivation",
        "derive",
        "deriving",
        "discussion",
        "dynamics",
        "engineering",
        "error",
        "errors",
        "expected",
        "exploit",
        "explore",
        "field",
        "formulation",
        "frames",
        "framework",
        "frameworks",
        "free",
        "graph",
        "implications",
        "inference",
        "intelligence",
        "introduction",
        "intrinsic",
        "knowledge",
        "learning",
        "map",
        "markov",
        "matter",
        "mechanics",
        "minimization",
        "model",
        "modeling",
        "models",
        "motive",
        "networks",
        "neural",
        "niche",
        "observation",
        "part",
        "partial",
        "precision",
        "predictive",
        "prediction",
        "principle",
        "problem",
        "process",
        "processing",
        "programming",
        "python",
        "quantum",
        "question",
        "reaction",
        "reference",
        "reflection",
        "relation",
        "research",
        "road",
        "rule",
        "scale",
        "science",
        "sensing",
        "session",
        "source",
        "state",
        "states",
        "step",
        "steps",
        "structure",
        "summary",
        "surprisal",
        "synchrony",
        "systems",
        "task",
        "terminology",
        "test",
        "theorem",
        "theory",
        "thoughts",
        "time",
        "tool",
        "transformation",
        "update",
        "updates",
        "variational",
        "words",
    }
)


class ChapterError(RuntimeError):
    """Raised when generated chapters fail the quality gate after retries."""


@dataclass
class ValidationReport:
    """Result of validating one chapter list against the gate rules."""

    passed: bool = True
    failures: list[str] = field(default_factory=list)

    def add(self, rule: str, detail: str) -> None:
        self.failures.append(f"{rule}: {detail}")
        self.passed = False

    def __bool__(self) -> bool:  # convenience for `if not validate_chapters(...)`
        return self.passed


def _title_word_count(title: str) -> int:
    return len([w for w in re.split(r"[\s/|]+", title.strip()) if w])


def _strip_trailing_punctuation(title: str) -> str:
    return title.strip().strip(".,;:!?—–-\"'“”")


def _is_bare_speaker_name(title: str) -> bool:
    """True for titles that read as bare personal names.

    "Karl Friston", "Karl J. Friston" fail (attribution noise); "Karl Friston
    on Free Energy" and "Free Energy Principle with Karl Friston" are topics
    and pass. Calibrated to keep concept vocabulary out of the flag.
    """
    t = _strip_trailing_punctuation(title)
    if not t:
        return False
    tokens = t.replace("’", "'").split()
    if not 1 <= len(tokens) <= 4:
        return False
    name_like = 0
    for tok in tokens:
        if tok.lower() in CONCEPT_STOP_WORDS:
            return False  # concept word → topic, not a name
        if tok.lower() in {"with", "on", "and", "the", "of", "in", "for", "a", "an", "to"}:
            return False  # connectors imply a phrase, not a bare name
        if not SPEAKER_NAME_RE.match(tok):
            return False  # digits, lowercase words, symbols → topic
        name_like += 1
    # A personal name is at least two name-like tokens ("Karl Friston");
    # single capitalized words are ordinary title words ("Matter
    # Consciousness", "Next Steps"), so they pass.
    return name_like >= 2


def validate_chapters(
    chapters: list[dict[str, Any]],
    *,
    duration_seconds: float | None,
) -> ValidationReport:
    """Validate a chapter list against the journal chapter contract.

    Rules (all must hold for the list to pass):
      - >= 3 chapters
      - first chapter starts at 0:00
      - gaps between consecutive chapters >= 10s
      - last chapter starts at >= 80% of the video duration
      - titles are 3-8 words, <= 60 characters
      - no filler-word titles (uh, um, so, like)
      - no bare speaker names as titles

    ``chapters`` entries: ``{"start": float, "title": str}`` (``start_time`` is
    also accepted, matching yt-dlp's key). ``duration_seconds`` is the total
    video duration; when None the coverage rule is skipped (cannot evaluate).
    """
    report = ValidationReport()
    if not chapters:
        report.add("count", "no chapters")
        return report

    if len(chapters) < MIN_CHAPTERS:
        report.add("count", f"{len(chapters)} chapters < minimum {MIN_CHAPTERS}")

    starts: list[float] = []
    for i, ch in enumerate(chapters):
        raw_start = ch.get("start", ch.get("start_time", 0.0))
        try:
            start = float(raw_start)
        except (TypeError, ValueError):
            report.add("start", f"chapter[{i}] non-numeric start {raw_start!r}")
            continue
        starts.append(start)

        title = str(ch.get("title", "")).strip()
        if not title:
            report.add("title", f"chapter[{i}] empty title")
            continue

        words = _title_word_count(title)
        if not (MIN_TITLE_WORDS <= words <= MAX_TITLE_WORDS):
            report.add(
                "title-words",
                f"chapter[{i}] {words} words (need {MIN_TITLE_WORDS}-{MAX_TITLE_WORDS}): {title!r}",
            )
        if len(title) > MAX_TITLE_CHARS:
            report.add(
                "title-chars",
                f"chapter[{i}] {len(title)} chars > {MAX_TITLE_CHARS}: {title!r}",
            )

        lowered = _strip_trailing_punctuation(title).lower()
        tokens = set(re.split(r"[\s/|]+", lowered))
        filler_hits = tokens & FILLER_WORDS
        if filler_hits:
            report.add(
                "filler",
                f"chapter[{i}] filler word(s) {sorted(filler_hits)}: {title!r}",
            )
        if _is_bare_speaker_name(title):
            report.add("speaker-name", f"chapter[{i}] bare speaker name: {title!r}")

    if starts:
        if starts[0] > 0.0:
            report.add("first-at-zero", f"first chapter starts at {starts[0]}, not 0:00")
        for i in range(1, len(starts)):
            gap = starts[i] - starts[i - 1]
            if gap < MIN_GAP_SECONDS:
                report.add(
                    "gap",
                    f"chapter[{i}] gap {gap:.1f}s < {MIN_GAP_SECONDS:.0f}s "
                    f"({format_seconds_to_timestamp(starts[i - 1])} -> "
                    f"{format_seconds_to_timestamp(starts[i])})",
                )

    if duration_seconds and duration_seconds > 0 and starts:
        last = starts[-1]
        if last < MIN_COVERAGE_FRACTION * duration_seconds:
            report.add(
                "coverage",
                f"last chapter at {format_seconds_to_timestamp(last)} covers only "
                f"{last / duration_seconds:.0%} of {format_seconds_to_timestamp(duration_seconds)} "
                f"(need >= {MIN_COVERAGE_FRACTION:.0%})",
            )

    return report


# ---------------------------------------------------------------------------
# Transcript windowing and generation
# ---------------------------------------------------------------------------


def parse_timestamp_to_seconds(ts_str: str) -> float | None:
    """Parse MM:SS or HH:MM:SS string to seconds."""
    parts = ts_str.strip().split(":")
    try:
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        return None
    return None


def build_windowed_transcript_text(
    transcript_segments: list[dict[str, Any]],
    window_seconds: float = WINDOW_SECONDS_MIN,
    max_chars: int = 120_000,
) -> str:
    """Render the FULL transcript as fixed-width, timestamped windows.

    Segments are bucketed into consecutive ``window_seconds`` blocks (3-5 min
    when called with the default contract); every window contributes its
    bracketed [MM:SS] start time so the model can anchor chapter timestamps.
    The result is capped at ``max_chars`` to stay inside context limits — the
    cap drops tail windows only, never the head.
    """
    if not transcript_segments:
        return ""

    lines: list[str] = []
    window_start = 0.0
    next_boundary = window_start + window_seconds
    current: list[str] = []

    def flush() -> None:
        if current:
            ts = format_seconds_to_timestamp(window_start)
            lines.append(f"[{ts}] " + " ".join(current))
            current.clear()

    for seg in transcript_segments:
        start = float(seg.get("start", 0.0))
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        while start >= next_boundary:
            flush()
            window_start = next_boundary
            next_boundary += window_seconds
        current.append(text)
    flush()

    text_block = "\n".join(lines)
    if len(text_block) > max_chars:
        text_block = text_block[:max_chars] + "\n[...remaining transcript omitted for brevity...]"
    return text_block


def downsample_transcript_segments(
    segments: list[dict[str, Any]],
    interval_seconds: float = 30.0,
    max_chars: int = 40000,
) -> str:
    """Downsample granular transcript segments into a concise time-stamped text block."""
    if not segments:
        return ""

    lines: list[str] = []
    last_time = -interval_seconds

    for seg in segments:
        start = float(seg.get("start", 0.0))
        text = str(seg.get("text", "")).strip()
        if not text:
            continue

        if start - last_time >= interval_seconds:
            ts_str = format_seconds_to_timestamp(start)
            lines.append(f"[{ts_str}] {text}")
            last_time = start

    text_block = "\n".join(lines)
    if len(text_block) > max_chars:
        text_block = text_block[:max_chars] + "\n[...remaining transcript omitted for brevity...]"
    return text_block


def calculate_optimal_chapter_count(total_duration_seconds: float | None) -> int:
    """Calculate optimal number of chapters (3-30) based on video length."""
    if not total_duration_seconds or total_duration_seconds <= 0:
        return 15  # Default balanced count

    minutes = total_duration_seconds / 60.0
    if minutes < 5:
        return MIN_CHAPTERS
    elif minutes < 20:
        return 10
    elif minutes < 45:
        return 12
    elif minutes < 90:
        return 20
    else:
        return min(30, int(minutes // 4))


def parse_llm_chapters_text(text: str) -> list[ChapterEntry]:
    """Extract and sanitize chapter entries from LLM generated response."""
    chapters: list[ChapterEntry] = []

    for line in text.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        match = CHAPTER_LINE_PATTERN.search(line_str)
        if match:
            ts_str = match.group(1).strip()
            title = match.group(2).strip()
            title = re.sub(r"[\*\_]", "", title).strip()

            secs = parse_timestamp_to_seconds(ts_str)
            if secs is not None and title:
                chapters.append(ChapterEntry(start=secs, title=title))

    if not chapters:
        return []

    # Deduplicate and sort chronologically
    chapters.sort(key=lambda c: c.start)
    unique_chapters: list[ChapterEntry] = []
    seen_times: set[float] = set()
    for c in chapters:
        if c.start not in seen_times:
            unique_chapters.append(c)
            seen_times.add(c.start)

    # Ensure starts at 00:00 (YouTube requirement)
    if unique_chapters and unique_chapters[0].start > 0:
        unique_chapters.insert(0, ChapterEntry(start=0.0, title="Introduction"))

    # Enforce chapter-count contract (cap at 30; <3 is a gate failure)
    if len(unique_chapters) > 30:
        logger.warning(
            "LLM produced %d chapters; downsampling to 30 via evenly spaced selection.",
            len(unique_chapters),
        )
        indices = sorted({round(i * (len(unique_chapters) - 1) / 29) for i in range(30)})
        indices[0] = 0  # Always keep the first (00:00) entry
        unique_chapters = [unique_chapters[i] for i in indices]
    elif 0 < len(unique_chapters) < MIN_CHAPTERS:
        logger.warning(
            "LLM produced only %d chapters; below the %d-chapter gate minimum but kept for validation.",
            len(unique_chapters),
            MIN_CHAPTERS,
        )

    return unique_chapters


def _window_plan(total_duration: float, target_count: int) -> list[float]:
    """Window widths (seconds) covering [0, total_duration].

    Evenly spaced windows in the 3-5 minute band, widened within the band so
    the window count matches the target chapter count.
    """
    if total_duration <= 0:
        return [WINDOW_SECONDS_MIN]
    count = max(1, min(target_count, int(total_duration // WINDOW_SECONDS_MIN) or 1))
    count = max(count, 1)
    width = total_duration / count
    if width > WINDOW_SECONDS_MAX:
        # Too long for one window per target chapter: cap at 5 min windows.
        width = WINDOW_SECONDS_MAX
        count = max(1, int(-(-total_duration // width)))  # ceil
    return [width] * count


class ChapterGenerator:
    """Generates high-resolution video chapters from transcripts using local or hosted LLMs."""

    def __init__(
        self,
        backend: str = "ollama",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.backend = backend.lower()
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if self.backend == "ollama":
            self.model = model or DEFAULT_OLLAMA_MODEL
            self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_URL).rstrip(
                "/"
            )
        else:
            self.model = model or DEFAULT_OPENROUTER_MODEL
            self.base_url = (
                base_url or os.getenv("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_URL
            ).rstrip("/")

    # -- prompt ------------------------------------------------------------

    def _prompt(self, title: str, windowed_text: str, target_count: int) -> str:
        return (
            f"You are an expert technical editor for the Active Inference Institute.\n"
            f"Create {target_count} clear, high-resolution YouTube video chapters with "
            f'timestamps for the session: "{title}".\n\n'
            f"CONTRACT (violations are rejected and regenerated):\n"
            f'1. The first chapter MUST be exactly "00:00 Introduction" (or a 3-8 word '
            f"description of the opening topic).\n"
            f"2. Between {max(MIN_CHAPTERS, target_count - 5)} and {target_count + 5} chapters, "
            f"marking every significant topic, speaker transition, model slide, or discussion "
            f"question; consecutive chapters must be at least 10 seconds apart.\n"
            f"3. The LAST chapter must land at or after 80% of the video's total runtime — "
            f"cover the whole video, including the closing discussion.\n"
            f"4. Timestamps strictly chronological, derived from the bracketed [MM:SS] windows "
            f"in the transcript. Format each line strictly as: MM:SS Title or HH:MM:SS Title.\n"
            f"5. Titles: descriptive, searchable topics of exactly 3-8 words, at most 60 "
            f'characters (e.g. "Markov blankets as internal states", "Deriving expected free '
            f'energy"). Never single words, bare labels ("Summary", "Conclusion", "Q&A"), '
            f'generic numbering ("Chapter 5", "Part 3"), filler words ("uh", "um", "so", '
            f'"like"), or bare personal names ("Karl Friston"). Attribute concepts, not '
            f"speakers.\n"
            f"6. Output ONLY the timestamp list — no prose, headers, or markdown fences.\n\n"
            f"TRANSCRIPT (time-windowed, full session):\n"
            f"{windowed_text}\n"
        )

    # -- generation with gate + retry --------------------------------------

    def generate_chapters(
        self,
        *,
        title: str,
        transcript_segments: list[dict[str, Any]],
        total_duration_seconds: float | None = None,
        num_chapters: int | None = None,
        max_attempts: int = 3,
    ) -> list[ChapterEntry]:
        """Generate chapters from the FULL transcript and return only gate-passing lists.

        The transcript is rendered in 3-5 minute time windows over the whole
        session; ``total_duration_seconds`` must be passed in (transcript tails
        under-report runtime). Each attempt validates against
        ``validate_chapters``; the first passing list wins. Raises
        ``ChapterError`` after ``max_attempts`` failures.
        """
        if not transcript_segments:
            logger.warning("No transcript text available to generate chapters.")
            raise ChapterError(f"no transcript segments for {title!r}")

        if total_duration_seconds is None:
            last_seg = transcript_segments[-1]
            total_duration_seconds = float(last_seg.get("end", last_seg.get("start", 0.0)))

        target_count = num_chapters or calculate_optimal_chapter_count(total_duration_seconds)
        windowed_text = build_windowed_transcript_text(transcript_segments)
        if not windowed_text:
            raise ChapterError(f"transcript for {title!r} rendered to empty text")

        prompt = self._prompt(title, windowed_text, target_count)
        report: ValidationReport | None = None
        for attempt in range(1, max_attempts + 1):
            raw = self._call(prompt)
            entries = parse_llm_chapters_text(raw)
            if not entries:
                report = report or ValidationReport(passed=False)
                report.add("parse", f"attempt {attempt}: no chapters parsed from model output")
                logger.warning(
                    "Attempt %d/%d produced no parseable chapters", attempt, max_attempts
                )
                continue

            payload = [{"start": c.start, "title": c.title} for c in entries]
            report = validate_chapters(payload, duration_seconds=total_duration_seconds)
            if report.passed:
                return entries
            logger.warning(
                "Attempt %d/%d failed the chapter gate for %s: %s",
                attempt,
                max_attempts,
                title,
                "; ".join(report.failures),
            )

        assert report is not None  # loop always runs >= 1 attempt
        raise ChapterError(
            f"chapters for {title!r} failed the gate after {max_attempts} attempts: "
            + "; ".join(report.failures)
        )

    # -- HTTP backends -------------------------------------------------------

    def _call(self, prompt: str) -> str:
        if self.backend == "ollama":
            return self._call_ollama(prompt)
        return self._call_openrouter(prompt)

    def _call_ollama(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data: Any = json.loads(resp.read().decode("utf-8"))
                response = data.get("response")
        except Exception as e:
            logger.error("Ollama chapter generation request failed: %s", e)
            raise
        return str(response) if response is not None else ""

    def _call_openrouter(self, prompt: str) -> str:
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY required for OpenRouter backend")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You generate high-resolution YouTube chapters with exact "
                    "timestamps from transcripts.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "journal-youtube-chapters",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data: Any = json.loads(resp.read().decode("utf-8"))
                choices: Any = data.get("choices", [])
                if choices:
                    message: Any = choices[0].get("message", {})
                    content = message.get("content")
        except Exception as e:
            logger.error("OpenRouter chapter generation request failed: %s", e)
            raise
        return str(content) if content is not None else ""


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------


def generation_provenance(model: str, generated_at: datetime | None = None) -> dict[str, str]:
    """Standard provenance block for generated chapter payloads."""
    return {
        "source": "llm",
        "model": model,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
    }


def save_generated_chapters(
    cache_path: str,
    video_id: str,
    chapters: list[ChapterEntry],
    *,
    model: str,
    generated_at: datetime | None = None,
) -> None:
    """Write a provenance-carrying entry into the LLM chapters cache.

    Writes to the LLM cache file (``*_llm.json``) only — never the
    YouTube-sourced ``video_chapters.json``. Existing YouTube-sourced entries
    in the target file are never overwritten.
    """
    path = os.fspath(cache_path)
    cache: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            cache = loaded
    if video_id in cache and cache[video_id].get("source") == "youtube":
        raise ValueError(f"refusing to overwrite YouTube-sourced chapters for {video_id} in {path}")
    cache[video_id] = {
        "source": "llm",
        "model": model,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "chapters": [{"start": c.start, "title": c.title} for c in chapters],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
