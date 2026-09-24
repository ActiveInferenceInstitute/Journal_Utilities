"""
Test suite for data_loader module.

Tests VideoRecord, SearchIndex, and DataLoader using real data structures
with temporary directories — no mocks.
"""

import json
from pathlib import Path

import pytest

# Requires the interface extra; skip cleanly when it is not installed.
pytest.importorskip("fastapi")

from journal_utilities.interface.data_loader import (
    DataLoader,
    SearchIndex,
    SearchResult,
    VideoRecord,
)

# ---------------------------------------------------------------------------
# VideoRecord tests
# ---------------------------------------------------------------------------


class TestVideoRecord:
    """Tests for VideoRecord dataclass and its methods."""

    def test_youtube_url(self):
        """youtube_url property builds correct URL."""
        record = VideoRecord(id="AbCdEfGhIjK")
        assert record.youtube_url == "https://www.youtube.com/watch?v=AbCdEfGhIjK"

    def test_thumbnail_url(self):
        """thumbnail_url returns medium quality thumbnail."""
        record = VideoRecord(id="test123")
        assert "mqdefault" in record.thumbnail_url
        assert "test123" in record.thumbnail_url

    def test_thumbnail_hq_url(self):
        """thumbnail_hq_url returns high quality thumbnail."""
        record = VideoRecord(id="test123")
        assert "hqdefault" in record.thumbnail_hq_url

    def test_to_dict_basic(self):
        """to_dict includes all core fields."""
        record = VideoRecord(
            id="test",
            title="Test Video",
            upload_date="20240101",
            duration=120.0,
            description="A test.",
            view_count=42,
        )
        d = record.to_dict()
        assert d["id"] == "test"
        assert d["title"] == "Test Video"
        assert d["duration"] == 120.0
        assert d["view_count"] == 42
        assert "youtube_url" in d
        assert "thumbnail_url" in d

    def test_to_dict_transcript_fields(self):
        """to_dict correctly reports transcript state."""
        record = VideoRecord(id="t1", has_transcript=True, transcript_size=5000)
        d = record.to_dict()
        assert d["has_transcript"] is True
        assert d["transcript_size"] == 5000

    def test_to_dict_no_transcript(self):
        """to_dict when no transcript is available."""
        record = VideoRecord(id="t2", has_transcript=False)
        d = record.to_dict()
        assert d["has_transcript"] is False


# ---------------------------------------------------------------------------
# SearchIndex tests
# ---------------------------------------------------------------------------


class TestSearchIndex:
    """Tests for SearchIndex full-text search."""

    @pytest.fixture
    def populated_index(self) -> SearchIndex:
        """Create and populate a search index with sample transcripts."""
        idx = SearchIndex()
        idx.add_document(
            "v1",
            "Active Inference is a framework for understanding brain function "
            "based on the free energy principle developed by Karl Friston."
        )
        idx.add_document(
            "v2",
            "Bayesian inference provides a principled way to update beliefs "
            "in light of new evidence using Bayes theorem."
        )
        idx.add_document(
            "v3",
            "Deep learning models use neural networks with multiple layers "
            "to learn representations of data."
        )
        return idx

    def test_add_and_search(self, populated_index: SearchIndex):
        """Basic search finds matching documents."""
        results = populated_index.search("active inference")
        assert len(results) > 0
        assert results[0].video_id == "v1"

    def test_search_returns_search_results(self, populated_index: SearchIndex):
        """Search returns SearchResult objects."""
        results = populated_index.search("bayesian")
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_scores_ordered(self, populated_index: SearchIndex):
        """Results are ordered by relevance (descending score)."""
        results = populated_index.search("inference")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_limit(self, populated_index: SearchIndex):
        """Limit parameter caps result count."""
        results = populated_index.search("inference", limit=1)
        assert len(results) <= 1

    def test_search_no_match(self, populated_index: SearchIndex):
        """No results for unmatched query."""
        results = populated_index.search("quantum entanglement")
        assert len(results) == 0

    def test_get_transcript(self, populated_index: SearchIndex):
        """get_transcript returns stored text."""
        text = populated_index.get_transcript("v1")
        assert text is not None
        assert "Active Inference" in text

    def test_get_transcript_missing(self, populated_index: SearchIndex):
        """get_transcript returns None for unknown video."""
        assert populated_index.get_transcript("nonexistent") is None

    def test_get_context_chunks(self, populated_index: SearchIndex):
        """get_context_chunks returns context dicts."""
        chunks = populated_index.get_context_chunks("free energy principle")
        assert isinstance(chunks, list)
        if chunks:
            assert "video_id" in chunks[0]
            assert "text" in chunks[0]

    def test_search_snippet(self, populated_index: SearchIndex):
        """Search results include a text snippet."""
        results = populated_index.search("friston")
        if results:
            assert results[0].snippet  # Non-empty snippet

    def test_empty_index_search(self):
        """Searching an empty index returns no results."""
        idx = SearchIndex()
        results = idx.search("anything")
        assert results == []


# ---------------------------------------------------------------------------
# DataLoader tests
# ---------------------------------------------------------------------------


