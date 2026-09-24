# Site (`src/journal_utilities/site/`)

Static website generation for the [ActiveInferenceJournal](https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal) GitHub Pages deployment.

## Module map

|File|Role|
|:---|:---|
|`builder.py`|SPA bundle: `manifest.json` + per-item `data/*.json` payloads + static assets. `build_site(..., static_pages=True)` also emits the M4 surfaces below. Per-item language lists read every `translations/` spelling (case-insensitive, any `.srt` case, `.chi(translated)`-style annotations stripped).|
|`pages_site.py`|M4 static per-item pages: one crawlable `/item/<series>/<item>/index.html` per INDEX item — server-rendered title/guests/date/summary, chapters as `?t=` jump links, YouTube-nocookie embeds, full transcript text (part-tagged via `## <video_id>` markers), VideoObject + hasPart Clip + Dataset JSON-LD, canonical/OG/Twitter head tags, breadcrumb + prev/next + SPA links.|
|`sitemap.py`|`sitemap.xml` urlset (root + one `<url>` per item; `lastmod` = max `parts[].upload_date`, omitted when unknown — never fabricated; no `changefreq`/`priority`) and `robots.txt` referencing the sitemap.|
|`static/`|Hand-written SPA frontend (HTML/CSS/JS), copied verbatim into the bundle.|

## URL contract

- Directory names from `INDEX.json items[].path` ARE the slugs; they are
  percent-encoded in emitted URLs and never re-slugified (folder slugification
  is a DAF decision, out of scope).
- Canonical form: `.../item/<series>/<item>/` — trailing slash, no `index.html`.
- The SPA stays at `/` with hash routing (`#/item/<series>/<item>`) for
  backward compatibility; item pages link back to it.

## Building

`scripts/build_pages_site.py` (dry-run by default):

```bash
uv run python scripts/build_pages_site.py                 # dry-run report
uv run python scripts/build_pages_site.py --apply         # write dist/
uv run python scripts/build_pages_site.py --check         # CI drift gate (exit 1 on drift)
```

`--check` builds into a temp dir and compares against an existing output
directory file-by-file; CI can fail a run when the committed/deployed bundle
is stale. Bare invocation writes nothing — deployment workflows must pass
`--apply`.

Spec source: `docs/m4-site-spec.md` in the ActiveInferenceJournal repo
(static per-item pages, sitemap, robots.txt).

## Testing

`uv run pytest tests/site tests/journal_utilities/test_site_builder.py` —
synthetic journal trees cover JSON-LD parsing, sitemap ↔ item-path bijection,
transcript presence, language normalization, and the no-fabrication rules.
