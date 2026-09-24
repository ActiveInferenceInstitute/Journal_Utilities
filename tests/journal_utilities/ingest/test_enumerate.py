"""Unit tests for journal_utilities.ingest.enumerate — fake service only.

No network, no API key. The fake service (tests/journal_utilities/ingest/
fake_service.py) stands in for googleapiclient, same pattern as
tests/youtube/test_client.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from journal_utilities.ingest.enumerate import (
    ChannelVideo,
    build_worklist,
    enumerate_channel_videos,
    load_index_video_ids,
    parse_iso8601_duration,
)
from journal_utilities.ingest.enumerate import (
    main as enumerate_main,
)
from journal_utilities.youtube.client import YouTubeClient

from .fake_service import FakeService, playlist_item, video_item


def _client(service: FakeService) -> YouTubeClient:
    return YouTubeClient(service=service)


def _service_with_videos(*videos: tuple[str, str]) -> FakeService:
    """Fake service with one playlist item + matching videos.list payload."""
    return FakeService(
        playlist_items=[playlist_item(vid) for vid, _ in videos],
        videos_by_id={vid: video_item(vid, title) for vid, title in videos},
    )


@pytest.fixture()
def journal(tmp_path: Path) -> Path:
    """Journal checkout root with an INDEX.json referencing two videos."""
    root = tmp_path / "journal"
    (root / "data" / "output").mkdir(parents=True)
    (root / "INDEX.json").write_text(
        json.dumps(
            {
                "count": 1,
                "videos": 2,
                "unique_videos": 2,
                "items": [
                    {
                        "path": "data/video/activeinferenceinstitute/GuestStream/GuestStream_001",
                        "series": "GuestStream",
                        "item": "GuestStream_001",
                        "parts": ["known1", "known2"],
                        "has_transcript": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_parse_iso8601_duration() -> None:
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("P1DT2H") == 93600
    assert parse_iso8601_duration("PT30S") == 30
    assert parse_iso8601_duration("PT0S") == 0
    assert parse_iso8601_duration("") is None
    assert parse_iso8601_duration("bogus") is None
    assert parse_iso8601_duration("PT") is None


def test_enumerate_merges_playlist_and_video_details() -> None:
    service = _service_with_videos(
        ("vid1", "ActInf GuestStream #141.1 ~ Talk"),
        ("vid2", "Active Inference Insights 025 ~ Someone"),
    )
    videos = enumerate_channel_videos(_client(service), "UCfake")
    assert [v.video_id for v in videos] == ["vid1", "vid2"]
    first = videos[0]
    assert first.title == "ActInf GuestStream #141.1 ~ Talk"
    assert first.published_date == "2026-09-20"
    assert first.duration_seconds == 3600
    assert first.upload_status == "processed"
    assert first.url == "https://www.youtube.com/watch?v=vid1"
    # Read-only list calls only: one playlist page + one batched videos.list.
    assert service.playlist_pages_served == 1
    assert service.videos_listed == ["vid1,vid2"]


def test_enumerate_paginates_playlist() -> None:
    service = _service_with_videos(("vid1", "t1"), ("vid2", "t2"))
    service.playlist_items = [playlist_item(f"v{i:03d}") for i in range(55)]
    service.videos_by_id = {f"v{i:03d}": video_item(f"v{i:03d}", f"t{i}") for i in range(55)}
    videos = enumerate_channel_videos(_client(service), "UCfake")
    assert len(videos) == 55
    assert service.playlist_pages_served == 2


def test_enumerate_marks_premiere_scheduled() -> None:
    service = _service_with_videos(("prem1", "ActInf Livestream #100.1 ~ Soon"))
    service.videos_by_id["prem1"] = video_item(
        "prem1", "ActInf Livestream #100.1 ~ Soon", live_broadcast="upcoming"
    )
    videos = enumerate_channel_videos(_client(service), "UCfake")
    assert videos[0].is_scheduled is True


def test_enumerate_falls_back_to_playlist_snippet_when_videos_list_misses() -> None:
    service = _service_with_videos(("vid1", "t1"))
    service.videos_by_id = {}  # videos.list returns nothing
    videos = enumerate_channel_videos(_client(service), "UCfake")
    assert videos[0].video_id == "vid1"
    assert videos[0].title == "title-for-vid1"
    assert videos[0].duration_seconds is None


def test_enumerate_fails_without_uploads_playlist() -> None:
    service = _service_with_videos(("vid1", "t"))
    service.channel_uploads = ""
    with pytest.raises(RuntimeError, match="uploads playlist"):
        enumerate_channel_videos(_client(service), "UCfake")


def test_channel_video_scheduled_via_upload_status() -> None:
    assert ChannelVideo(video_id="x", title="t", upload_status="unpublished").is_scheduled
    assert not ChannelVideo(video_id="x", title="t", upload_status="processed").is_scheduled


def test_load_index_video_ids(journal: Path) -> None:
    assert load_index_video_ids(journal / "INDEX.json") == {"known1", "known2"}


def test_load_index_video_ids_tolerates_missing(tmp_path: Path) -> None:
    assert load_index_video_ids(tmp_path / "nope.json") == set()


def test_diff_against_index_and_worklist(journal: Path) -> None:
    service = _service_with_videos(("known1", "already in journal"), ("new1", "Fresh Talk"))
    worklist = build_worklist(_client(service), journal / "INDEX.json", "UCfake")
    assert worklist.index_video_count == 2
    assert worklist.channel_video_count == 2
    assert [v.video_id for v in worklist.new_videos] == ["new1"]
    payload = worklist.to_dict()
    assert payload["new_video_count"] == 1
    assert payload["new_videos"][0]["video_id"] == "new1"
    assert payload["new_videos"][0]["is_scheduled"] is False


def test_cli_refuses_empty_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed/empty INDEX must be fatal, not 'everything is new'."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake-key-for-test")
    empty = tmp_path / "empty-journal"
    empty.mkdir()
    with pytest.raises(SystemExit, match="refusing to diff"):
        enumerate_main(["--journal", str(empty)])


def test_cli_dry_run_does_not_write_output(journal: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (dry-run) never writes the worklist file."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "fake-key-for-test")
    service = _service_with_videos(("new1", "Fresh Talk"))
    client = YouTubeClient(service=service)
    import journal_utilities.ingest.enumerate as enum_mod

    monkeypatch.setattr(enum_mod, "_build_client", lambda api_key: client)
    output = journal / "out" / "worklist.json"
    rc = enumerate_main(["--journal", str(journal), "--output", str(output)])
    assert rc == 0
    assert not output.exists()
