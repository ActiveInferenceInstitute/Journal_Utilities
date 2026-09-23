"""Static website generator for ActiveInferenceJournal (GitHub Pages).

Compiles ActiveInferenceJournal data into a standalone, client-side static site
with:
- Full index and series directory with category filtering
- Embedded YouTube video playback with interactive timestamp seeking
- Diarized transcripts with speaker labels and synchronized cues
- Chapters / session navigation
- Multi-language subtitle & translation switching
- Client-side full-text search index and clipboard copy tools
- Dark/Black/Gray theme with red accents, full accessibility (ARIA) and SEO metadata
"""

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def parse_srt(text: str) -> list[dict[str, Any]]:
    """Parse SubRip (.srt) subtitle text into structured cue dictionaries."""
    cues = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for b in blocks:
        lines = b.strip().splitlines()
        if len(lines) >= 3:
            timing = lines[1]
            content = " ".join(lines[2:]).strip()
            if "-->" in timing:
                parts = timing.split("-->")

                def to_sec(s: str) -> float:
                    s = s.strip().replace(",", ".")
                    p = s.split(":")
                    if len(p) == 3:
                        return float(p[0]) * 3600 + float(p[1]) * 60 + float(p[2])
                    elif len(p) == 2:
                        return float(p[0]) * 60 + float(p[1])
                    return 0.0

                cues.append(
                    {
                        "start": round(to_sec(parts[0]), 2),
                        "end": round(to_sec(parts[1]), 2),
                        "text": content,
                    }
                )
    return cues


_LANG_ANNOTATION_RE = re.compile(r"\([^()]*\)$")
_LANG_TAG_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z")


def _translation_dirs(item_dir: Path) -> list[Path]:
    """Translation directories under an item, in any case spelling.

    The journal has both `translations/` and legacy `Translations/` item
    subdirectories; lowercase is preferred when both exist.
    """
    if not item_dir.is_dir():
        return []
    dirs = [d for d in item_dir.iterdir() if d.is_dir() and d.name.casefold() == "translations"]
    return sorted(dirs, key=lambda d: (d.name != "translations", str(d)))


def _iter_translation_files(item_dir: Path) -> list[Path]:
    """Collect `.srt` files from every spelling of the item's translations dir.

    Matches any `.srt` extension spelling, deduplicates by file name across
    directory spellings (lowercase dir wins), and returns a name-sorted list.
    """
    chosen: dict[str, Path] = {}
    for d in _translation_dirs(item_dir):
        for f in d.iterdir():
            if f.is_file() and f.suffix.casefold() == ".srt":
                chosen.setdefault(f.name, f)
    return [chosen[name] for name in sorted(chosen)]


def translation_lang_key(srt_file: Path) -> str | None:
    """Derive the language key for a translation SRT file name.

    Strips a trailing parenthetical annotation (`.chi(translated)` -> `chi`)
    and returns ``None`` when the final dot segment is not a plausible language
    tag (e.g. transcript dumps named without a language).
    """
    tag = srt_file.name[: -len(srt_file.suffix)].rsplit(".", 1)[-1].strip()
    tag = _LANG_ANNOTATION_RE.sub("", tag).strip()
    if not tag or not _LANG_TAG_RE.fullmatch(tag):
        return None
    return tag

