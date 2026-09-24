"""Static per-item pages for the Active Inference Journal (M4).

Bakes one crawlable ``/item/<series>/<item>/index.html`` per INDEX.json item
with server-rendered title, guests, date, summary, chapters as ``?t=`` jump
links, a YouTube-nocookie embed per part, the FULL transcript text,
schema.org VideoObject + hasPart Clip + Dataset JSON-LD, and canonical/OG
head tags.

Spec: ``docs/m4-site-spec.md`` in the ActiveInferenceJournal repo. Directory
names from ``INDEX.json items[].path`` ARE the slugs; they are percent-encoded
in emitted URLs, never re-slugified (DAF decision §6/J11). Dates come from
``parts[].upload_date`` with ``metadata.json date`` as fallback — recorded
dates only, never fabricated.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from journal_utilities.site.sitemap import SitemapUrl

logger = logging.getLogger(__name__)

#: Canonical site base URL (spec §1).
BASE_URL = "https://activeinferenceinstitute.github.io/ActiveInferenceJournal/"

_ZENODO_CITATION = "https://doi.org/10.5281/zenodo.7299755"
_CC_BY_40 = "https://creativecommons.org/licenses/by/4.0/"

# Legacy ISO-639-2 tags -> BCP-47 (M2 table, spec §0).
_LANG_NORMALIZATION: dict[str, str] = {
    "chi": "zh-Hans",
    "dut": "nl",
    "fre": "fr",
    "ger": "de",
    "jpn": "ja",
    "kor": "ko",
    "rus": "ru",
    "por": "pt",
    "spa": "es",
    "ita": "it",
}


def page_url(base_url: str, series: str, item: str) -> str:
    """Canonical item URL: percent-encoded segments, trailing slash, no index.html."""
    return f"{base_url}item/{quote(series, safe='')}/{quote(item, safe='')}/"


def spa_url(base_url: str, series: str, item: str) -> str:
    """Backward-compatible hash route into the hash-routed SPA."""
    return f"{base_url}#/item/{quote(f'{series}/{item}', safe='')}"


def _iso_date(value: Any) -> str | None:  # noqa: ANN401 — metadata fields are untyped by design
    """Normalize a YYYYMMDD or ISO-8601 date string; ``None`` when not a date."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if re.fullmatch(r"\d{8}", v):
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", v):
        return v
    return None


def _parts_dates(meta: dict[str, Any]) -> list[str]:
    """Normalized ``parts[].upload_date`` values (spec §1 date source)."""
    return [
        d
        for p in meta.get("parts", [])
        if isinstance(p, dict)
        for d in [_iso_date(p.get("upload_date"))]
        if d
    ]


def _item_date(meta: dict[str, Any]) -> str | None:
    """Page-display date: max ``parts[].upload_date`` or recorded ``meta['date']``."""
    dates = _parts_dates(meta)
    if dates:
        return max(dates)
    return _iso_date(meta.get("date"))


def _lastmod(meta: dict[str, Any]) -> str | None:
    """Sitemap ``lastmod``: strictly max ``parts[].upload_date`` (spec §3).

    Never falls back to ``meta['date']`` — the spec's ``lastmod`` contract is
    parts-derived only; omit (``None``) when unknown, never fabricate.
    """
    dates = _parts_dates(meta)
    return max(dates) if dates else None


def _clips(part: dict[str, Any]) -> list[dict[str, Any]]:
    """schema.org Clip entries from a part's gated chapters (spec §2.3).

    Metadata stores only provenance-gated chapters, so presence is provenance;
    fewer than two chapters is not a chapter structure. ``endOffsetTime`` is the
    next chapter's start, the part duration, or omitted when unknown.
    """
    chapters = part.get("chapters")
    if not isinstance(chapters, list) or len(chapters) < 2:
        return []
    watch = str(part.get("url") or "")
    duration = part.get("duration")
    clips: list[dict[str, Any]] = []
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict) or ch.get("start") is None:
            continue
        start = int(float(ch["start"]))
        end: float | None = None
        if ch.get("end") is not None:
            end = float(ch["end"])
        elif i + 1 < len(chapters) and chapters[i + 1].get("start") is not None:
            end = float(chapters[i + 1]["start"])
        elif isinstance(duration, (int, float)):
            end = float(duration)
        clip: dict[str, Any] = {
            "@type": "Clip",
            "name": str(ch.get("title") or f"Chapter {i + 1}"),
            "startOffsetTime": start,
            # parts[].url already carries ?v=<id>; the timestamp is an
            # additional query param, so join with & when a query exists.
            "url": f"{watch}{'&' if '?' in watch else '?'}t={start}",
        }
        if end is not None:
            clip["endOffsetTime"] = int(end)
        clips.append(clip)
    return clips


