"""
Multi-format transcript exporter for Journal Utilities.

Exports transcripts from ``data/output/transcripts/`` to plaintext, PDF,
Markdown (with YAML frontmatter), JSON, and standalone HTML.

When a ``data_dir`` is provided, video metadata (title, category, series,
episode, speakers, duration, URL, views) is loaded from
``channel_videos.json`` and included in every export header.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ExportFormat(str, Enum):
    """Supported export formats."""

    PLAINTEXT = "plaintext"
    PDF = "pdf"
    MARKDOWN = "markdown"
    JSON = "json"
    HTML = "html"


@dataclass
class ExportResult:
    """Result of a single export operation."""

    source_path: str
    format: ExportFormat
    status: str  # "success", "skipped", "failed"
    output_path: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    file_size_bytes: int | None = None

    @property
    def file_size_str(self) -> str:
        """Return human-readable file size."""
        if self.file_size_bytes is None:
            return ""
        size = float(self.file_size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _file_size(path: Path) -> int:
    """Get file size in bytes, returning 0 on error."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _stem_to_title(stem: str) -> str:
    """Derive a human-readable title from a filename stem.

    YouTube IDs are passed through as-is; anything that looks like a
    slug (contains hyphens or underscores) is title-cased.
    """
    if re.match(r"^[A-Za-z0-9_-]{11}$", stem):
        return stem  # YouTube video ID
    return stem.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------


