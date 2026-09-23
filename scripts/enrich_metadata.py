#!/usr/bin/env python3
"""
Enrich ActiveInferenceJournal metadata.json files (v2.1 schema) from:

  1. the Coda (Superhuman Docs) livestream table — full API fetch with
     fallback to the checked-in snapshot,
  2. data/input/*_split.txt session split-files (multi-talk videos),
  3. data/output/channel_videos.json (fills empty parts[] on split items).

Dry-run by default; pass --apply to write. Never creates journal items —
unmatched Coda rows are reported only. Idempotent: re-running --apply on an
enriched tree changes nothing.

Usage:
    python scripts/enrich_metadata.py                # dry run, API fetch
    python scripts/enrich_metadata.py --snapshot-only
    python scripts/enrich_metadata.py --apply --report report.json
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from dotenv import load_dotenv  # noqa: E402

from journal_utilities.data.coda_client import load_rows  # noqa: E402
from journal_utilities.data.enrichment import (  # noqa: E402
    PER_PART_KEYS,
    map_coda_row,
    merge_enrichment,
    parse_split_file,
    prefer_url,
)
from journal_utilities.youtube.categorizer import categorize_name  # noqa: E402
from journal_utilities.youtube.chapter_generator import validate_chapters  # noqa: E402
from journal_utilities.youtube.youtube import extract_youtube_id  # noqa: E402

logger = logging.getLogger("enrich_metadata")

SRC_PREFIX = "data/video/activeinferenceinstitute"  # matches refactor_journal.py
GITHUB_BASE = "https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/tree/main"


def load_db_export(path: Path) -> dict[str, dict]:
    """session_name -> record for whole-video sessions (per-talk _sessNN skipped)."""
    if not path.exists():
        return {}
    sessions = json.loads(path.read_text(encoding="utf-8")).get("sessions", [])
    return {s["session_name"]: s for s in sessions if "_sess" not in s["session_name"]}


def github_link(rel: str) -> str:
    from urllib.parse import quote

    return f"{GITHUB_BASE}/{quote(SRC_PREFIX + '/' + rel, safe='/')}"


def load_journal_index(journal: Path) -> dict[str, dict]:
    """item_rel_path -> {path, meta}; item_rel_path is relative to SRC_PREFIX."""
    root = journal / SRC_PREFIX
    items = {}
    for meta_path in sorted(root.rglob("metadata.json")):
        rel = str(meta_path.parent.relative_to(root))
        items[rel] = {"path": meta_path, "meta": json.loads(meta_path.read_text(encoding="utf-8"))}
    return items


def video_index(items: dict[str, dict]) -> dict[str, str]:
    """video_id -> item_rel_path (first claim wins; collisions logged)."""
    index: dict[str, str] = {}
    for rel, entry in items.items():
        for part in entry["meta"].get("parts", []):
            vid = part.get("video_id", "")
            if vid and vid not in index:
                index[vid] = rel
            elif vid:
                logger.debug("video id %s in both %s and %s", vid, index[vid], rel)
    return index


def load_manifest(path: Path) -> dict[str, dict]:
    videos = json.loads(path.read_text(encoding="utf-8")).get("videos", [])
    return {v["id"]: v for v in videos if v.get("id")}


def manifest_part(video: dict) -> dict:
    part = {
        "video_id": video["id"],
        "url": video.get("url", f"https://www.youtube.com/watch?v={video['id']}"),
        "title": video.get("title", ""),
    }
    if video.get("duration"):
        part["duration"] = video["duration"]
    if video.get("upload_date"):
        part["upload_date"] = video["upload_date"]
    return part


def find_secondary_item(vid: str, canonical: str, items: dict) -> str | None:
    """Locate the non-canonical item carrying this video id (slug-named Other/ dup)."""
    for rel, entry in items.items():
        if rel == canonical:
            continue
        if any(p.get("video_id") == vid for p in entry["meta"].get("parts", [])):
            return rel
    return None


def process_split_files(
    split_dir: Path, items: dict, manifest: dict, report: dict
) -> dict[str, dict]:
    """Parse *_split.txt files -> {item_rel: {enrichment, fill_parts}}; mark Other/ duplicates."""
    pending: dict[str, dict] = {}
    for split_path in sorted(split_dir.glob("*_split.txt")):
        result = parse_split_file(split_path.read_text(encoding="utf-8"))
        target = f"{result.category}/{result.series}"
        if target not in items:
            report["errors"].append(
                f"{split_path.name}: target item {target!r} not found in journal"
            )
            continue
        enrichment = {
            "sessions": result.sessions,
            "enriched_from": ["split_file"],
        }
        if result.description:
            enrichment["description"] = result.description
        fill = [manifest_part(manifest[result.video_id])] if result.video_id in manifest else None
        pending[target] = {"enrichment": enrichment, "fill_parts": fill}
        report["split_files"].append(
            {
                "file": split_path.name,
                "item": target,
                "sessions": len(result.sessions),
                "parts_filled": bool(fill),
            }
        )

        duplicate = find_secondary_item(result.video_id, target, items)
        if duplicate:
            pending[duplicate] = {
                "enrichment": {"duplicate_of": target, "enriched_from": ["split_file"]},
                "fill_parts": None,
            }
            report["duplicates_marked"].append(duplicate)
    return pending


def match_coda_rows(
    rows: list[dict], vid_index: dict, items: dict, report: dict
) -> dict[str, list]:
    """Return item_rel -> [(video_id_or_None, mapped_fields), ...]."""
    matched: dict[str, list] = defaultdict(list)
    claimed_fallback: set[str] = set()
    for row in rows:
        values = row.get("values", {})
        name = row.get("name", "") or values.get("Unique event name", "")
        vid = extract_youtube_id(values.get("YouTube", "") or "")
        fields = map_coda_row(values)
        if not fields:
            continue
        if vid and vid in vid_index:
            matched[vid_index[vid]].append((vid, fields))
            report["matched_by_id"] += 1
            continue
        # Fallback: reconstruct the item path from the Unique event name.
        category, series, _ = categorize_name(values.get("Unique event name", "") or "", True)
        rel = f"{category}/{series}" if category and series else None
        if rel and rel in items and rel not in claimed_fallback and rel not in matched:
            claimed_fallback.add(rel)
            matched[rel].append((vid, fields))
            report["matched_by_fallback"].append({"row": name, "item": rel})
        else:
            report["unmatched"].append({"row": name, "video_id": vid or None})
    return matched


# List-valued fields whose cross-row differences merge by order-preserving union.
UNION_KEYS = ("guests", "other_participants", "keywords")


# Human-verified corrections (2026-07-16): the refactor's 11-char id regex
# matched asset filename fragments for these items; the real uploads sat
# uncategorized in Other/. Maps item -> its actual YouTube video id.
CURATED_PARTS = {
    "Applied Active Inference Symposium/2023 Ecosystem Symposium/First_Interval": "rIemcswLfGg",
    "Applied Active Inference Symposium/2023 Ecosystem Symposium/Second_Interval": "PVeyvHSAwmk",
    # Social Sciences course lectures: curated items had empty parts while the
    # real uploads sat uncategorized (verified 2026-07-17).
    "Courses/ActiveInferenceForTheSocialSciences/ActInf_Basics_Lecture": "BNLnbOFdgc0",
    "Courses/ActiveInferenceForTheSocialSciences/Introduction_Lecture": "JkORFoyk8o8",
}

# (CURATED_GUESTS retired 2026-07-16: the swapped guest lists for the two
# 2023 Symposium videos were fixed upstream in the Coda/Superhuman table.)


def process_curated_parts(items: dict, manifest: dict, pending: dict, report: dict) -> None:
    """Replace bogus refactor-derived parts with the real video; mark Other/ duplicates."""
    for rel, vid in CURATED_PARTS.items():
        if rel not in items or vid not in manifest:
            report["errors"].append(f"curated parts: {rel!r} or video {vid} unavailable")
            continue
        pending[rel] = {
            "enrichment": {"enriched_from": ["curated"]},
            "fill_parts": [manifest_part(manifest[vid])],
            "replace_parts": True,
            "overrides": {"sessions": CURATED_SESSIONS[rel]} if rel in CURATED_SESSIONS else {},
        }
        duplicate = find_secondary_item(vid, rel, items)
        if duplicate:
            pending[duplicate] = {
                "enrichment": {"duplicate_of": rel, "enriched_from": ["curated"]},
                "fill_parts": None,
            }
            report["duplicates_marked"].append(duplicate)
        report["curated_parts"].append({"item": rel, "video_id": vid})


def _fmt_start(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def load_chapters(path: Path) -> dict[str, Any]:
    """Load a chapters cache: video_id -> payload (list of chapters, or a
    provenance dict ``{source, model, generated_at, chapters: [...]}``).

    Trust decisions are made per-part in chapter_sessions, where the
    part's video duration is available for the coverage rule.
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _usable_part_chapters(payload: Any, duration: float | None) -> list | None:  # noqa: ANN401 - cache payload is list-or-dict by design
    """Return seedable chapters for one video part, or None to skip.

    Trust model:
      - ``{"source": "youtube", "chapters": [...]}`` or a plain list (the
        video_chapters.json shape — only fetch_chapters.py writes it, from
        YouTube's own chapter data) → trusted; needs >=2 chapters.
      - Anything else with provenance (``source`` != youtube, i.e. the LLM
        cache) must pass validate_chapters with the part's duration — lists
        without a duration can never prove coverage, so they are rejected.
    """
    source = ""
    entries: list
    if isinstance(payload, dict) and "chapters" in payload:
        source = str(payload.get("source") or "")
        entries = payload["chapters"]
    elif isinstance(payload, list):
        entries = payload
        sources = {c.get("source", "") for c in entries if isinstance(c, dict)}
        if sources == {"youtube"}:
            source = "youtube"
    else:
        return None

    if source == "youtube":
        return entries if len(entries) >= 2 else None

    if duration is None:
        return None
    if not validate_chapters(entries, duration_seconds=duration).passed:
        return None
    return entries