def _abstract(meta: dict[str, Any]) -> str:
    """Summary/abstract for the page and VideoObject description."""
    for key in ("description", "paper_title"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(meta.get("title") or meta.get("item", ""))


def _video_object(
    part: dict[str, Any],
    meta: dict[str, Any],
    item_date: str | None,
    canonical: str,
) -> dict[str, Any]:
    """VideoObject JSON-LD for one part (no fabricated fields)."""
    vid = str(part.get("video_id") or "")
    obj: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "VideoObject",
        "name": str(part.get("title") or meta.get("title") or meta.get("item", "")),
        "description": _abstract(meta),
        "contentUrl": str(part.get("url") or f"https://www.youtube.com/watch?v={vid}"),
        "embedUrl": f"https://www.youtube-nocookie.com/embed/{vid}",
        "thumbnailUrl": [f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"],
        "inLanguage": "en",
        "transcript": f"{canonical}#transcript",
    }
    if item_date:
        obj["uploadDate"] = item_date
    clips = _clips(part)
    if clips:
        obj["hasPart"] = clips
    return obj


def _dataset_node(meta: dict[str, Any], canonical: str) -> dict[str, Any]:
    """Top-level Dataset node: CC-BY-4.0, journal Dataset parent, Zenodo DOI."""
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": str(meta.get("title") or meta.get("item", "")),
        "url": canonical,
        "license": _CC_BY_40,
        "isPartOf": {
            "@type": "Dataset",
            "name": "Active Inference Journal",
            "url": BASE_URL,
        },
        "citation": _ZENODO_CITATION,
    }


