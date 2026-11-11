# Agent guide — journal_utilities.site

The `journal_utilities.site` package. See [`README.md`](README.md) for the module map
and [`../../../docs/site.md`](../../../docs/site.md) for the URL contract.

## Conventions
- The generated bundle, per-item pages, sitemap and robots are **build outputs** —
  never hand-edit them or commit them under `data/`.
- `<lastmod>` comes only from a real `parts[].upload_date`; omit it when unknown.
  Never fabricate dates, `changefreq` or `priority`.
- `build_site(static_pages=True)` must fail on any pages/sitemap ↔ processed-item
  count mismatch.
- Escaping: percent-encode slugs from `INDEX.json items[].path`; HTML/XML-escape all
  rendered text.
- Tests mirror this package under `../../../tests/site/` and
  `../../../tests/journal_utilities/test_site_builder.py`.

Parent: [`../../../README.md`](../../../README.md) · [`../../../AGENTS.md`](../../../AGENTS.md).