def chapter_sessions(meta: dict, chapters: dict[str, Any]) -> list[dict]:
    """Seed sessions[] from trusted chapter lists, sequential across parts.

    Per part, chapters are seedable when their source is ``youtube`` or they
    pass ``validate_chapters`` (journal part duration required for the
    coverage rule). Unprovenanced lists — e.g. the legacy LLM cache — are
    never seeded. Only fires when a part has >=2 chapters (a single chapter
    is not a session structure). Speaker attribution is left to humans — the
    journal owns sessions after seeding.
    """
    sessions: list[dict] = []
    for part in meta.get("parts", []):
        vid = part.get("video_id", "")
        if not vid:
            continue
        usable = _usable_part_chapters(chapters.get(vid), part.get("duration"))
        if not usable:
            continue
        for chapter in usable:
            index = len(sessions) + 1
            sessions.append(
                {
                    "index": index,
                    "session_name": f"{vid}_sess{index:02d}",
                    "start": _fmt_start(chapter["start"]),
                    "title": chapter["title"],
                }
            )
    return sessions


def _sess(vid: str, index: int, start: str, guests: list[str], title: str = "") -> dict:
    session = {"index": index, "session_name": f"{vid}_sess{index:02d}", "start": start}
    if title:
        session["title"] = title
    if guests:
        session["guests"] = guests
    return session


