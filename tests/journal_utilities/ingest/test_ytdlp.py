"""Unit tests for journal_utilities.ingest.ytdlp — evidence rules, no network.

The full per-video extraction is faked (``FakeRunner``) or replayed from saved
JSON files (``DirectoryVideoDetailRunner``); the flat channel manifest is built
in memory. Nothing here needs an API key, a network call, or a live yt-dlp run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from journal_utilities.ingest.enumerate import UNKNOWN, ChannelVideo
from journal_utilities.ingest.scaffold import build_scaffold
from journal_utilities.ingest.ytdlp import (
    AdapterResult,
    DirectoryVideoDetailRunner,
    apply_full_details,
    build_worklist_from_manifest,
    video_from_manifest_entry,
)
from journal_utilities.ingest.ytdlp import main as ytdlp_main
from journal_utilities.youtube.channel import ChannelManifest, VideoInfo, save_channel_manifest

#: 2026-09-20T00:00:00Z — the epoch second yt-dlp reports for that upload date.
_EPOCH_2026_09_20 = 1789862400

_PUBLISHED_DETAILS = {"availability": "public", "live_status": "not_live"}


class FakeRunner:
    """Full per-video extractor returning canned details; missing ids -> None."""

    def __init__(self, details: dict[str, dict[str, Any]]) -> None:
        self.details = details
        self.calls: list[str] = []

    def video_details(self, video_id: str) -> dict[str, Any] | None:
        self.calls.append(video_id)
        return self.details.get(video_id)


def _manifest(*entries: VideoInfo) -> ChannelManifest:
    return ChannelManifest(
        channel_id="UCbPq2w41ZaJSWtpCq4BE6Dg",
        channel_url="https://www.youtube.com/@ActiveInference",
        enumerated_at="2026-09-21T00:00:00Z",
        total_videos=len(entries),
        videos=list(entries),
    )


def _write_index(root: Path, *video_ids: str) -> Path:
    """Minimal journal checkout: only INDEX.json with ``parts`` video ids."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "INDEX.json").write_text(
        json.dumps(
            {
                "count": 1,
                "videos": len(video_ids),
                "unique_videos": len(video_ids),
                "items": [
                    {
                        "path": "data/video/activeinferenceinstitute/GuestStream/GuestStream_001",
                        "series": "GuestStream",
                        "item": "GuestStream_001",
                        "parts": list(video_ids),
                        "has_transcript": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


# ------------------------------------------------------- flat pass: no evidence


def test_flat_entry_carries_no_status_evidence() -> None:
    """The flat pass knows nothing about status: every field stays unknown."""
    video = video_from_manifest_entry(
        VideoInfo(id="newv0000001", title="Talk", upload_date="20260920", duration=1234.0)
    )
    assert video.video_id == "newv0000001"
    assert video.title == "Talk"
    assert video.published_at == "2026-09-20"
    assert video.duration_seconds == 1234
    assert video.privacy_status == UNKNOWN
    assert video.upload_status == UNKNOWN
    assert video.broadcast_status == UNKNOWN
    assert video.publication_state == UNKNOWN


def test_flat_entry_tolerates_raw_dicts_and_junk_dates() -> None:
    video = video_from_manifest_entry(
        {"id": "newv0000002", "title": "Talk", "upload_date": "20", "duration": None}
    )
    assert video.published_at == ""
    assert video.published_date == ""
    assert video.duration_seconds is None
    assert video.publication_state == UNKNOWN


# --------------------------------------------------- publication_state matrix


@pytest.mark.parametrize(
    ("privacy", "broadcast", "upload", "expected"),
    [
        ("public", "none", "processed", "published"),
        ("public", "live", "processed", "published"),
        ("unlisted", "none", "processed", "published"),
        ("public", "upcoming", "processed", "scheduled"),
        ("public", "none", "unpublished", "scheduled"),
        ("private", "none", "processed", UNKNOWN),
        ("public", UNKNOWN, "processed", UNKNOWN),
        (UNKNOWN, "none", "processed", UNKNOWN),
        (UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN),
        ("", "", "", UNKNOWN),
    ],
)
def test_publication_state_requires_evidence(
    privacy: str, broadcast: str, upload: str, expected: str
) -> None:
    video = ChannelVideo(
        video_id="newv0000003",
        title="Talk",
        privacy_status=privacy,
        broadcast_status=broadcast,
        upload_status=upload,
    )
    assert video.publication_state == expected


# ---------------------------------------------- full extraction adds evidence


def test_full_extraction_supplies_availability_evidence() -> None:
    flat = video_from_manifest_entry(
        VideoInfo(id="newv0000001", title="Talk", upload_date="20260920", duration=1000.0)
    )
    resolved = apply_full_details(
        flat,
        {
            "title": "Talk",
            "availability": "public",
            "live_status": "not_live",
            "timestamp": _EPOCH_2026_09_20,
            "duration": 3600,
        },
    )
    assert resolved.publication_state == "published"
    assert resolved.privacy_status == "public"
    assert resolved.broadcast_status == "none"
    assert resolved.published_at == "2026-09-20T00:00:00Z"
    assert resolved.duration_seconds == 3600
    # yt-dlp has no equivalent of the Data API's uploadStatus: permanent unknown.
    assert resolved.upload_status == UNKNOWN
    assert build_scaffold(resolved, "GuestStream", "GuestStream_141")["status"] == "published"


def test_upcoming_premiere_is_scheduled_not_published() -> None:
    """The regression the adapter exists for: a flat pass cannot see this."""
    flat = video_from_manifest_entry(VideoInfo(id="newv0000001", title="Stream", duration=10.0))
    resolved = apply_full_details(
        flat,
        {"availability": "public", "live_status": "is_upcoming"},
    )
    assert resolved.broadcast_status == "upcoming"
    assert resolved.publication_state == "scheduled"
    assert build_scaffold(resolved, "Livestream", "Livestream_200")["status"] == "scheduled"


@pytest.mark.parametrize(
    "details",
    [
        {"availability": "private", "live_status": "not_live"},
        {"availability": "premium", "live_status": "not_live"},
        {"live_status": "not_live"},  # availability absent
        {"availability": "public"},  # live_status absent
        {},
    ],
)
def test_unreported_or_restricted_availability_is_unknown(details: dict[str, Any]) -> None:
    flat = video_from_manifest_entry(VideoInfo(id="newv0000001", title="Talk"))
    resolved = apply_full_details(flat, details)
    assert resolved.publication_state == UNKNOWN
    assert resolved.publication_state != "published"
    assert build_scaffold(resolved, "GuestStream", "GuestStream_142")["status"] == UNKNOWN


def test_absent_extraction_fields_keep_flat_values() -> None:
    flat = video_from_manifest_entry(
        VideoInfo(id="newv0000001", title="Flat title", upload_date="20260920", duration=99.0)
    )
    resolved = apply_full_details(flat, {"availability": "public", "live_status": "not_live"})
    assert resolved.title == "Flat title"
    assert resolved.published_at == "2026-09-20"
    assert resolved.duration_seconds == 99


# ---------------------------------------------- delta resolution & failure mode


def test_delta_only_resolves_new_videos() -> None:
    manifest = _manifest(
        VideoInfo(id="known000001", title="Already ingested"),
        VideoInfo(id="newv0000001", title="New one"),
        VideoInfo(id="newv0000002", title="New two"),
    )
    runner = FakeRunner({"newv0000002": dict(_PUBLISHED_DETAILS)})
    result = build_worklist_from_manifest(manifest, {"known000001"}, runner)
    assert isinstance(result, AdapterResult)
    assert runner.calls == ["newv0000001", "newv0000002"]
    assert result.resolved == 1
    assert result.unresolved == 1
    states = {v.video_id: v.publication_state for v in result.worklist.new_videos}
    assert states == {"newv0000001": UNKNOWN, "newv0000002": "published"}
    assert result.worklist.index_video_count == 1
    assert result.worklist.channel_video_count == 3


def test_failed_extraction_is_unknown_and_never_published() -> None:
    manifest = _manifest(
        VideoInfo(id="newv0000001", title="A"), VideoInfo(id="newv0000002", title="B")
    )
    result = build_worklist_from_manifest(manifest, {"known000001"}, FakeRunner({}))
    assert result.resolved == 0
    assert result.unresolved == 2
    payload = result.worklist.to_dict()
    assert payload["new_video_count"] == 2
    for entry in payload["new_videos"]:
        assert entry["publication_state"] == UNKNOWN
        assert entry["is_scheduled"] is False


def test_max_new_cap_leaves_the_rest_unknown() -> None:
    manifest = _manifest(
        VideoInfo(id="newv0000001", title="A"),
        VideoInfo(id="newv0000002", title="B"),
        VideoInfo(id="newv0000003", title="C"),
    )
    runner = FakeRunner({f"newv{i:07d}": dict(_PUBLISHED_DETAILS) for i in (1, 2, 3)})
    result = build_worklist_from_manifest(manifest, {"known000001"}, runner, max_new=1)
    assert runner.calls == ["newv0000001"]
    assert result.resolved == 1
    assert result.unresolved == 2
    states = [v.publication_state for v in result.worklist.new_videos]
    assert states == ["published", UNKNOWN, UNKNOWN]


def test_max_new_zero_resolves_nothing() -> None:
    manifest = _manifest(VideoInfo(id="newv0000001", title="A"))
    runner = FakeRunner({"newv0000001": dict(_PUBLISHED_DETAILS)})
    result = build_worklist_from_manifest(manifest, {"known000001"}, runner, max_new=0)
    assert runner.calls == []
    assert result.resolved == 0
    assert result.unresolved == 1
    assert result.worklist.new_videos[0].publication_state == UNKNOWN


def test_no_runner_means_no_status_claims() -> None:
    manifest = _manifest(VideoInfo(id="newv0000001", title="A"))
    result = build_worklist_from_manifest(manifest, {"known000001"}, None)
    assert result.resolved == 0
    assert result.unresolved == 1
    assert result.worklist.new_videos[0].publication_state == UNKNOWN


# ------------------------------------------------------------ detail runners


def test_directory_runner_replays_saved_extractions(tmp_path: Path) -> None:
    details_dir = tmp_path / "details"
    details_dir.mkdir()
    (details_dir / "newv0000001.json").write_text(json.dumps(_PUBLISHED_DETAILS), encoding="utf-8")
    (details_dir / "newv0000002.json").write_text("{not json", encoding="utf-8")
    (details_dir / "newv0000003.json").write_text("[1, 2]", encoding="utf-8")
    runner = DirectoryVideoDetailRunner(details_dir)
    assert runner.video_details("newv0000001") == _PUBLISHED_DETAILS
    assert runner.video_details("newv0000002") is None
    assert runner.video_details("newv0000003") is None
    assert runner.video_details("newv9000009") is None


# ----------------------------------------------------------------------- CLI


def test_cli_refuses_empty_index(tmp_path: Path) -> None:
    empty = tmp_path / "empty-journal"
    empty.mkdir()
    with pytest.raises(SystemExit, match="refusing to diff"):
        ytdlp_main(["--journal", str(empty)])


def test_cli_rejects_details_dir_with_no_resolve(tmp_path: Path) -> None:
    journal = _write_index(tmp_path / "journal", "known000001")
    with pytest.raises(SystemExit):
        ytdlp_main(
            [
                "--journal",
                str(journal),
                "--details-dir",
                str(tmp_path),
                "--no-resolve",
            ]
        )


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    journal = _write_index(tmp_path / "journal", "known000001")
    manifest_path = tmp_path / "channel_videos.json"
    save_channel_manifest(
        _manifest(
            VideoInfo(id="known000001", title="Old"),
            VideoInfo(id="newv0000001", title="New", upload_date="20260920"),
        ),
        manifest_path,
    )
    output = tmp_path / "out" / "ingest-worklist.json"
    channel_output = tmp_path / "out" / "channel-manifest.json"
    rc = ytdlp_main(
        [
            "--journal",
            str(journal),
            "--channel-manifest",
            str(manifest_path),
            "--no-resolve",
            "--output",
            str(output),
            "--channel-output",
            str(channel_output),
        ]
    )
    assert rc == 0
    assert not output.exists()
    assert not channel_output.exists()


def test_cli_writes_worklist_and_channel_manifest(tmp_path: Path) -> None:
    journal = _write_index(tmp_path / "journal", "known000001")
    manifest_path = tmp_path / "channel_videos.json"
    save_channel_manifest(
        _manifest(
            VideoInfo(id="known000001", title="Old"),
            VideoInfo(id="newv0000001", title="New Talk", upload_date="20260920"),
        ),
        manifest_path,
    )
    details_dir = tmp_path / "details"
    details_dir.mkdir()
    (details_dir / "newv0000001.json").write_text(json.dumps(_PUBLISHED_DETAILS), encoding="utf-8")
    output = tmp_path / "out" / "ingest-worklist.json"
    channel_output = tmp_path / "out" / "channel-manifest.json"
    rc = ytdlp_main(
        [
            "--journal",
            str(journal),
            "--channel-manifest",
            str(manifest_path),
            "--details-dir",
            str(details_dir),
            "--output",
            str(output),
            "--channel-output",
            str(channel_output),
            "--no-dry-run",
        ]
    )
    assert rc == 0
    worklist = json.loads(output.read_text(encoding="utf-8"))
    assert worklist["new_video_count"] == 1
    new_video = worklist["new_videos"][0]
    assert new_video["video_id"] == "newv0000001"
    assert new_video["publication_state"] == "published"
    assert new_video["published_date"] == "2026-09-20"
    channel_manifest = json.loads(channel_output.read_text(encoding="utf-8"))
    assert channel_manifest["channel_id"] == "UCbPq2w41ZaJSWtpCq4BE6Dg"
    assert channel_manifest["total_videos"] == 2
