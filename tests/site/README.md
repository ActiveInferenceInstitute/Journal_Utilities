# tests/site

Tests for [`journal_utilities.site`](../../src/journal_utilities/site/) — the static
GitHub Pages generator.

| File | Covers |
| --- | --- |
| `test_pages_site.py` | Per-item page bundles, JSON-LD shape, slug/canonical handling. |
| `test_sitemap.py` | `sitemap.xml` / `robots.txt` emission and `<lastmod>` rules. |

Uses synthetic journal trees (no network, no real journal checkout). Run:

```bash
uv run pytest tests/site/ -q
```

Part of the suite described in [`../README.md`](../README.md).