class TestDataLoader:
    """Tests for DataLoader with real temporary data."""

    @pytest.fixture
    def data_dir(self, tmp_path: Path) -> Path:
        """Create a realistic data directory structure."""
        output = tmp_path / "data" / "output"
        output.mkdir(parents=True)

        # channel_videos.json
        manifest = {
            "channel_id": "UCtest",
            "total_videos": 2,
            "videos": [
                {
                    "id": "abc123",
                    "title": "Test Video One",
                    "upload_date": "20240601",
                    "duration": 1200.0,
                    "description": "First test video.",
                    "view_count": 100,
                },
                {
                    "id": "def456",
                    "title": "Test Video Two",
                    "upload_date": "20240715",
                    "duration": 1800.0,
                    "description": "Second test video.",
                    "view_count": 200,
                },
            ],
        }
        (output / "channel_videos.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        # Transcripts
        tx = output / "transcripts"
        tx.mkdir()
        (tx / "abc123.txt").write_text(
            "Hello and welcome to this test video transcript content.",
            encoding="utf-8",
        )

        return output

    def test_load_creates_videos(self, data_dir: Path):
        """DataLoader loads video records from manifest."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        assert len(loader.videos) == 2

    def test_load_indexes_transcripts(self, data_dir: Path):
        """DataLoader indexes transcripts into the search index."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        results = loader.search_index.search("test video transcript")
        assert len(results) > 0

    def test_get_video_by_id(self, data_dir: Path):
        """get_video returns the correct record."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        record = loader.get_video("abc123")
        assert record is not None
        assert record.title == "Test Video One"

    def test_get_video_nonexistent(self, data_dir: Path):
        """get_video returns None for unknown ID."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        assert loader.get_video("zzz999") is None

    def test_get_all_videos_pagination(self, data_dir: Path):
        """get_all_videos supports offset and limit."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        records, total = loader.get_all_videos(offset=0, limit=1)
        assert len(records) == 1
        assert total == 2

    def test_get_stats(self, data_dir: Path):
        """get_stats returns correct aggregate statistics."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        stats = loader.get_stats()
        assert stats["total_videos"] == 2
        assert stats["with_transcripts"] >= 1

    def test_has_transcript_flag(self, data_dir: Path):
        """Videos with transcripts have has_transcript=True."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        record = loader.get_video("abc123")
        assert record is not None
        assert record.has_transcript is True

    def test_no_transcript_flag(self, data_dir: Path):
        """Videos without transcripts have has_transcript=False."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        record = loader.get_video("def456")
        assert record is not None
        assert record.has_transcript is False

    def test_categories_populated(self, data_dir: Path):
        """Categories dict is populated after loading."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        assert isinstance(loader.categories, dict)

    def test_empty_data_dir(self, tmp_path: Path):
        """DataLoader handles empty data directory gracefully."""
        empty = tmp_path / "empty"
        empty.mkdir()
        loader = DataLoader(data_dir=empty)
        loader.load()
        assert len(loader.videos) == 0

    def test_get_all_videos_sort_by_upload_date(self, data_dir: Path):
        """Videos are sorted by upload_date descending by default."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        records, _ = loader.get_all_videos(sort_by="upload_date", reverse=True)
        dates = [r.upload_date for r in records if r.upload_date]
        assert dates == sorted(dates, reverse=True)

    def test_get_all_videos_sort_ascending(self, data_dir: Path):
        """Videos can be sorted in ascending order."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        records, _ = loader.get_all_videos(sort_by="upload_date", reverse=False)
        dates = [r.upload_date for r in records if r.upload_date]
        assert dates == sorted(dates)

    def test_get_all_videos_filter_has_transcript(self, data_dir: Path):
        """Filtering by has_transcript returns only matching videos."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        with_tx, total = loader.get_all_videos(has_transcript=True)
        assert total >= 1
        assert all(r.has_transcript for r in with_tx)

    def test_get_all_videos_filter_no_transcript(self, data_dir: Path):
        """Filtering by has_transcript=False returns only videos without."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        without_tx, total = loader.get_all_videos(has_transcript=False)
        assert total >= 1
        assert all(not r.has_transcript for r in without_tx)

    def test_load_download_manifest(self, data_dir: Path):
        """Download manifest correctly sets transcript/audio asset paths."""
        # Create a download_manifest.json alongside channel_videos.json
        transcript_path = data_dir / "transcripts" / "abc123.txt"
        manifest = {
            "downloads": [
                {
                    "video_id": "abc123",
                    "results": [
                        {
                            "asset_type": "transcript",
                            "status": "success",
                            "path": str(transcript_path),
                            "file_size_bytes": 500,
                        },
                    ],
                }
            ]
        }
        (data_dir / "download_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        record = loader.get_video("abc123")
        assert record is not None
        assert record.has_transcript is True

    def test_load_idempotent(self, data_dir: Path):
        """Calling load() twice does not duplicate videos."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        count_first = len(loader.videos)
        loader.load()
        assert len(loader.videos) == count_first

    def test_get_stats_category_count(self, data_dir: Path):
        """get_stats includes category_count field."""
        loader = DataLoader(data_dir=data_dir)
        loader.load()
        stats = loader.get_stats()
        assert "category_count" in stats
        assert isinstance(stats["category_count"], int)

