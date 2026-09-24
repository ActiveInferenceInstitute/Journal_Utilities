"""
Test suite for importer module with mocks.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("surrealdb")

from journal_utilities.data.importer import insert_missing_sessions_from_json


class TestInsertMissingSessionsFromJson:
    """Tests for session import with mocked database."""

    @pytest.fixture
    def sample_coda_json(self, tmp_path):
        """Create sample Coda JSON file."""
        data = {
            "items": [
                {
                    "values": {
                        "YouTube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        "Unique event name": "Livestream #001.1",
                        "Date": "2025-01-15T10:00:00.000-08:00",
                        "Guests": "Test Guest",
                    }
                },
                {
                    "values": {
                        "YouTube": "https://youtu.be/abc123xyz99",
                        "Unique event name": "GuestStream #002.1",
                    }
                }
            ]
        }

        json_file = tmp_path / "test_coda.json"
        json_file.write_text(json.dumps(data))
        return str(json_file)

    @pytest.fixture
    def mock_db_client(self):
        """Create mock database client."""
        mock = AsyncMock()
        mock.query = AsyncMock(return_value=[])  # No existing sessions
        mock.create = AsyncMock(return_value={"id": "session:test"})
        mock.__aenter__ = AsyncMock(return_value=mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        return mock

    @pytest.mark.asyncio
    async def test_import_new_sessions(self, sample_coda_json, mock_db_client):
        """Test importing new sessions."""
        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            stats = await insert_missing_sessions_from_json(
                sample_coda_json,
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        assert stats["total"] == 2
        assert stats["inserted"] == 2
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_skip_existing_sessions(self, sample_coda_json, mock_db_client):
        """Test skipping existing sessions."""
        # Return existing session for first query
        mock_db_client.query = AsyncMock(return_value=[{"id": "session:existing"}])

        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            stats = await insert_missing_sessions_from_json(
                sample_coda_json,
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        assert stats["total"] == 2
        assert stats["skipped"] == 2
        assert stats["inserted"] == 0

    @pytest.mark.asyncio
    async def test_handles_invalid_youtube_url(self, tmp_path, mock_db_client):
        """Test handling of invalid YouTube URLs."""
        data = {
            "items": [
                {
                    "values": {
                        "YouTube": "https://invalid-url.com/video",
                        "Unique event name": "Test Event",
                    }
                }
            ]
        }

        json_file = tmp_path / "invalid.json"
        json_file.write_text(json.dumps(data))

        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            stats = await insert_missing_sessions_from_json(
                str(json_file),
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        assert stats["total"] == 1
        assert stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_handles_file_not_found(self, mock_db_client):
        """Test handling of missing JSON file."""
        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            stats = await insert_missing_sessions_from_json(
                "/nonexistent/file.json",
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        # Should return empty stats when file read fails
        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_creates_audit_records(self, sample_coda_json, mock_db_client):
        """Test that audit records are created."""
        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            await insert_missing_sessions_from_json(
                sample_coda_json,
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        # Should have created audit records
        create_calls = mock_db_client.create.call_args_list

        # At least: 2 session inserts + 2 audit records + 1 summary
        assert len(create_calls) >= 5

    @pytest.mark.asyncio
    async def test_categorizes_events(self, sample_coda_json, mock_db_client):
        """Test that events are properly categorized."""
        captured_sessions = []

        async def capture_create(table, data):
            if table == 'session':
                captured_sessions.append(data)
            return {"id": f"{table}:test"}

        mock_db_client.create = capture_create

        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            await insert_missing_sessions_from_json(
                sample_coda_json,
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        assert len(captured_sessions) == 2
        assert captured_sessions[0]['category'] == 'Livestream'
        assert captured_sessions[1]['category'] == 'GuestStream'


class TestJsonParsing:
    """Tests for JSON parsing edge cases."""

    @pytest.fixture
    def mock_db_client(self):
        mock = AsyncMock()
        mock.query = AsyncMock(return_value=[])
        mock.create = AsyncMock(return_value={"id": "test:1"})
        mock.__aenter__ = AsyncMock(return_value=mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        return mock

    @pytest.mark.asyncio
    async def test_handles_empty_items(self, tmp_path, mock_db_client):
        """Test handling of empty items array."""
        data = {"items": []}

        json_file = tmp_path / "empty.json"
        json_file.write_text(json.dumps(data))

        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            stats = await insert_missing_sessions_from_json(
                str(json_file),
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_handles_list_format(self, tmp_path, mock_db_client):
        """Test handling of bare list format."""
        data = [
            {
                "values": {
                    "YouTube": "https://youtube.com/watch?v=test1234567",
                    "Unique event name": "Test",
                }
            }
        ]

        json_file = tmp_path / "list.json"
        json_file.write_text(json.dumps(data))

        with patch("journal_utilities.importer.DatabaseClient", return_value=mock_db_client):
            stats = await insert_missing_sessions_from_json(
                str(json_file),
                "ws://test:8080",
                "user",
                "pass",
                "db",
                "ns"
            )

        assert stats["total"] == 1


class TestDateParsing:
    """Tests for date parsing."""

    def test_parses_iso_date(self):
        """Test parsing ISO format dates."""
        from datetime import datetime

        date_str = "2025-01-15T10:00:00.000-08:00"
        parsed = datetime.fromisoformat(date_str)

        assert parsed.year == 2025
        assert parsed.month == 1
        assert parsed.day == 15

    def test_handles_invalid_date(self):
        """Test handling of invalid dates."""
        date_str = "invalid-date"

        try:
            datetime.fromisoformat(date_str)
            parsed = True
        except ValueError:
            parsed = False

        assert parsed is False