def _load_video_index(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Load ``channel_videos.json`` and return a dict keyed by video ID.

    Returns an empty dict if the file is missing or malformed.
    """
    path = data_dir / "channel_videos.json"
    if not path.exists():
        logger.debug("No channel_videos.json found at %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        videos = data.get("videos", []) if isinstance(data, dict) else data
        index: dict[str, dict[str, Any]] = {}
        for v in videos:
            if isinstance(v, dict) and "id" in v:
                index[v["id"]] = v
        logger.info("Loaded video index with %d entries", len(index))
        return index
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Could not load video index: %s", exc)
        return {}


def _extract_speakers(title: str) -> list[str]:
    """Extract speaker names from a video title.

    Convention: text after ``~`` contains the speaker/topic description.
    Handles patterns like ``Stream 013.1 ~ Speaker: "Topic"``.
    """
    if "~" not in title:
        return []
    after_tilde = title.split("~", 1)[1].strip()
    # Strip quoted subtitles
    after_tilde = re.sub(r'["\u201c\u201d].+?["\u201c\u201d]', "", after_tilde).strip()
    # Remove leading/trailing colons and commas
    after_tilde = after_tilde.strip(":,").strip()
    if not after_tilde:
        return []
    # Split on " and " or ", " for multi-speaker titles
    speakers = re.split(r"\s+and\s+|,\s*", after_tilde)
    return [s.strip() for s in speakers if s.strip()]


def _format_duration(seconds: int | float | None) -> str:
    """Convert seconds to ``H:MM:SS`` or ``M:SS`` format."""
    if not seconds or seconds <= 0:
        return ""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _build_metadata(video_id: str, video_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build a metadata dict for the given video ID from the index."""
    info = video_index.get(video_id, {})
    if not info:
        return {}

    title = info.get("title", "")
    meta: dict[str, Any] = {"title": title}

    # Category / series / episode from categorizer
    try:
        from journal_utilities.youtube.categorizer import categorize_name

        cat, series, episode = categorize_name(title, is_unique_event_name=False)
        if cat:
            meta["category"] = cat
        if series:
            meta["series"] = series
        if episode:
            meta["episode"] = episode
    except Exception:  # noqa: BLE001
        pass

    speakers = _extract_speakers(title)
    if speakers:
        meta["speakers"] = speakers

    duration_str = _format_duration(info.get("duration"))
    if duration_str:
        meta["duration"] = duration_str

    url = info.get("url", "")
    if url:
        meta["url"] = url

    views = info.get("view_count")
    if views is not None:
        meta["views"] = views

    upload_date = info.get("upload_date", "")
    if upload_date:
        meta["date"] = upload_date

    return meta


# ---------------------------------------------------------------------------
# Format converters
# ---------------------------------------------------------------------------


def _to_plaintext(
    text: str, dest: Path, title: str = "", metadata: dict[str, Any] | None = None
) -> None:
    """Write clean plaintext with an optional metadata header."""
    lines: list[str] = []
    meta = metadata or {}
    display_title = meta.get("title", title)
    if display_title:
        lines.append(display_title)
        lines.append("=" * len(display_title))
    header_parts: list[str] = []
    if meta.get("category"):
        header_parts.append(f"Category: {meta['category']}")
    if meta.get("series"):
        ep = f" (Episode {meta['episode']})" if meta.get("episode") else ""
        header_parts.append(f"Series: {meta['series']}{ep}")
    if meta.get("speakers"):
        header_parts.append(f"Speakers: {', '.join(meta['speakers'])}")
    if meta.get("duration"):
        header_parts.append(f"Duration: {meta['duration']}")
    if meta.get("url"):
        header_parts.append(f"URL: {meta['url']}")
    if header_parts:
        lines.extend(header_parts)
        lines.append("")
    lines.append(text.strip())
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yaml_escape(value: str) -> str:
    """Escape a value for a double-quoted YAML scalar.

    Titles and other metadata routinely contain quotes, backslashes, or
    newlines — without escaping these the markdown export's YAML frontmatter
    is malformed and downstream parsers mis-read it.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _to_markdown(
    text: str, dest: Path, title: str = "", metadata: dict[str, Any] | None = None
) -> None:
    """Write Markdown with YAML frontmatter metadata."""
    now = datetime.now(UTC).isoformat()
    meta = metadata or {}
    display_title = meta.get("title", title)

    fm_lines = [
        "---",
        f'title: "{_yaml_escape(str(display_title))}"',
    ]
    if meta.get("category"):
        fm_lines.append(f'category: "{_yaml_escape(str(meta["category"]))}"')
    if meta.get("series"):
        fm_lines.append(f'series: "{_yaml_escape(str(meta["series"]))}"')
    if meta.get("episode"):
        fm_lines.append(f'episode: "{_yaml_escape(str(meta["episode"]))}"')
    if meta.get("speakers"):
        fm_lines.append("speakers:")
        for speaker in meta["speakers"]:
            fm_lines.append(f'  - "{_yaml_escape(str(speaker))}"')
    if meta.get("duration"):
        fm_lines.append(f'duration: "{_yaml_escape(str(meta["duration"]))}"')
    if meta.get("url"):
        fm_lines.append(f'url: "{_yaml_escape(str(meta["url"]))}"')
    if meta.get("views") is not None:
        fm_lines.append(f"views: {meta['views']}")
    if meta.get("date"):
        fm_lines.append(f'date: "{_yaml_escape(str(meta["date"]))}"')
    fm_lines.append(f'exported_at: "{now}"')
    fm_lines.append("format: markdown")
    fm_lines.append("---")
    fm_lines.append("")

    frontmatter = "\n".join(fm_lines) + "\n"
    body = f"# {display_title}\n\n{text.strip()}\n"
    dest.write_text(frontmatter + body, encoding="utf-8")


def _to_json(
    text: str, dest: Path, title: str = "", source: str = "", metadata: dict[str, Any] | None = None
) -> None:
    """Write structured JSON with metadata."""
    now = datetime.now(UTC).isoformat()
    meta = metadata or {}
    payload: dict[str, Any] = {
        "title": meta.get("title", title),
    }
    # Inject rich metadata
    for key in ("category", "series", "episode", "speakers", "duration", "url", "views", "date"):
        if meta.get(key) is not None:
            payload[key] = meta[key]
    payload.update(
        {
            "source": source,
            "exported_at": now,
            "word_count": len(text.split()),
            "char_count": len(text),
            "transcript": text.strip(),
        }
    )
    dest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _to_html(
    text: str, dest: Path, title: str = "", metadata: dict[str, Any] | None = None
) -> None:
    """Write a standalone HTML page with embedded CSS."""
    meta = metadata or {}
    display_title = meta.get("title", title)
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Metadata values also flow into the HTML document — escape them too so a
    # title/URL from upstream metadata can never inject markup into the export.
    escaped_title = (
        display_title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    paragraphs = "\n".join(f"<p>{line}</p>" if line.strip() else "" for line in escaped.split("\n"))

    # Build metadata lines
    meta_parts: list[str] = []
    if meta.get("category"):
        meta_parts.append(f"Category: {meta['category']}")
    if meta.get("series"):
        ep = f" &middot; Episode {meta['episode']}" if meta.get("episode") else ""
        meta_parts.append(f"Series: {meta['series']}{ep}")
    if meta.get("speakers"):
        meta_parts.append(f"Speakers: {', '.join(meta['speakers'])}")
    if meta.get("duration"):
        meta_parts.append(f"Duration: {meta['duration']}")
    if meta.get("views") is not None:
        meta_parts.append(f"Views: {meta['views']:,}")
    meta_html = " &middot; ".join(meta_parts) if meta_parts else "Exported from Journal-Utilities"

    url_link = ""
    if meta.get("url"):
        meta_url = meta["url"]
        escaped_url = (
            meta_url.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        url_link = f'<div class="meta"><a href="{escaped_url}">{escaped_url}</a></div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title}</title>
<style>
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    max-width: 800px;
    margin: 2rem auto;
    padding: 0 1rem;
    line-height: 1.7;
    color: #1a1a1a;
    background: #fafafa;
  }}
  h1 {{
    border-bottom: 2px solid #e63946;
    padding-bottom: 0.5rem;
    color: #0a0a0a;
  }}
  p {{ margin: 0.6rem 0; }}
  .meta {{
    color: #666;
    font-size: 0.85rem;
    margin-bottom: 0.5rem;
  }}
  .meta a {{ color: #457b9d; }}
</style>
</head>
<body>
<h1>{escaped_title}</h1>
<div class="meta">{meta_html}</div>
{url_link}
<article>
{paragraphs}
</article>
</body>
</html>
"""
    dest.write_text(html, encoding="utf-8")


def _sanitize_for_pdf(text: str) -> str:
    """Replace non-latin1 Unicode characters with safe ASCII equivalents.

    fpdf2's built-in Helvetica font only supports latin-1 (ISO 8859-1).
    This function replaces common Unicode punctuation (em/en dashes,
    curly quotes, ellipsis, etc.) with ASCII equivalents and strips
    any remaining unsupported characters.
    """
    replacements = {
        "\u2014": "--",  # em dash
        "\u2013": "-",  # en dash
        "\u2018": "'",  # left single curly quote
        "\u2019": "'",  # right single curly quote
        "\u201c": '"',  # left double curly quote
        "\u201d": '"',  # right double curly quote
        "\u2026": "...",  # ellipsis
        "\u2022": "-",  # bullet
        "\u00a0": " ",  # non-breaking space
        "\u2009": " ",  # thin space
        "\u200b": "",  # zero-width space
        "\u00b7": "-",  # middle dot
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)

    # Strip any remaining non-latin1 characters
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _to_pdf(text: str, dest: Path, title: str = "", metadata: dict[str, Any] | None = None) -> None:
    """Write a PDF document via fpdf2.

    Raises ``ImportError`` if ``fpdf2`` is not installed.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise ImportError(
            "PDF export requires 'fpdf2'. Install with: uv pip install fpdf2"
        ) from None

    meta = metadata or {}
    display_title = meta.get("title", title)
    safe_text = _sanitize_for_pdf(text)
    safe_title = _sanitize_for_pdf(display_title)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, safe_title, new_x="LMARGIN", new_y="NEXT")

    # Subtitle metadata line
    subtitle_parts: list[str] = []
    if meta.get("category"):
        subtitle_parts.append(meta["category"])
    if meta.get("speakers"):
        subtitle_parts.append(", ".join(meta["speakers"]))
    if meta.get("duration"):
        subtitle_parts.append(meta["duration"])
    if subtitle_parts:
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 7, _sanitize_for_pdf(" | ".join(subtitle_parts)), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    pdf.ln(4)

    # Body
    pdf.set_font("Helvetica", "", 11)
    for line in safe_text.strip().split("\n"):
        pdf.multi_cell(0, 6, line)
        pdf.ln(1)

    pdf.output(str(dest))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_FORMAT_WRITERS: dict[ExportFormat, Callable[..., None]] = {
    ExportFormat.PLAINTEXT: lambda text, dest, title, source, meta: _to_plaintext(
        text, dest, title, meta
    ),
    ExportFormat.MARKDOWN: lambda text, dest, title, source, meta: _to_markdown(
        text, dest, title, meta
    ),
    ExportFormat.JSON: lambda text, dest, title, source, meta: _to_json(
        text, dest, title, source, meta
    ),
    ExportFormat.HTML: lambda text, dest, title, source, meta: _to_html(text, dest, title, meta),
    ExportFormat.PDF: lambda text, dest, title, source, meta: _to_pdf(text, dest, title, meta),
}


def export_single(
    source_path: Path,
    output_dir: Path,
    fmt: ExportFormat,
    skip_existing: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ExportResult:
    """Export a single transcript file to the given format.

    Args:
        source_path: Path to the source ``.txt`` transcript.
        output_dir: Directory to write the exported file into.
        fmt: Target export format.
        skip_existing: Skip if the output file already exists.
        metadata: Optional video metadata dict (title, category, etc.).

    Returns:
        An :class:`ExportResult` with status, path, and timing.
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)

    ext_map = {
        ExportFormat.PLAINTEXT: ".txt",
        ExportFormat.PDF: ".pdf",
        ExportFormat.MARKDOWN: ".md",
        ExportFormat.JSON: ".json",
        ExportFormat.HTML: ".html",
    }
    ext = ext_map[fmt]
    dest = output_dir / f"{source_path.stem}{ext}"

    if skip_existing and dest.exists():
        size = _file_size(dest)
        logger.info("Export already exists: %s (%d bytes)", dest.name, size)
        return ExportResult(
            source_path=str(source_path),
            format=fmt,
            status="skipped",
            output_path=str(dest),
            file_size_bytes=size,
        )

    start = time.monotonic()

    try:
        text = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ExportResult(
            source_path=str(source_path),
            format=fmt,
            status="failed",
            error=f"Read error: {exc}",
        )

    if not text.strip():
        return ExportResult(
            source_path=str(source_path),
            format=fmt,
            status="failed",
            error="Source transcript is empty",
        )

    title = _stem_to_title(source_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        writer = _FORMAT_WRITERS[fmt]
        writer(text, dest, title, str(source_path), metadata)
    except Exception as exc:
        logger.error("Export failed for %s → %s: %s", source_path.name, fmt.value, exc)
        return ExportResult(
            source_path=str(source_path),
            format=fmt,
            status="failed",
            error=str(exc),
            duration_seconds=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start
    size = _file_size(dest)
    logger.info(
        "Exported %s → %s (%s, %.2fs)",
        source_path.name,
        dest.name,
        ExportResult(source_path="", format=fmt, status="", file_size_bytes=size).file_size_str,
        elapsed,
    )
    return ExportResult(
        source_path=str(source_path),
        format=fmt,
        status="success",
        output_path=str(dest),
        file_size_bytes=size,
        duration_seconds=elapsed,
    )


def export_transcripts(
    transcript_dir: Path,
    output_dir: Path,
    formats: list[ExportFormat] | None = None,
    skip_existing: bool = True,
    data_dir: Path | None = None,
) -> dict[str, list[ExportResult]]:
    """Batch-export all ``.txt`` transcripts to one or more formats.

    Args:
        transcript_dir: Directory containing ``.txt`` transcript files.
        output_dir: Base output directory (sub-dirs created per format).
        formats: List of formats to export. Defaults to ``[PLAINTEXT]``.
        skip_existing: Skip files whose output already exists.
        data_dir: Path to ``data/output`` for loading video metadata.

    Returns:
        Dict mapping format name → list of :class:`ExportResult`.
    """
    transcript_dir = Path(transcript_dir)
    output_dir = Path(output_dir)

    if formats is None:
        formats = [ExportFormat.PLAINTEXT]

    # Load video index for metadata enrichment
    video_index: dict[str, dict[str, Any]] = {}
    if data_dir is not None:
        video_index = _load_video_index(Path(data_dir))

    sources = sorted(transcript_dir.glob("*.txt"))
    if not sources:
        logger.warning("No .txt files found in %s", transcript_dir)
        return {}

    logger.info(
        "Exporting %d transcripts to %s format(s) (metadata: %s)",
        len(sources),
        ", ".join(f.value for f in formats),
        "yes" if video_index else "no",
    )

    results: dict[str, list[ExportResult]] = {}

    for fmt in formats:
        fmt_dir = output_dir / fmt.value
        fmt_results: list[ExportResult] = []

        for src in sources:
            meta = _build_metadata(src.stem, video_index) if video_index else None
            result = export_single(
                src,
                fmt_dir,
                fmt,
                skip_existing=skip_existing,
                metadata=meta,
            )
            fmt_results.append(result)

        successes = sum(1 for r in fmt_results if r.status == "success")
        skipped = sum(1 for r in fmt_results if r.status == "skipped")
        failed = sum(1 for r in fmt_results if r.status == "failed")
        logger.info(
            "Format %s: %d success, %d skipped, %d failed",
            fmt.value,
            successes,
            skipped,
            failed,
        )
        results[fmt.value] = fmt_results

    return results