# Per-talk segments from the video descriptions (verified 2026-07-16).
CURATED_SESSIONS = {
    "Applied Active Inference Symposium/2023 Ecosystem Symposium/First_Interval": [
        _sess("rIemcswLfGg", 1, "0:00:00", ["André Bastos"]),
        _sess("rIemcswLfGg", 2, "0:44:19", ["Keith Duggar"]),
        _sess("rIemcswLfGg", 3, "1:03:54", ["Sanjeev Namjoshi"]),
        _sess("rIemcswLfGg", 4, "1:23:35", ["Inês Hipólito"]),
        _sess("rIemcswLfGg", 5, "1:58:05", ["Aswin Paul"]),
        _sess("rIemcswLfGg", 6, "3:19:30", ["Takuya Isomura"]),
        _sess("rIemcswLfGg", 7, "3:56:55", ["Shanna Dobson"]),
        _sess("rIemcswLfGg", 8, "4:28:25", ["Nynke Boiten"]),
    ],
    "Applied Active Inference Symposium/2023 Ecosystem Symposium/Second_Interval": [
        _sess("PVeyvHSAwmk", 1, "0:00:00", ["Jean-François Cloutier"]),
        _sess("PVeyvHSAwmk", 2, "1:01:25", ["Conor Heins"]),
        _sess("PVeyvHSAwmk", 3, "1:31:24", ["Bert de Vries", "Dmitry Bagaev", "Bart van Erp"]),
        _sess("PVeyvHSAwmk", 4, "2:19:49", [], title="Active Inference Institute"),
        _sess("PVeyvHSAwmk", 5, "3:01:20", ["Rafael Kaufmann"]),
        _sess("PVeyvHSAwmk", 6, "3:31:10", ["Avel Guénin-Carlut"]),
        _sess("PVeyvHSAwmk", 7, "4:00:40", ["Pablo Fernandez-Maquieira"]),
        _sess("PVeyvHSAwmk", 8, "4:30:00", ["Mahault Albarracin"]),
        _sess(
            "PVeyvHSAwmk",
            9,
            "5:02:30",
            [
                "Bert de Vries",
                "Rafael Kaufmann",
                "Anna Lembke",
                "Curt Jaimungal",
                "Karl J Friston",
                "Guillaume Dumas",
            ],
            title="Roundtable",
        ),
    ],
}


