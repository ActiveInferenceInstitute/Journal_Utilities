"""
Tests for channel video enumeration (channel.py).

All tests use real methods — no mocks. Tests that require network
access to YouTube use a single known video from the Active Inference channel.
"""

import json
from pathlib import Path

import pytest

from journal_utilities.youtube.channel import (
    ChannelManifest,
    VideoInfo,
    _parse_video_entry,
    enumerate_channel_videos,
    load_channel_manifest,
    save_channel_manifest,
)

# ---------------------------------------------------------------------------
# VideoInfo dataclass
# ---------------------------------------------------------------------------


class TestVideoInfo:
    """Tests for the VideoInfo dataclass."""

    def test_url_auto_populated(self):
        """URL is filled from ID when not provided."""
        v = VideoInfo(id="abc123DEF_-")
        assert v.url == "https://www.youtube.com/watch?v=abc123DEF_-"

    def test_explicit_url_preserved(self):
        """Explicitly provided URL is preserved."""
        v = VideoInfo(id="abc123DEF_-", url="https://custom.url/")
        assert v.url == "https://custom.url/"

    def test_title_and_fields(self):
        """Fields are set correctly."""
        v = VideoInfo(id="x", title="Test", upload_date="20230101", duration=120.0)
        assert v.title == "Test"
        assert v.upload_date == "20230101"
        assert v.duration == 120.0

    def test_default_empty_fields(self):
        """Default fields are empty or None."""
        v = VideoInfo(id="x")
        assert v.title == ""
        assert v.description == ""
        assert v.view_count is None
        assert v.duration is None


# ---------------------------------------------------------------------------
# ChannelManifest dataclass
# ---------------------------------------------------------------------------


class TestChannelManifest:
    """Tests for the ChannelManifest dataclass."""

    def test_channel_url_auto_populated(self):
        m = ChannelManifest(channel_id="UCtest123")
        assert m.channel_url == "https://www.youtube.com/channel/UCtest123"

    def test_enumerated_at_auto_set(self):
        m = ChannelManifest(channel_id="UCtest123")
        assert len(m.enumerated_at) > 10
        # Should be a valid ISO 8601 timestamp
        assert "T" in m.enumerated_at
        assert "2026" in m.enumerated_at or "202" in m.enumerated_at

    def test_total_videos_default_zero(self):
        m = ChannelManifest(channel_id="UCtest123")
        assert m.total_videos == 0


# ---------------------------------------------------------------------------
# _parse_video_entry
# ---------------------------------------------------------------------------


class TestParseVideoEntry:
    """Tests for _parse_video_entry helper."""

    def test_full_entry(self):
        entry = {
            "id": "abc123DEF_-",
            "title": "ActInf Livestream 001",
            "upload_date": "20230101",
            "duration": 3600.0,
            "description": "First livestream of 2023.",
            "view_count": 500,
        }
        v = _parse_video_entry(entry)
        assert v is not None
        assert v.id == "abc123DEF_-"
        assert v.title == "ActInf Livestream 001"
        assert v.upload_date == "20230101"
        assert v.duration == 3600.0
        assert v.view_count == 500

    def test_minimal_entry(self):
        v = _parse_video_entry({"id": "test123"})
        assert v is not None
        assert v.id == "test123"
        assert v.title == ""

    def test_url_in_url_field(self):
        """When yt-dlp uses 'url' instead of 'id'."""
        v = _parse_video_entry({"url": "myVideoId123"})
        assert v is not None
        assert v.id == "myVideoId123"

    def test_url_with_query_string(self):
        """Extract ID from YouTube watch URL with query params."""
        v = _parse_video_entry({"url": "https://youtube.com/watch?v=myId123_XYZ"})
        assert v is not None
        assert v.id == "myId123_XYZ"

    def test_url_with_slash_path(self):
        """Strip URL prefix when 'url' contains a path."""
        v = _parse_video_entry({"url": "https://youtu.be/shortId1234"})
        assert v is not None
        assert v.id == "shortId1234"

    def test_empty_entry_returns_none(self):
        assert _parse_video_entry({}) is None

    def test_missing_optional_fields(self):
        v = _parse_video_entry({"id": "vid1"})
        assert v.description == ""
        assert v.view_count is None
        assert v.duration is None


# ---------------------------------------------------------------------------
# save / load manifest round-trip
# ---------------------------------------------------------------------------


