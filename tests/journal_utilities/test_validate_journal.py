"""Tests for the read-only journal integrity gate."""

import json
from pathlib import Path

from scripts.generate_journal_indexes import update_indexes
from scripts.validate_journal import validate_journal

SRC = Path("data/video/activeinferenceinstitute")


def _write_item(
    journal: Path,
    path: str,
    video_ids: list[str],
    *,
    duplicate_of: str | None = None,
    split_record: bool = False,
) -> None:
    item_dir = journal / SRC / path
    item_dir.mkdir(parents=True)
    series, item = path.split("/", 1)[0], path.rsplit("/", 1)[-1]
    metadata = {
        "series": series,
        "item": item,
        "source": "youtube",
        "channel": "ActiveInferenceInstitute",
        "parts": [
            {
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": f"Video {video_id}",
            }
            for video_id in video_ids
        ],
    }
    if duplicate_of:
        metadata["duplicate_of"] = duplicate_of
    (item_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (item_dir / "transcript.txt").write_text("transcript", encoding="utf-8")
    if split_record:
        (item_dir / "transcript.json").write_text(
            json.dumps([{"video_id": "", "segments": []}]), encoding="utf-8"
        )


def _write_manifest(utilities: Path, video_ids: list[str]) -> Path:
    path = utilities / "data/output/channel_videos.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"videos": [{"id": value} for value in video_ids]}), encoding="utf-8"
    )
    return path


def test_validates_metadata_indexes_duplicates_and_manifest(tmp_path: Path):
    journal = tmp_path / "journal"
    utilities = tmp_path / "utilities"
    _write_item(journal, "Series/Item", ["video00001a"])
    _write_item(
        journal,
        "Other/video00001a",
        ["video00001a"],
        duplicate_of="Series/Item",
    )
    update_indexes(journal)
    manifest = _write_manifest(utilities, ["video00001a"])

    report = validate_journal(journal, manifest)

    assert report.ok, report.errors
    assert report.counts["canonical_video_ids"] == 1
    assert report.counts["missing_manifest_videos"] == 0


def test_session_linked_talk_uploads_count_as_covered(tmp_path: Path):
    """A per-talk upload's manifest id is covered via sessions[].video_id on the
    canonical item; the upload's own item carries duplicate_of."""
    journal = tmp_path / "journal"
    utilities = tmp_path / "utilities"
    _write_item(journal, "Series/Symposium", ["video00001a"])
    meta_path = journal / SRC / "Series/Symposium/metadata.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["sessions"] = [
        {
            "index": 1,
            "session_name": "video00001a_sess01",
            "start": "0:00:00",
            "video_id": "talkvideo0b",
        }
    ]
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    _write_item(journal, "Other/Talk", ["talkvideo0b"], duplicate_of="Series/Symposium")
    update_indexes(journal)
    manifest = _write_manifest(utilities, ["video00001a", "talkvideo0b"])

    report = validate_journal(journal, manifest)

    assert report.ok, report.errors
    assert report.counts["missing_manifest_videos"] == 0


def test_rejects_stale_indexes_and_blank_split_identity(tmp_path: Path):
    journal = tmp_path / "journal"
    _write_item(journal, "Series/Item", ["video00001a"], split_record=True)
    update_indexes(journal)
    (journal / "INDEX.json").write_text("{}\n", encoding="utf-8")

    report = validate_journal(journal)

    assert not report.ok
    assert any("stale derived index" in error for error in report.errors)
    assert any("split record has blank video_id" in error for error in report.errors)


def test_manifest_extras_are_warning_unless_strict(tmp_path: Path):
    journal = tmp_path / "journal"
    utilities = tmp_path / "utilities"
    _write_item(journal, "Series/Item", ["video00001a"])
    _write_item(journal, "Series/Item2", ["video00002b"])
    update_indexes(journal)
    manifest = _write_manifest(utilities, ["video00001a"])

    report = validate_journal(journal, manifest)
    strict_report = validate_journal(journal, manifest, strict_manifest=True)

    assert report.ok, report.errors
    assert any("absent from manifest" in warning for warning in report.warnings)
    assert not strict_report.ok
    assert any("absent from manifest" in error for error in strict_report.errors)


def test_malformed_metadata_is_reported_without_crashing(tmp_path: Path):
    journal = tmp_path / "journal"
    item_dir = journal / SRC / "Series" / "Item"
    item_dir.mkdir(parents=True)
    (item_dir / "metadata.json").write_text(
        json.dumps({"series": "Series", "item": "Item", "parts": None}),
        encoding="utf-8",
    )

    report = validate_journal(journal)

    assert not report.ok
    assert any("parts must be a list" in error for error in report.errors)