# Human-reviewed disagreements where the Coda value was confirmed correct;
# suppressed from the review report. (item, field, db names as parsed)
RESOLVED_NAME_DIFFS = {
    # Verified against the video and website 2026-07-16: guest is Austin Cook.
    ("GuestStream/GuestStream_072", "guests", ("John Cook",)),
}


def _collect_name_diffs(rec: dict, enrichment: dict, rel: str, report: dict) -> None:
    """Record (not apply) people-name disagreements between legacy DB and Coda."""
    from journal_utilities.data.enrichment import split_names

    for field in ("guests", "other_participants"):
        db_names = split_names(rec.get(field) or "")
        coda_names = enrichment.get(field) or []
        if (rel, field, tuple(db_names)) in RESOLVED_NAME_DIFFS:
            continue
        if db_names and coda_names and not set(db_names) <= set(coda_names):
            report["name_diffs"].append(
                {"item": rel, "field": field, "db": db_names, "coda": coda_names}
            )


def write_private_registry(
    journal: Path, db_records: dict, vid_index: dict, apply: bool, report: dict
) -> None:
    """Document private/unlisted channel videos absent from the journal."""
    private = [
        {"video_id": vid, "title": rec.get("title", "")}
        for vid, rec in sorted(db_records.items())
        if rec.get("is_private") and vid not in vid_index
    ]
    if not private:
        return
    path = journal / SRC_PREFIX / "private_videos.json"
    payload = (
        json.dumps(
            {
                "description": "Private/unlisted videos known to the Institute but absent from "
                "this public corpus (from the legacy session database).",
                "videos": private,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    changed = not path.exists() or path.read_text(encoding="utf-8") != payload
    if changed and apply:
        path.write_text(payload, encoding="utf-8")
    report["private_registry"] = {"videos": len(private), "written": changed and apply}


def combine_rows(entries: list, meta: dict, report: dict, rel: str) -> tuple[dict, dict]:
    """Merge multiple matched rows: shared values -> item level, list fields
    union, per-part fields attach to their part, rest first-row-wins."""
    if len(entries) == 1:
        return entries[0][1], {}
    item_level: dict = {}
    part_updates: dict = defaultdict(dict)
    keys = {key for _, fields in entries for key in fields}
    for key in keys:
        values = [fields.get(key) for _, fields in entries if fields.get(key)]
        unique = {json.dumps(v, sort_keys=True) for v in values}
        if len(unique) == 1:
            item_level[key] = values[0]
        elif key in UNION_KEYS:
            item_level[key] = list(dict.fromkeys(name for value in values for name in value))
        elif key in PER_PART_KEYS:
            for vid, fields in entries:
                if vid and fields.get(key):
                    part_updates[vid][key] = fields[key]
            report["per_part_attachments"].append({"item": rel, "field": key})
        else:
            item_level[key] = values[0]
            report["conflicts"].append({"item": rel, "field": key, "kept": "first row"})
    return item_level, dict(part_updates)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--journal", type=Path, default=REPO.parent / "ActiveInferenceJournal")
    parser.add_argument("--snapshot-only", action="store_true", help="skip the Coda API fetch")
    parser.add_argument(
        "--coda-cache", type=Path, default=REPO / "data/input/livestream_fulldata_full.json"
    )
    parser.add_argument("--split-dir", type=Path, default=REPO / "data/input")
    parser.add_argument("--manifest", type=Path, default=REPO / "data/output/channel_videos.json")
    parser.add_argument(
        "--db-export", type=Path, default=REPO / "data/input/session_db_export.json"
    )
    parser.add_argument("--chapters", type=Path, default=REPO / "data/input/video_chapters.json")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--report", type=Path, help="write full JSON report to this path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv(REPO / ".env")

    report: dict = {
        "source": "",
        "rows_total": 0,
        "matched_by_id": 0,
        "matched_by_fallback": [],
        "unmatched": [],
        "split_files": [],
        "duplicates_marked": [],
        "per_part_attachments": [],
        "conflicts": [],
        "items_enriched": 0,
        "items_unchanged": 0,
        "errors": [],
        "db_export": "absent",
        "db_slides": [],
        "name_diffs": [],
        "private_registry": None,
        "curated_parts": [],
        "chapter_seeded": [],
        "chapters_cache": "absent",
        "per_series": defaultdict(lambda: {"enriched": 0, "total": 0}),
    }

    items = load_journal_index(args.journal)
    if not items:
        logger.error("no journal items under %s/%s", args.journal, SRC_PREFIX)
        return 1
    manifest = load_manifest(args.manifest)

    # Split files and curated corrections first, so symposium parts are
    # filled/replaced before id-matching.
    pending = process_split_files(args.split_dir, items, manifest, report)
    process_curated_parts(items, manifest, pending, report)
    vid_index = video_index(items)
    for rel, work in pending.items():
        for part in work.get("fill_parts") or []:
            vid_index[part["video_id"]] = rel  # symposium item wins over Other/ duplicate

    rows, source = load_rows(
        snapshot_path=REPO / "data/input/livestream_fulldata_table.json",
        cache_path=args.coda_cache,
        fetch=not args.snapshot_only,
    )
    report["source"] = source
    report["rows_total"] = len(rows)

    matched = match_coda_rows(rows, vid_index, items, report)

    db_records = load_db_export(args.db_export)
    db_by_item: dict[str, list] = defaultdict(list)
    for vid, rec in db_records.items():
        if vid in vid_index:
            db_by_item[vid_index[vid]].append(rec)
    report["db_export"] = (
        f"{args.db_export.name} ({len(db_records)} sessions)" if db_records else "absent"
    )
    chapters = load_chapters(args.chapters)
    report["chapters_cache"] = (
        f"{sum(1 for c in chapters.values() if c)} videos with chapters" if chapters else "absent"
    )

    for rel, entry in items.items():
        series = rel.split("/")[0]
        report["per_series"][series]["total"] += 1
        # Provenance is sticky: a source that contributed in a past run stays
        # recorded even when this run has nothing new from it.
        enrichment: dict = {"enriched_from": list(entry["meta"].get("enriched_from", []))}
        part_updates: dict = {}
        fill_parts = None
        replace_parts = False

        if rel in matched:
            row_fields, part_updates = combine_rows(matched[rel], entry["meta"], report, rel)
            row_fields.pop("enriched_from", None)
            enrichment.update(row_fields)
            enrichment["enriched_from"] = list(
                dict.fromkeys(enrichment["enriched_from"] + ["coda"])
            )
        if rel in pending:
            work = pending[rel]
            for key, value in work["enrichment"].items():
                if key == "enriched_from":
                    enrichment["enriched_from"] = list(
                        dict.fromkeys(enrichment.get("enriched_from", []) + value)
                    )
                else:
                    enrichment.setdefault(key, value)
            for key, value in work.get("overrides", {}).items():
                enrichment[key] = value
            fill_parts = work["fill_parts"]
            replace_parts = work.get("replace_parts", False)
            if fill_parts:
                enrichment["enriched_from"] = list(
                    dict.fromkeys(enrichment.get("enriched_from", []) + ["youtube"])
                )

        # YouTube chapters seed sessions[] when nothing else has (journal-owned
        # after seeding — hand-edits there are never overwritten).
        if not enrichment.get("sessions") and not entry["meta"].get("sessions"):
            seeded = chapter_sessions(entry["meta"], chapters)
            if seeded:
                enrichment["sessions"] = seeded
                enrichment["enriched_from"] = list(
                    dict.fromkeys(enrichment.get("enriched_from", []) + ["youtube"])
                )
                report["chapter_seeded"].append(rel)

        # Legacy-DB overlay: slides links the current Coda table lost or holds junk for.
        # Single-part items take them at item level; multi-part items per-part.
        db_recs = db_by_item.get(rel, [])
        multi_part = len(entry["meta"].get("parts", [])) > 1
        for rec in db_recs:
            db_slides = (rec.get("slides_url") or "").strip()
            _collect_name_diffs(rec, enrichment, rel, report)
            if not db_slides.startswith(("http://", "https://")):
                continue
            applied = False
            if multi_part:
                vid = rec["session_name"]
                existing = next(
                    (
                        p.get("slides_url", "")
                        for p in entry["meta"]["parts"]
                        if p.get("video_id") == vid
                    ),
                    "",
                )
                if prefer_url(existing, db_slides) != existing:
                    part_updates.setdefault(vid, {})["slides_url"] = db_slides
                    report["db_slides"].append(
                        {"item": rel, "part": vid, "replaced": existing or None}
                    )
                    applied = True
            else:
                current = enrichment.get("slides_url") or entry["meta"].get("slides_url") or ""
                if prefer_url(current, db_slides) != current:
                    enrichment["slides_url"] = db_slides
                    report["db_slides"].append(
                        {"item": rel, "part": None, "replaced": current or None}
                    )
                    applied = True
            already_db = db_slides in (
                [enrichment.get("slides_url"), entry["meta"].get("slides_url")]
                + [p.get("slides_url") for p in entry["meta"].get("parts", [])]
            )
            if applied or already_db:
                enrichment["enriched_from"] = list(
                    dict.fromkeys(enrichment.get("enriched_from", []) + ["db"])
                )

        # Canonical self-link into this repo's current layout (Coda's are pre-v2, stale).
        enrichment["github"] = github_link(rel)
        enrichment["enriched_from"] = list(
            dict.fromkeys(enrichment.get("enriched_from", []) + ["generated"])
        )

        new_meta, changed = merge_enrichment(
            entry["meta"], enrichment, part_updates, fill_parts, replace_parts
        )
        if changed:
            report["items_enriched"] += 1
            report["per_series"][series]["enriched"] += 1
            if args.apply:
                entry["path"].write_text(
                    json.dumps(new_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
        else:
            report["items_unchanged"] += 1

    write_private_registry(args.journal, db_records, vid_index, args.apply, report)

    report["per_series"] = dict(sorted(report["per_series"].items()))
    _print_summary(report, dry_run=not args.apply)
    if args.report:
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        logger.info("full report -> %s", args.report)
    return 0 if not report["errors"] else 1


def _print_summary(report: dict, dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "APPLIED"
    print(f"\n=== enrich_metadata {mode} ===")
    print(f"coda source:          {report['source']}")
    print(f"coda rows:            {report['rows_total']}")
    print(f"  matched by id:      {report['matched_by_id']}")
    print(f"  matched by fallback:{len(report['matched_by_fallback']):>4}")
    print(f"  unmatched:          {len(report['unmatched'])}")
    print(
        f"split files:          {len(report['split_files'])} "
        f"({sum(s['sessions'] for s in report['split_files'])} sessions)"
    )
    print(f"duplicates marked:    {report['duplicates_marked']}")
    print(f"curated part fixes:   {[c['item'].split('/')[-1] for c in report['curated_parts']]}")
    print(f"chapters cache:       {report['chapters_cache']}")
    print(f"chapter-seeded items: {len(report['chapter_seeded'])}")
    print(f"items enriched:       {report['items_enriched']}")
    print(f"items already current:{report['items_unchanged']:>4}")
    print(f"per-part attachments: {len(report['per_part_attachments'])}")
    print(f"conflicts:            {len(report['conflicts'])}")
    print(f"db export:            {report['db_export']}")
    print(
        f"db slides applied:    {len(report['db_slides'])} "
        f"({sum(1 for s in report['db_slides'] if s['replaced'])} replaced junk)"
    )
    print(f"name diffs (review):  {len(report['name_diffs'])}")
    if report["private_registry"]:
        print(
            f"private registry:     {report['private_registry']['videos']} videos "
            f"(written: {report['private_registry']['written']})"
        )
    if report["errors"]:
        print("ERRORS:")
        for err in report["errors"]:
            print(f"  - {err}")
    print("\nper-series coverage:")
    for series, counts in report["per_series"].items():
        print(f"  {series:<45} {counts['enriched']}/{counts['total']}")
    if report["unmatched"]:
        print("\nunmatched coda rows:")
        for row in report["unmatched"][:25]:
            print(f"  - {row['row']!r} (video_id={row['video_id']})")
        if len(report["unmatched"]) > 25:
            print(f"  … and {len(report['unmatched']) - 25} more (see --report)")


if __name__ == "__main__":
    sys.exit(main())
