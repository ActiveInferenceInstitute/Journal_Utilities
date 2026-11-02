#!/usr/bin/env python3
"""Refactor the ActiveInferenceJournal into the v2 schema (see docs/JOURNAL_SCHEMA.md).

DRY-RUN by default: classifies every file in every item folder into its v2 target
(or an intentional placeholder-drop), and reports an audit so we can prove zero
data loss before applying. Applying is done **out-of-place** with ``--build <dir>``
(a safe staging copy with history-preserving classification + passthrough + an
idempotent uncovered-video pass), then the maintained workflow validates the tree
(``validate_journal.py``) before it is swapped in. ``--apply`` is intentionally not
a silent in-place move — pass it and the tool refuses with guidance rather than
pretending to do nothing.

Usage:
    python scripts/refactor_journal.py --journal ../ActiveInferenceJournal            # dry-run audit
    python scripts/refactor_journal.py --journal ../ActiveInferenceJournal --build /tmp/v2
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

PLACEHOLDERS = {"blank_document.txt", "blank.txt"}
# Source-namespaced root so other channels / non-video sources can live alongside:
#   data/video/activeinferenceinstitute/<Series>/...   data/<type>/<source>/...
SRC_PREFIX = "data/video/activeinferenceinstitute"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
SERIES_DIRS_SKIP = {".git", "Stream Series Template"}

# Item dir name like "GuestStream_094", "Roundtable_2024.2", "LiveStream_008"
ITEM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[0-9].*")


def classify(rel_parts: list[str], name: str) -> str:
    """Return the v2 destination category for a file given its path *inside* an item."""
    lower = name.lower()
    ext = Path(name).suffix.lower()
    pathlow = "/".join(p.lower() for p in rel_parts)

    if name in PLACEHOLDERS or name == ".gitkeep":
        return "DROP"
    if "metadata" in pathlow and ext == ".json" and not lower.endswith(".simple.json"):
        return "metadata"
    if lower.endswith(".simple.txt"):
        return "transcript_txt"
    if lower.endswith(".simple.json"):
        return "transcript_json"
    if ext == ".srt":
        return "translations" if "translation" in pathlow else "captions"
    if ext in {".m4a", ".mp3", ".wav", ".opus", ".webm"}:
        return "AUDIO"
    if ext in IMAGE_EXT:
        return "assets/images"
    if ext in {".html", ".xhtml"}:
        return "assets/html"
    if "prose" in pathlow:
        return "assets/prose"
    if "appendic" in pathlow:
        return "assets/appendices"
    if "bibliograph" in pathlow:
        return "assets/bibliography"
    if ext in {".pdf", ".odt", ".zip", ".csv", ".lua", ".docx"}:
        return f"assets/{ext.lstrip('.')}"
    if ext in {".txt", ".md", ".vtt", ".json"}:
        # leftover transcript/notes text
        return "assets/notes"
    return "UNMAPPED"


# A folder is an "item" if it directly contains any of these template subdirs.
# Content-based detection captures stream items AND non-standard names (symposium
# years, "End of 2023 Review", course Lecture_N) without relying on a name pattern.
TEMPLATE_SUBDIRS = {
    "Metadata",
    "Transcripts",
    "Captions",
    "Translations",
    "Audio",
    "Video",
    "Images",
    "Prose",
    "Appendices",
    "Bibliographic Information",
    "HTML",
}


def _is_item(d: Path) -> bool:
    return any((d / sub).is_dir() for sub in TEMPLATE_SUBDIRS)


def find_items(journal: Path) -> list[Path]:
    items: list[Path] = []

    def walk(d: Path) -> None:
        for sub in sorted(d.iterdir()):
            if not sub.is_dir() or sub.name in SERIES_DIRS_SKIP:
                continue
            if _is_item(sub):
                items.append(sub)  # do not descend into an item
            else:
                walk(sub)

    for series in sorted(journal.iterdir()):
        if series.is_dir() and series.name not in SERIES_DIRS_SKIP:
            if _is_item(series):
                items.append(series)
            else:
                walk(series)
    return items


def analyze(journal: Path) -> dict:
    items = find_items(journal)
    cats: collections.Counter = collections.Counter()
    unmapped: list[str] = []
    audio: list[str] = []
    per_item = []
    for item in items:
        files = [f for f in item.rglob("*") if f.is_file()]
        item_cats: collections.Counter = collections.Counter()
        for f in files:
            rel = f.relative_to(item)
            cat = classify(list(rel.parts[:-1]), f.name)
            cats[cat] += 1
            item_cats[cat] += 1
            if cat == "UNMAPPED":
                unmapped.append(str(f.relative_to(journal)))
            elif cat == "AUDIO":
                audio.append(str(f.relative_to(journal)))
        per_item.append(
            {"item": str(item.relative_to(journal)), "files": len(files), "by_cat": dict(item_cats)}
        )
    return {
        "items": len(items),
        "total_files": sum(cats.values()),
        "by_category": dict(cats.most_common()),
        "audio_count": len(audio),
        "unmapped_count": len(unmapped),
        "unmapped_sample": unmapped[:25],
        "per_item": per_item,
    }


_VID_RE = re.compile(r"([A-Za-z0-9_-]{11})(?:\.|$|_)")


def _video_id(name: str) -> str:
    # ids appear as ..._<id> / ..._youtube_<id> / <title> [<id>] / <item>.<ep>_<id>
    stem = re.sub(r"\.(simple\.)?(json|txt|srt)$", "", name)
    m = (
        re.search(r"\[([A-Za-z0-9_-]{11})\]", stem)  # symposium: "... [hW9IiOujS1E]_0"
        or re.search(r"^([A-Za-z0-9_-]{11})_sess\d+\b", stem)
        or re.search(r"_youtube_([A-Za-z0-9_-]{11})\b", stem)
        or re.search(r"_([A-Za-z0-9_-]{11})$", stem)
        or re.search(r"_([A-Za-z0-9_-]{11})\b", stem)
    )
    return m.group(1) if m else ""


def _load_titles(journal: Path) -> dict[str, str]:
    """video_id -> title, from the Journal-Utilities channel manifest if present."""
    mani = journal.parent / "Journal-Utilities" / "data" / "output" / "channel_videos.json"
    if not mani.exists():
        return {}
    try:
        data = json.loads(mani.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {v["id"]: v.get("title", "") for v in data.get("videos", []) if v.get("id")}


def build_item(item: Path, journal: Path, out_dir: Path, titles: dict, audio_out: Path) -> dict:
    """Build one v2 item folder under out_dir. Returns a per-item record + reconciliation."""
    from journal_utilities.youtube.categorizer import categorize_name

    rel = item.relative_to(journal)
    series = rel.parts[0]
    dest = out_dir / SRC_PREFIX / rel
    dest.mkdir(parents=True, exist_ok=True)

    parts: dict[str, dict] = {}
    transcript_txt: list[tuple[str, str]] = []
    transcript_json: list[dict] = []
    moved = 0
    dropped = 0
    audio_files: list[str] = []

    for f in sorted(item.rglob("*")):
        if not f.is_file():
            continue
        relparts = list(f.relative_to(item).parts[:-1])
        cat = classify(relparts, f.name)
        vid = _video_id(f.name)
        if vid:
            parts.setdefault(
                vid,
                {
                    "video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "title": titles.get(vid, ""),
                },
            )
        if cat == "DROP":
            dropped += 1
        elif cat == "transcript_txt":
            transcript_txt.append((vid, f.read_text(encoding="utf-8", errors="replace")))
        elif cat == "transcript_json":
            pass  # redundant simple.json — consumed by transcript.txt
        elif cat == "metadata":
            try:
                seg = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                transcript_json.append({"video_id": vid, "segments": seg})
            except json.JSONDecodeError:
                _copy(f, _unique(dest / "assets" / "notes", f.name, relparts))
                moved += 1
        elif cat == "AUDIO":
            ao = audio_out / rel / f.name
            ao.parent.mkdir(parents=True, exist_ok=True)
            _copy(f, ao)
            audio_files.append(f.name)
        else:  # captions / translations / assets/*
            _copy(f, _unique(dest / cat, f.name, relparts))
            moved += 1

    cat_, ser_, ep_ = categorize_name(
        titles.get(next(iter(parts), ""), "") or item.name, is_unique_event_name=False
    )
    meta = {
        "series": series,
        "item": item.name,
        "source": "youtube",
        "channel": "ActiveInferenceInstitute",
        "category": cat_,
        "episode": ep_,
        "parts": sorted(parts.values(), key=lambda p: p["video_id"]),
    }
    (dest / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if transcript_txt:
        body = "\n\n".join(
            f"## {vid}\n\n{txt.strip()}" for vid, txt in transcript_txt if txt.strip()
        )
        (dest / "transcript.txt").write_text(body, encoding="utf-8")
    if transcript_json:
        (dest / "transcript.json").write_text(
            json.dumps(transcript_json, ensure_ascii=False), encoding="utf-8"
        )
    # README
    lines = [f"# {item.name}", "", f"Series: **{series}**", ""]
    for p in meta["parts"]:
        t = p["title"] or "(untitled)"
        lines.append(f"- [{t}]({p['url']}) — `{p['video_id']}`")
    lines += [
        "",
        "Contents: "
        + ", ".join(sorted({d.name for d in dest.iterdir() if d.is_dir()}) or ["—"])
        + ".",
    ]
    (dest / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "item": str(rel),
        "parts": len(parts),
        "moved": moved,
        "dropped": dropped,
        "transcripts": len(transcript_txt),
        "audio": len(audio_files),
    }


def _copy(src: Path, dst: Path) -> None:
    import shutil

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _unique(dirpath: Path, name: str, relparts: list[str]) -> Path:
    """Return a collision-free target path. Disambiguates by prefixing the source
    subdir when the basename already exists from a different source location."""
    dirpath.mkdir(parents=True, exist_ok=True)
    target = dirpath / name
    if not target.exists():
        return target
    prefix = "_".join(p for p in relparts if p) or "x"
    return dirpath / f"{prefix}__{name}"


def build_v2(journal: Path, out_dir: Path, audio_out: Path) -> dict:
    titles = _load_titles(journal)
    items = find_items(journal)
    item_paths = [it.resolve() for it in items]
    records = [build_item(it, journal, out_dir, titles, audio_out) for it in items]

    # Passthrough pass: copy every file NOT under a detected item verbatim, so nothing
    # outside the item structure (course-level files, top-level README, …) is lost.
    def under_item(p: Path) -> bool:
        rp = p.resolve()
        return any(ip == rp or ip in rp.parents for ip in item_paths)

    passthrough = 0
    for f in journal.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(journal)
        if rel.parts[0] in (".git", "Stream Series Template", "data", "docs"):
            continue
        if rel.name in ("README.md", "INDEX.json", "INDEX.md", "SCHEMA.md", ".gitignore"):
            continue  # regenerated at the top level
        if f.name in PLACEHOLDERS or f.name == ".gitkeep":
            continue
        if under_item(f):
            continue
        ext = f.suffix.lower()
        if ext in {".m4a", ".mp3", ".wav", ".opus", ".webm"}:
            dst = audio_out / rel
        elif len(rel.parts) == 1:  # top-level loose file → docs/
            dst = out_dir / "docs" / rel.name
        else:  # course-level / series-level file → under the source namespace
            dst = out_dir / SRC_PREFIX / rel
        _copy(f, dst)
        passthrough += 1

    # Coverage pass: ensure EVERY channel video is an item (idempotent). Videos with a
    # JU transcript but no curated item get a generated item, categorized by title.
    generated = _build_uncovered(journal, out_dir, titles, item_paths)

    return {
        "items": len(records) + generated,
        "curated_items": len(records),
        "generated_items": generated,
        "titles_known": len(titles),
        "total_moved": sum(r["moved"] for r in records),
        "total_dropped": sum(r["dropped"] for r in records),
        "total_audio": sum(r["audio"] for r in records),
        "passthrough": passthrough,
        "with_transcript": sum(1 for r in records if r["transcripts"]),
    }


def _build_uncovered(journal: Path, out_dir: Path, titles: dict, item_paths: list) -> int:
    """Generate an item for every channel video not already in a curated item.

    Categorized videos land in their series; uncategorized ones go to ``Other/``.
    Idempotent: re-running produces the same tree. Uses JU transcripts when present.
    """
    from journal_utilities.youtube.categorizer import categorize_name

    mani = journal.parent / "Journal-Utilities" / "data" / "output" / "channel_videos.json"
    tx_dir = journal.parent / "Journal-Utilities" / "data" / "output" / "transcripts"
    if not mani.exists():
        return 0
    videos = json.loads(mani.read_text(encoding="utf-8")).get("videos", [])
    covered = set()
    for mj in (out_dir / SRC_PREFIX).rglob("metadata.json"):
        try:
            for p in json.loads(mj.read_text(encoding="utf-8")).get("parts", []):
                covered.add(p["video_id"])
        except (OSError, json.JSONDecodeError):
            continue

    generated = 0
    for v in videos:
        vid = v.get("id")
        if not vid or vid in covered:
            continue
        cat, ser, ep = categorize_name(v.get("title", ""), is_unique_event_name=False)
        if cat and ser:
            series, item = cat, ser
        else:
            from journal_utilities.utils.naming import slugify_title

            series = "Other"
            item = slugify_title(v.get("title", "")) or vid
            if (out_dir / SRC_PREFIX / series / item).exists():
                item = f"{item}_{vid}"
        dest = out_dir / SRC_PREFIX / series / item
        dest.mkdir(parents=True, exist_ok=True)
        meta = {
            "series": series,
            "item": item,
            "source": "youtube",
            "channel": "ActiveInferenceInstitute",
            "category": cat,
            "episode": ep,
            "parts": [
                {
                    "video_id": vid,
                    "url": v.get("url", f"https://www.youtube.com/watch?v={vid}"),
                    "title": v.get("title", ""),
                    "duration": v.get("duration"),
                    "upload_date": v.get("upload_date", ""),
                }
            ],
        }
        (dest / "metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tx = tx_dir / f"{vid}.txt"
        if tx.exists():
            (dest / "transcript.txt").write_text(
                tx.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
            )
        (dest / "README.md").write_text(
            f"# {item}\n\nSeries: **{series}**\n\n- [{v.get('title') or '(untitled)'}]"
            f"({v.get('url', '')}) — `{vid}`\n",
            encoding="utf-8",
        )
        covered.add(vid)
        generated += 1
    return generated


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--journal",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "ActiveInferenceJournal",
    )
    ap.add_argument(
        "--build", type=Path, default=None, help="build v2 staging tree at this path (out-of-place)"
    )
    ap.add_argument(
        "--audio-out",
        type=Path,
        default=None,
        help="collect audio files here (for the audio branch)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="DEPRECATED: in-place apply is not performed; use --build + validation",
    )
    ap.add_argument("--report", type=Path, default=None, help="write full JSON plan here")
    args = ap.parse_args()

    journal = args.journal.resolve()
    if not journal.exists():
        print(f"journal not found: {journal}")
        return 1

    if args.build:
        out = args.build.resolve()
        audio_out = (args.audio_out or (out.parent / "_audio")).resolve()
        out.mkdir(parents=True, exist_ok=True)
        audio_out.mkdir(parents=True, exist_ok=True)
        print(f"building v2 staging -> {out}\naudio -> {audio_out}")
        res = build_v2(journal, out, audio_out)
        print(json.dumps(res, indent=2))
        return 0

    plan = analyze(journal)
    print("=== ActiveInferenceJournal v2 refactor — DRY RUN ===")
    print(f"journal: {journal}")
    print(f"items: {plan['items']}   total files: {plan['total_files']}")
    print("by category:")
    for cat, n in plan["by_category"].items():
        print(f"  {n:6d}  {cat}")
    print(f"audio files (-> audio branch): {plan['audio_count']}")
    print(f"UNMAPPED (must be 0 before apply): {plan['unmapped_count']}")
    for u in plan["unmapped_sample"]:
        print(f"    ? {u}")
    if args.report:
        args.report.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(f"full plan -> {args.report}")
    if args.apply:
        print(
            "\n--apply is not implemented: in-place conversion is intentionally staged "
            "out-of-place with --build <dir>, then validated. Refusing (exit 1) so this "
            "is never a silent no-op.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