def _ld_json_script(node: dict[str, Any]) -> str:
    # <script> content is raw text: HTML entities are NOT decoded there, so
    # html.escape would corrupt JSON values (e.g. "&t=1" -> "&amp;t=1" in the
    # parsed JSON-LD). Only "</" needs guarding to prevent </script> breakout.
    payload = json.dumps(node, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


def _item_languages(item_dir: Path) -> list[str]:
    """Languages actually present for the item (post-I4 fix, normalized).

    Reuses the builder's case-insensitive translation discovery and
    parenthetical stripping (:func:`builder.translation_lang_key`), then maps
    legacy ISO-639-2 tags per the M2 table. Languages are never fabricated.
    """
    from journal_utilities.site.builder import (  # noqa: PLC0415 — leaf import breaks the builder cycle
        _iter_translation_files,
        translation_lang_key,
    )

    langs: set[str] = set()
    for srt_file in _iter_translation_files(item_dir):
        lang = translation_lang_key(srt_file)
        if lang is None:
            continue
        langs.add(_LANG_NORMALIZATION.get(lang, lang))
    return sorted(langs)


def _transcript_html(item_dir: Path, meta: dict[str, Any]) -> str:
    """Full transcript text as HTML paragraphs, part-tagged when multi-part."""
    txt_path = item_dir / "transcript.txt"
    if not txt_path.exists():
        return ""
    try:
        raw = txt_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("Failed reading %s: %s", txt_path, e)
        return ""
    part_titles = {
        str(p.get("video_id")): str(p.get("title") or p.get("video_id"))
        for p in meta.get("parts", [])
        if p.get("video_id")
    }

    def paragraphs(chunk: str) -> str:
        return "".join(
            f"<p>{html.escape(p.strip())}</p>" for p in re.split(r"\n\s*\n", chunk) if p.strip()
        )

    if len(part_titles) <= 1:
        return paragraphs(raw)
    # Multi-part: transcript.txt uses ``## <video_id>`` part markers; tag each
    # chunk with its part title.
    sections = re.split(r"^## (.+)$", raw, flags=re.MULTILINE)
    out: list[str] = []
    if sections and sections[0].strip():
        out.append(paragraphs(sections[0]))
    for i in range(1, len(sections), 2):
        marker = sections[i].strip()
        title = part_titles.get(marker, marker)
        body = sections[i + 1] if i + 1 < len(sections) else ""
        out.append(f"<h3>{html.escape(title)}</h3>")
        out.append(paragraphs(body))
    return "".join(out)


def _fmt_offset(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _item_link(m: dict[str, Any] | None, label: str) -> str:
    """Relative link to a sibling item page (``../../<series>/<item>/``)."""
    if not m:
        return ""
    href = (
        "../../"
        + quote(str(m.get("series")), safe="")
        + "/"
        + quote(str(m.get("item")), safe="")
        + "/"
    )
    return f'<a href="{html.escape(href, quote=True)}">{label}</a>'


def _render_item_page(
    journal_dir: Path,
    meta: dict[str, Any],
    base_url: str,
    prev_meta: dict[str, Any] | None,
    next_meta: dict[str, Any] | None,
) -> str:
    """Bake the full HTML document for one item."""
    series = str(meta.get("series") or "")
    item_id = str(meta.get("item") or "")
    title = str(meta.get("title") or item_id)
    item_dir = journal_dir / f"data/video/activeinferenceinstitute/{series}/{item_id}"
    canonical = page_url(base_url, series, item_id)
    item_date = _item_date(meta)
    abstract = _abstract(meta)
    languages = _item_languages(item_dir)
    parts = [p for p in meta.get("parts", []) if isinstance(p, dict) and p.get("video_id")]
    first_vid = str(parts[0]["video_id"]) if parts else ""
    spa_link = spa_url(base_url, series, item_id)
    guests = [str(g) for g in (meta.get("guests") or [])]

    head = [
        f"<title>{html.escape(title)} — Active Inference Journal</title>",
        f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">',
        '<meta property="og:type" content="video">',
        f'<meta property="og:title" content="{html.escape(title, quote=True)}">',
        f'<meta property="og:description" content="{html.escape(abstract, quote=True)}">',
        f'<meta property="og:url" content="{html.escape(canonical, quote=True)}">',
        f'<meta property="og:image" content="https://i.ytimg.com/vi/{first_vid}/hqdefault.jpg">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<link rel="stylesheet" href="../../../styles.css">',
    ]
    if item_date:
        head.append(
            '<meta property="video:release_date" content="'
            + html.escape(item_date, quote=True)
            + '">'
        )

    breadcrumb = (
        '<nav aria-label="Breadcrumb"><a href="../../../">Active Inference Journal</a>'
        f' &rsaquo; <a href="../../../#/">{html.escape(series)}</a> &rsaquo; '
        f"{html.escape(item_id)}</nav>"
    )
    nav_links = [
        link
        for link in (
            _item_link(prev_meta, "&larr; Previous in series"),
            _item_link(next_meta, "Next in series &rarr;"),
        )
        if link
    ]
    nav = f'<nav aria-label="Series navigation">{" | ".join(nav_links)}</nav>' if nav_links else ""

    body: list[str] = [breadcrumb, "<main>", f"<h1>{html.escape(title)}</h1>"]
    body.append(f'<p class="series">{html.escape(series)}</p>')
    if item_date:
        body.append(f'<p class="date">Date: {html.escape(item_date)}</p>')
    if guests:
        body.append('<p class="guests">Guests: ' + html.escape(", ".join(guests)) + "</p>")
    if abstract != title:
        body.append(f'<p class="summary">{html.escape(abstract)}</p>')
    if languages:
        body.append(
            '<p class="languages">Translations: '
            + ", ".join(
                f'<a href="{html.escape(spa_link, quote=True)}">{html.escape(lang)}</a>'
                for lang in languages
            )
            + "</p>"
        )
    body.append(
        f'<p><a href="{html.escape(spa_link, quote=True)}">Open in interactive player</a></p>'
    )

    parts_html: list[str] = []
    for i, part in enumerate(parts, 1):
        vid = str(part["video_id"])
        p_title = str(part.get("title") or f"Part {i}")
        blocks = [
            f'<section class="part" id="part-{i}">',
            f"<h2>{html.escape(p_title)}</h2>",
            '<iframe src="https://www.youtube-nocookie.com/embed/'
            f'{vid}" title="{html.escape(p_title, quote=True)}" '
            'allowfullscreen loading="lazy"></iframe>',
        ]
        clips = _clips(part)
        if clips:
            links = "".join(
                '<li><a href="'
                + html.escape(str(c["url"]), quote=True)
                + '">'
                + html.escape(str(c["name"]))
                + " ("
                + _fmt_offset(c["startOffsetTime"])
                + ")</a></li>"
                for c in clips
            )
            blocks.append(f'<h3>Chapters</h3><ul class="chapters">{links}</ul>')
        blocks.append("</section>")
        parts_html.append("".join(blocks))
    body.extend(parts_html)

    transcript = _transcript_html(item_dir, meta)
    if transcript:
        body.append(f'<section id="transcript"><h2>Transcript</h2>{transcript}</section>')
    body.append("</main>")
    if nav:
        body.append(nav)

    scripts = [_ld_json_script(_dataset_node(meta, canonical))]
    for part in parts:
        scripts.append(_ld_json_script(_video_object(part, meta, item_date, canonical)))

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        + "\n".join(head)
        + "\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n"
        + "\n".join(scripts)
        + "\n</body>\n</html>\n"
    )


@dataclass(frozen=True)
class ItemPage:
    """One planned per-item page: on-disk path, baked HTML, sitemap date."""

    series: str
    item: str
    rel_path: str
    html: str
    lastmod: str | None


def plan_item_pages(
    journal_dir: Path,
    entries: list[tuple[str, dict[str, Any]]],
    base_url: str = BASE_URL,
) -> list[ItemPage]:
    """Render one static ``index.html`` per processed INDEX entry.

    ``entries`` are ``(INDEX.json items[].path, parsed metadata.json)`` pairs in
    INDEX order; series-adjacent entries become prev/next links.
    """
    positions: dict[str, list[int]] = {}
    for i, (_, meta) in enumerate(entries):
        positions.setdefault(str(meta.get("series", "")), []).append(i)

    plans: list[ItemPage] = []
    for idx, (path_str, meta) in enumerate(entries):
        series = str(meta.get("series") or "")
        item_id = str(meta.get("item") or "")
        if not series or not item_id:
            logger.warning("Skipping entry without series/item: %s", path_str)
            continue
        siblings = positions[series]
        pos = siblings.index(idx)
        prev_meta = entries[siblings[pos - 1]][1] if pos > 0 else None
        next_meta = entries[siblings[pos + 1]][1] if pos + 1 < len(siblings) else None
        plans.append(
            ItemPage(
                series=series,
                item=item_id,
                rel_path=f"item/{series}/{item_id}/index.html",
                html=_render_item_page(journal_dir, meta, base_url, prev_meta, next_meta),
                lastmod=_lastmod(meta),
            )
        )
    return plans


def write_item_pages(plans: list[ItemPage], output_dir: Path) -> int:
    """Write each planned ``index.html`` under ``output_dir``; returns count."""
    for plan in plans:
        path = output_dir / plan.rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.html, encoding="utf-8")
    return len(plans)


def plan_sitemap_urls(plans: list[ItemPage], base_url: str = BASE_URL) -> list[SitemapUrl]:
    """Sitemap entries: the root first, then one canonical URL per item."""
    urls = [SitemapUrl(loc=base_url)]
    for plan in plans:
        urls.append(
            SitemapUrl(loc=page_url(base_url, plan.series, plan.item), lastmod=plan.lastmod)
        )
    return urls
