# journal_utilities.site

Static **GitHub Pages** generator for the ActiveInferenceJournal. Compiles the
journal data tree into a standalone, client-side site (index + series directory,
embedded YouTube playback, diarized transcripts, chapters, multi-language
subtitles, full-text search) plus crawlable per-item pages, `sitemap.xml` and
`robots.txt`.

| Module | Purpose |
| --- | --- |
| `builder.py` | `build_site()` — assembles the SPA bundle and, with `static_pages=True`, bakes the per-item pages, sitemap and robots; fails the build on any pages/sitemap ↔ processed-item count mismatch. |
| `pages_site.py` | One crawlable `/item/<slug>/index.html` per `INDEX.json` item (server-rendered metadata, YouTube-nocookie embeds, chapters, transcript, schema.org JSON-LD, canonical/OG tags). |
| `sitemap.py` | `sitemap.xml` + `robots.txt` emitters (`<lastmod>` only from a real date, never fabricated). |
| `static/` | The bundle's HTML/CSS/JS shell — see [`static/README.md`](static/README.md). |

Run it through [`../../../scripts/build_pages_site.py`](../../../scripts/build_pages_site.py)
(dry-run by default; `--apply` writes, `--check` is the drift gate). Full contract
in [`../../../docs/site.md`](../../../docs/site.md).

Part of [Journal-Utilities](../../../README.md). See [`../../../docs/README.md`](../../../docs/README.md).
