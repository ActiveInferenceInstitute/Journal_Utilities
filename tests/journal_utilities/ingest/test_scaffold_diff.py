"""Unit tests for journal_utilities.ingest.scaffold + diff — fake-driven.

No network, no API key, no journal checkout required (tmp_path stands in).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from journal_utilities.ingest.diff import (
    build_reconciliation,
    load_channel_ids,
    load_index_item_paths,
    load_manifest_ids,
    render_text_report,
)
from journal_utilities.ingest.diff import main as diff_main
from journal_utilities.ingest.enumerate import ChannelVideo
from journal_utilities.ingest.scaffold import (
    build_scaffold,
    plan_scaffolds,
    write_scaffolds,
)


@pytest.fixture()
def journal(tmp_path: Path) -> Path:
    root = tmp_path / "journal"
    (root / "data" / "output").mkdir(parents=True)
    return root


# ---------------------------------------------------------------- scaffold


def test_build_scaffold_schema_fields() -> None:
    video = ChannelVideo(
        video_id="abc123",
        title="ActInf GuestStream #141.1 ~ Test Talk",
        published_at="2026-09-20T10:00:00Z",
        duration_seconds=3600,
    )
    scaffold = build_scaffold(video, "GuestStream", "GuestStream_141", "GuestStream", "1")
    # Core keys per journal docs/SCHEMA.md; ingest additions: status + transcript_kind.
    assert scaffold["series"] == "GuestStream"
    assert scaffold["item"] == "GuestStream_141"
    assert scaffold["source"] == "youtube"
    assert scaffold["channel"] == "ActiveInferenceInstitute"
    assert scaffold["category"] == "GuestStream"
    assert scaffold["episode"] == "1"
    assert scaffold["status"] == "published"
    assert scaffold["transcript_kind"] == "youtube"
    part = scaffold["parts"][0]
    assert part["video_id"] == "abc123"
    assert part["url"] == "https://www.youtube.com/watch?v=abc123"
    assert part["transcript_kind"] == "youtube"
    assert part["published"] == "2026-09-20"
    assert part["duration"] == 3600


def test_scaffold_scheduled_status_for_premieres() -> None:
    upcoming = ChannelVideo(video_id="p1", title="Talk", broadcast_status="upcoming")
    unpublished = ChannelVideo(video_id="p2", title="Talk", upload_status="unpublished")
    normal = ChannelVideo(video_id="p3", title="Talk")
    assert build_scaffold(upcoming, "Livestream", "Livestream_100")["status"] == "scheduled"
    assert build_scaffold(unpublished, "Livestream", "Livestream_101")["status"] == "scheduled"
    assert build_scaffold(normal, "Livestream", "Livestream_102")["status"] == "published"


def test_plan_scaffolds_matches_index_naming(tmp_path: Path) -> None:
    """Series dir + item must match INDEX rows (series 'GuestStream',
    item 'GuestStream_141'); canonical numbers must never be renumbered."""
    videos = [
        ChannelVideo(video_id="g1", title="ActInf GuestStream #141.1 ~ Talk"),
        ChannelVideo(video_id="i1", title="Active Inference Insights 025 ~ Someone"),
        ChannelVideo(video_id="t1", title="ActInf Textbook Group ~ Cohort 5 ~ Meeting 12"),
        ChannelVideo(video_id="u1", title="Completely Unstructured Seminar Title"),
    ]
    plans = plan_scaffolds(videos, tmp_path)
    by_video = {p.metadata["parts"][0]["video_id"]: p for p in plans}
    guest = by_video["g1"]
    assert guest.relative_dir.as_posix() == (
        "data/video/activeinferenceinstitute/GuestStream/GuestStream_141"
    )
    assert guest.metadata["item"] == "GuestStream_141"
    assert by_video["i1"].relative_dir.as_posix() == (
        "data/video/activeinferenceinstitute/Insights/Insights_025"
    )
    textbook = by_video["t1"]
    # Real journal layout: nested TextbookGroup/<Book>/Cohort_N/<item>;
    # INDEX has zero flattened TextbookGroup_* dirs.
    assert textbook.relative_dir.as_posix() == (
        "data/video/activeinferenceinstitute/"
        "TextbookGroup/ParrPezzuloFriston2022/Cohort_5/Meeting_012"
    )
    assert textbook.metadata["series"] == "TextbookGroup"
    assert textbook.metadata["category"] == "TextbookGroup/ParrPezzuloFriston2022/Cohort_5"
    assert by_video["u1"].relative_dir.as_posix() == (
        "data/video/activeinferenceinstitute/Other/completely-unstructured-seminar-title"
    )


def test_no_scaffold_ever_lands_in_flattened_textbook_dir(tmp_path: Path) -> None:
    """Regression: scaffolds must not mint flattened TextbookGroup_* dirs."""
    videos = [
        ChannelVideo(video_id="t1", title="ActInf Textbook Group ~ Cohort 5 ~ Meeting 12"),
        ChannelVideo(video_id="t2", title="Fundamentals of Active Inference ~ Session 9"),
        ChannelVideo(video_id="t3", title="ActInf Textbook Group ~ Cohort 1 ~ Session 8"),
    ]
    for plan in plan_scaffolds(videos, tmp_path):
        first_segment = plan.relative_dir.parts[3]
        assert first_segment == "TextbookGroup", plan.relative_dir
    namjoshi = [
        p for p in plan_scaffolds(videos, tmp_path) if p.metadata["parts"][0]["video_id"] == "t2"
    ][0]
    assert namjoshi.relative_dir.as_posix() == (
        "data/video/activeinferenceinstitute/TextbookGroup/Namjoshi2026/Cohort_1/Session_009"
    )


def test_plan_scaffolds_preserves_categorizer_numbers(tmp_path: Path) -> None:
    """A re-run must not renumber items already aligned to the categorizer."""
    video = ChannelVideo(video_id="g1", title="ActInf GuestStream #141.1 ~ Talk")
    first = plan_scaffolds([video], tmp_path)[0]
    # Simulate the item existing from a previous run (different content).
    first.metadata_path.parent.mkdir(parents=True)
    first.metadata_path.write_text("{}", encoding="utf-8")
    rerun = plan_scaffolds([video], tmp_path)
    assert rerun == []  # skipped as existing, NOT renumbered to _142


def test_plan_scaffolds_skips_existing(journal: Path) -> None:
    item_dir = journal / "data/video/activeinferenceinstitute/GuestStream/GuestStream_141"
    item_dir.mkdir(parents=True)
    (item_dir / "metadata.json").write_text("{}", encoding="utf-8")
    video = ChannelVideo(video_id="g1", title="ActInf GuestStream #141.1 ~ Talk")
    assert plan_scaffolds([video], journal) == []
    assert len(plan_scaffolds([video], journal, skip_existing=False)) == 1


def test_unmatched_videos_dedupe_item_names(journal: Path) -> None:
    """Two distinct unmatched videos with the same slug must not merge."""
    v1 = ChannelVideo(video_id="u1", title="Completely Unstructured Seminar Title")
    v2 = ChannelVideo(video_id="u2", title="Completely Unstructured Seminar Title")
    plans = plan_scaffolds([v1, v2], journal, skip_existing=False)
    paths = [p.relative_dir.as_posix() for p in plans]
    assert paths[0] != paths[1], "distinct videos must not share one item dir"


def test_write_scaffolds_dry_run_writes_nothing(tmp_path: Path) -> None:
    video = ChannelVideo(video_id="g1", title="ActInf GuestStream #141.1 ~ Talk")
    plans = plan_scaffolds([video], tmp_path)
    report = write_scaffolds(plans, dry_run=True)
    assert report.written == []
    assert len(report.planned) == 1
    assert not (tmp_path / "data").exists()


def test_write_scaffolds_applies_and_never_overwrites(tmp_path: Path) -> None:
    video = ChannelVideo(video_id="g1", title="ActInf GuestStream #141.1 ~ Talk")
    plans = plan_scaffolds([video], tmp_path)
    report = write_scaffolds(plans, dry_run=False)
    assert len(report.written) == 1
    written = json.loads(report.written[0].read_text(encoding="utf-8"))
    assert written["series"] == "GuestStream"
    assert written["transcript_kind"] == "youtube"
    # Second pass: even planned against an existing item (skip_existing=False),
    # write_scaffolds must skip it — never overwrite.
    rerun = write_scaffolds(plan_scaffolds([video], tmp_path, skip_existing=False), dry_run=False)
    assert rerun.written == []
    assert len(rerun.skipped_existing) == 1


# ---------------------------------------------------------------- diff


def test_reconciliation_gap_sets() -> None:
    recon = build_reconciliation(
        channel_ids={"a", "b", "c"},
        manifest_ids={"b", "d"},
        index_ids={"a", "b", "e"},
    )
    assert recon.in_channel_not_manifest == {"a", "c"}
    assert recon.in_channel_not_index == {"c"}
    assert recon.in_manifest_not_channel == {"d"}
    assert recon.in_manifest_not_index == {"d"}
    assert recon.in_index_not_channel == {"e"}
    assert recon.fully_reconciled is False
    assert build_reconciliation({"x"}, {"x"}, {"x"}).fully_reconciled is True
    payload = recon.to_dict()
    assert payload["counts"]["channel_not_index"] == 1
    assert payload["channel_not_index"] == ["c"]


def test_load_channel_ids_accepts_manifest_and_worklist(tmp_path: Path) -> None:
    manifest = tmp_path / "channel_videos.json"
    manifest.write_text(
        json.dumps({"channel_id": "UCx", "videos": [{"id": "a"}, {"id": "b"}]}),
        encoding="utf-8",
    )
    assert load_channel_ids(manifest) == {"a", "b"}
    worklist = tmp_path / "worklist.json"
    worklist.write_text(
        json.dumps({"new_videos": [{"video_id": "c"}, {"video_id": "d"}]}),
        encoding="utf-8",
    )
    assert load_channel_ids(worklist) == {"c", "d"}
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    assert load_channel_ids(broken) == set()


def test_load_manifest_ids_ignores_simple_files(journal: Path) -> None:
    out = journal / "data" / "output"
    (out / "aaa.json").write_text("{}", encoding="utf-8")
    (out / "aaa.simple.json").write_text("{}", encoding="utf-8")
    (out / "bbb.simple.json").write_text("{}", encoding="utf-8")
    assert load_manifest_ids(out) == {"aaa"}
    assert load_manifest_ids(journal / "missing-dir") == set()


def test_render_text_report_lists_gaps() -> None:
    recon = build_reconciliation({"c1"}, {"m1"}, {"i1"})
    text = render_text_report(recon)
    assert "channel→manifest gaps: 1" in text
    assert "c1" in text
    assert "i1" in text
    assert "reconciled: False" in text


def test_duplicate_index_video_ids_detected(journal: Path) -> None:
    """Same video id in two INDEX items -> duplicate_video_ids, not reconciled."""
    (journal / "INDEX.json").write_text(
        json.dumps(
            {
                "items": [
                    {"path": "data/video/x/A", "parts": ["dup1", "only_a"]},
                    {"path": "data/video/x/B", "parts": ["dup1"]},
                    # Legitimate mirror: carries duplicate_of like 34 real
                    # INDEX rows; must not count as a hard duplicate.
                    {
                        "path": "data/video/x/C",
                        "parts": ["dup1"],
                        "duplicate_of": "data/video/x/A",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    paths = load_index_item_paths(journal / "INDEX.json")
    recon = build_reconciliation({"dup1", "only_a"}, {"dup1", "only_a"}, {"dup1", "only_a"}, paths)
    # x/C is annotated as a mirror; the A/B pair is the hard duplicate.
    # duplicate_video_ids lists ALL paths (mirrors annotated) for the report;
    # the reconciled gate fires because >1 canonical (unannotated) path exists.
    assert recon.duplicate_video_ids == {
        "dup1": [
            "data/video/x/A",
            "data/video/x/B",
            "data/video/x/C [duplicate_of]",
        ]
    }
    assert recon.fully_reconciled is False  # duplicates block reconciliation
    assert "INDEX duplicate video ids: 1" in render_text_report(recon)
    # to_dict carries the same annotated lists as the property.
    assert recon.to_dict()["duplicate_video_ids"]["dup1"] == [
        "data/video/x/A",
        "data/video/x/B",
        "data/video/x/C [duplicate_of]",
    ]
    # Raw paths keep the annotation for the report reader.
    assert recon.index_id_paths["dup1"] == [
        "data/video/x/A",
        "data/video/x/B",
        "data/video/x/C [duplicate_of]",
    ]


def test_diff_main_fatal_on_broken_manifest(tmp_path: Path) -> None:
    """A typo'd --channel-manifest must exit fatal, not 'reconciled except everything'."""
    journal = tmp_path / "journal"
    journal.mkdir()
    (journal / "INDEX.json").write_text(
        json.dumps({"items": [{"path": "p", "parts": ["v1"]}]}), encoding="utf-8"
    )
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="broken"):
        diff_main(["--journal", str(journal), "--channel-manifest", str(broken)])


def test_diff_main_fatal_on_unreadable_index(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    with pytest.raises(SystemExit, match="Cannot read INDEX"):
        diff_main(["--journal", str(journal), "--channel-manifest", str(tmp_path / "none.json")])