def build_item_payload(item_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Extract and structure full interactive data for a single journal item."""
    series = meta.get("series", "")
    item_id = meta.get("item", "")
    title = meta.get("title") or item_id
    category = meta.get("category") or series
    episode = meta.get("episode", "")
    parts = meta.get("parts", [])
    speakers = meta.get("speakers", {})
    guests = meta.get("guests", [])
    other_participants = meta.get("other_participants", [])
    keywords = meta.get("keywords", [])
    paper_title = meta.get("paper_title", "")
    github_url = meta.get("github", "")
    sessions = meta.get("sessions", [])

    payload: dict[str, Any] = {
        "id": f"{series}/{item_id}",
        "series": series,
        "item": item_id,
        "title": title,
        "category": category,
        "episode": episode,
        "parts": parts,
        "speakers": speakers,
        "guests": guests,
        "other_participants": other_participants,
        "keywords": keywords,
        "paper_title": paper_title,
        "github": github_url,
        "sessions": sessions,
        "transcripts": [],
        "translations": {},
        "raw_text": "",
    }

    # 1. Process transcript.json if present
    tj_path = item_dir / "transcript.json"
    if tj_path.exists():
        try:
            tj_data = json.loads(tj_path.read_text(encoding="utf-8"))
            if isinstance(tj_data, list):
                for part in tj_data:
                    if isinstance(part, dict) and isinstance(part.get("segments"), list):
                        vid = part.get("video_id", "")
                        segs = []
                        for s in part["segments"]:
                            if isinstance(s, dict):
                                segs.append(
                                    {
                                        "start": round(float(s.get("start", 0)), 2),
                                        "end": round(float(s.get("end", 0)), 2),
                                        "text": str(s.get("text", "")).strip(),
                                        "speaker": str(s.get("speaker", "")),
                                    }
                                )
                        payload["transcripts"].append({"video_id": vid, "segments": segs})
        except Exception as e:
            logger.warning("Failed parsing %s: %s", tj_path, e)

    # 2. Process transcript.txt
    txt_path = item_dir / "transcript.txt"
    if txt_path.exists():
        payload["raw_text"] = txt_path.read_text(encoding="utf-8", errors="replace")

    # 3. Process translations (both `translations/` and `Translations/` spellings)
    for srt_file in _iter_translation_files(item_dir):
        lang = translation_lang_key(srt_file)
        if lang is None:
            continue
        try:
            cues = parse_srt(srt_file.read_text(encoding="utf-8", errors="replace"))
            if cues:
                payload["translations"].setdefault(lang, []).append(
                    {"file": srt_file.name, "cues": cues}
                )
        except Exception as e:
            logger.warning("Failed parsing translation %s: %s", srt_file, e)

    return payload


def build_site(
    journal_dir: Path,
    output_dir: Path,
    clean: bool = True,
) -> dict[str, Any]:
    """Generate the complete static site bundle for GitHub Pages."""
    index_path = journal_dir / "INDEX.json"
    if not index_path.exists():
        raise FileNotFoundError(f"INDEX.json not found at {index_path}")

    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    items = index_data.get("items", [])

    if clean and output_dir.exists():
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    manifest_items = []
    processed_count = 0

    for it in items:
        path_str = it.get("path", "")
        item_path = journal_dir / path_str
        meta_path = item_path / "metadata.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Skipping malformed metadata %s: %s", meta_path, e)
            continue

        series = meta.get("series") or it.get("series", "Other")
        item_id = meta.get("item") or it.get("item", "")
        title = meta.get("title") or item_id
        category = meta.get("category") or series
        parts = meta.get("parts", [])
        guests = meta.get("guests", [])
        keywords = meta.get("keywords", [])

        # Build full item JSON payload
        item_payload = build_item_payload(item_path, meta)
        safe_key = f"{series}_{item_id}".replace("/", "_").replace(" ", "_")
        item_json_rel = f"data/{safe_key}.json"
        (output_dir / item_json_rel).write_text(
            json.dumps(item_payload, ensure_ascii=False),
            encoding="utf-8",
        )

        manifest_items.append(
            {
                "id": f"{series}/{item_id}",
                "series": series,
                "item": item_id,
                "title": title,
                "category": category,
                "has_transcript": it.get("has_transcript", False),
                "parts_count": len(parts),
                "video_ids": [pt.get("video_id") for pt in parts if pt.get("video_id")],
                "guests": guests,
                "keywords": keywords,
                "languages": sorted(item_payload["translations"].keys()),
                "data_url": item_json_rel,
            }
        )
        processed_count += 1

    # Write manifest.json
    manifest = {
        "version": "1.0",
        "total_items": len(manifest_items),
        "items": manifest_items,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Copy static assets (HTML, CSS, JS, Images)
    static_src = Path(__file__).parent / "static"
    if static_src.exists():
        for asset in static_src.glob("*"):
            if asset.is_file():
                shutil.copy2(asset, output_dir / asset.name)
            elif asset.is_dir():
                shutil.copytree(asset, output_dir / asset.name, dirs_exist_ok=True)

    return {
        "items_processed": processed_count,
        "output_dir": str(output_dir),
    }
