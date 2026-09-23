"""Every emitted journal URL must resolve against INDEX.json (Y1/E1/I1).

Builds descriptions for a fixture INDEX the same way the sync script does
(build_video_item_index -> resolve_video_journal_url -> assemble_video_description),
then asserts that every journal URL in the output maps to an item path present
in the INDEX — and that videos absent from the INDEX emit no journal URL at all.
"""

import re

from journal_utilities.youtube.metadata_formatter import (
    JOURNAL_GITHUB_TREE_BASE,
    ChapterEntry,
    assemble_video_description,
    build_journal_item_url,
    build_video_item_index,
    format_chapters_block,
    resolve_video_journal_url,
)

FIXTURE_INDEX_ITEMS = [
    {
        "path": "data/video/activeinferenceinstitute/Insights/Insights_001",
        "series": "Insights",
        "item": "Insights_001",
        "has_transcript": True,
        "parts": ["friston13k"],
    },
    {
        "path": "data/video/activeinferenceinstitute/Insights/Insights_002",
        "series": "Insights",
        "item": "Insights_002",
        "has_transcript": True,
        "parts": ["metzinger8k", "part2id"],
    },
    {
        "path": "data/video/activeinferenceinstitute/Fundamentals/Fundamentals_001",
        "series": "Fundamentals",
        "item": "Fundamentals_001",
        "has_transcript": False,
        "parts": ["nofranscript"],
    },
]

_JOURNAL_URL_RE = re.compile(re.escape(JOURNAL_GITHUB_TREE_BASE) + r"/\S+")


def _emitted_descriptions() -> dict[str, str]:
    index = build_video_item_index(FIXTURE_INDEX_ITEMS)
    descriptions = {}
    for item in FIXTURE_INDEX_ITEMS:
        for video_id in item["parts"]:
            descriptions[video_id] = assemble_video_description(
                base_description=f"Abstract for {video_id}.",
                chapters=[ChapterEntry(start=0.0, title="Intro")],
                github_transcript_url=resolve_video_journal_url(video_id, index),
            )
    return descriptions


def test_every_emitted_journal_url_resolves_against_index():
    valid_paths = {item["path"] for item in FIXTURE_INDEX_ITEMS}
    for video_id, description in _emitted_descriptions().items():
        for url in _JOURNAL_URL_RE.findall(description):
            suffix = url[len(JOURNAL_GITHUB_TREE_BASE) + 1 :]
            assert suffix in valid_paths, f"{video_id} emitted non-INDEX URL: {url}"


def test_mapped_video_links_to_its_own_item():
    descriptions = _emitted_descriptions()
    assert "data/video/activeinferenceinstitute/Insights/Insights_001" in descriptions["friston13k"]
    assert (
        "data/video/activeinferenceinstitute/Insights/Insights_002" in descriptions["metzinger8k"]
    )


def test_video_without_transcript_gets_no_link():
    descriptions = _emitted_descriptions()
    assert "Full Transcript" not in descriptions["nofranscript"]


def test_unmapped_video_gets_no_link():
    index = build_video_item_index(FIXTURE_INDEX_ITEMS)
    desc = assemble_video_description(
        base_description="Abstract.",
        github_transcript_url=resolve_video_journal_url("unknown_video", index),
    )
    assert "unknown_video" not in index
    assert _JOURNAL_URL_RE.search(desc) is None


def test_build_journal_item_url_matches_index_paths():
    for item in FIXTURE_INDEX_ITEMS:
        assert build_journal_item_url(item["path"]).startswith(JOURNAL_GITHUB_TREE_BASE)
        assert format_chapters_block([]) == ""
