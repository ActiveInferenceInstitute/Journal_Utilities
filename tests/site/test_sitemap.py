"""Tests for sitemap.xml and robots.txt emitters (M4 spec §3-§4)."""

from journal_utilities.site.sitemap import SitemapUrl, render_robots, render_sitemap


def test_render_sitemap_root_and_items_no_changefreq_priority() -> None:
    xml = render_sitemap(
        [
            SitemapUrl(loc="https://example.com/"),
            SitemapUrl(loc="https://example.com/item/A%20B/C/", lastmod="2021-06-21"),
            SitemapUrl(loc="https://example.com/item/D/E/"),
        ]
    )
    assert 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' in xml
    assert xml.count("<url>") == 3
    assert "<lastmod>2021-06-21</lastmod>" in xml
    assert "<changefreq>" not in xml and "<priority>" not in xml


def test_render_sitemap_omits_unknown_lastmod() -> None:
    # spec §3: omit when unknown — never fabricate.
    xml = render_sitemap([SitemapUrl(loc="https://example.com/item/D/E/")])
    assert "<lastmod>" not in xml
    assert "<loc>https://example.com/item/D/E/</loc>" in xml


def test_render_sitemap_escapes_xml() -> None:
    xml = render_sitemap([SitemapUrl(loc="https://example.com/item/A&B/C?x=1&y=2/")])
    assert "<loc>https://example.com/item/A&amp;B/C?x=1&amp;y=2/</loc>" in xml


def test_render_robots_exact_contract() -> None:
    assert render_robots("https://example.com/") == (
        "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n"
    )