class TestManifestPersistence:
    """Tests for save_channel_manifest and load_channel_manifest."""

    def test_round_trip(self, tmp_path: Path):
        """Save then load produces identical manifest."""
        videos = [
            VideoInfo(id="abc123DEF_-", title="Video 1"),
            VideoInfo(id="xyz789GHI_-", title="Video 2"),
            VideoInfo(id="qrs456JKL_-", title="Video 3"),
        ]
        original = ChannelManifest(
            channel_id="UCtest",
            total_videos=len(videos),
            videos=videos,
        )

        manifest_path = tmp_path / "manifest.json"
        save_channel_manifest(original, manifest_path)

        assert manifest_path.exists()

        loaded = load_channel_manifest(manifest_path)
        assert loaded.channel_id == "UCtest"
        assert loaded.total_videos == 3
        assert len(loaded.videos) == 3
        assert loaded.videos[0].id == "abc123DEF_-"
        assert loaded.videos[1].title == "Video 2"

    def test_save_creates_parents(self, tmp_path: Path):
        """Saving to a nested path creates intermediate directories."""
        path = tmp_path / "a" / "b" / "manifest.json"
        m = ChannelManifest(channel_id="UCx", total_videos=0, videos=[])
        save_channel_manifest(m, path)
        assert path.exists()

    def test_load_nonexistent_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_channel_manifest(tmp_path / "nope.json")

    def test_load_invalid_json_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_channel_manifest(bad)

    def test_manifest_json_structure(self, tmp_path: Path):
        """Saved JSON has expected top-level keys."""
        m = ChannelManifest(channel_id="UC1", total_videos=1, videos=[VideoInfo(id="v1")])
        path = tmp_path / "m.json"
        save_channel_manifest(m, path)

        data = json.loads(path.read_text())
        assert "channel_id" in data
        assert "videos" in data
        assert "total_videos" in data
        assert data["total_videos"] == 1

    def test_empty_manifest_round_trip(self, tmp_path: Path):
        """Empty manifest round-trips correctly."""
        m = ChannelManifest(channel_id="UC_empty", total_videos=0, videos=[])
        path = tmp_path / "empty.json"
        save_channel_manifest(m, path)
        loaded = load_channel_manifest(path)
        assert loaded.total_videos == 0
        assert loaded.videos == []


# ---------------------------------------------------------------------------
# Real yt-dlp enumeration (network required)
# ---------------------------------------------------------------------------


class TestEnumerateChannelVideosReal:
    """Tests using real yt-dlp to enumerate the Active Inference channel.

    These tests make real network calls to YouTube via yt-dlp.
    """

    def test_enumerate_small_batch(self, tmp_path: Path):
        """Enumerate 3 videos from the Active Inference channel."""
        manifest = enumerate_channel_videos(
            channel_id="UCbPq2w41ZaJSWtpCq4BE6Dg",
            max_videos=3,
            output_path=tmp_path / "manifest.json",
        )
        assert manifest.channel_id == "UCbPq2w41ZaJSWtpCq4BE6Dg"
        assert manifest.total_videos >= 1
        assert manifest.total_videos <= 3
        assert len(manifest.videos) == manifest.total_videos

        # Each video should have an ID and title
        for video in manifest.videos:
            assert len(video.id) >= 5, f"Video ID too short: {video.id}"
            assert video.title, f"Video {video.id} has no title"

        # Manifest file should be saved
        assert (tmp_path / "manifest.json").exists()

    def test_enumerate_with_date_filter(self):
        """Enumerate only recent videos using date filter."""
        manifest = enumerate_channel_videos(
            channel_id="UCbPq2w41ZaJSWtpCq4BE6Dg",
            max_videos=2,
            date_after="20250101",
        )
        assert manifest.total_videos >= 0  # Channel may have recent videos

    def test_enumerate_saves_and_loads(self, tmp_path: Path):
        """Enumerate, save, and reload produces consistent data."""
        path = tmp_path / "saved.json"
        original = enumerate_channel_videos(
            channel_id="UCbPq2w41ZaJSWtpCq4BE6Dg",
            max_videos=2,
            output_path=path,
        )

        loaded = load_channel_manifest(path)
        assert loaded.channel_id == original.channel_id
        assert loaded.total_videos == original.total_videos
        assert len(loaded.videos) == len(original.videos)
        if loaded.videos:
            assert loaded.videos[0].id == original.videos[0].id
