"""
Test suite for database module with mocks.

These tests use mocks to avoid requiring a live SurrealDB instance.
"""

from unittest.mock import AsyncMock, patch

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("surrealdb")

from journal_utilities.data.database import (
    DatabaseClient,
    DatabaseConfig,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig dataclass."""

    def test_default_values(self, monkeypatch):
        """Test default configuration values."""
        # Clear environment
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.delenv("DB_USER", raising=False)
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)
        monkeypatch.delenv("DB_NAMESPACE", raising=False)

        config = DatabaseConfig()
        assert config.url == "ws://localhost:8080/rpc"
        assert config.user == "root"
        assert config.password == "root"
        assert config.name == "actinf"
        assert config.namespace == "actinf"

    def test_from_env(self, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("DB_URL", "ws://custom:9090/rpc")
        monkeypatch.setenv("DB_USER", "testuser")
        monkeypatch.setenv("DB_PASSWORD", "testpass")
        monkeypatch.setenv("DB_NAME", "testdb")
        monkeypatch.setenv("DB_NAMESPACE", "testns")

        config = DatabaseConfig.from_env()
        assert config.url == "ws://custom:9090/rpc"
        assert config.user == "testuser"
        assert config.password == "testpass"
        assert config.name == "testdb"
        assert config.namespace == "testns"


class TestDatabaseClient:
    """Tests for DatabaseClient class."""

    @pytest.fixture
    def mock_surreal(self):
        """Create a mock AsyncSurreal instance."""
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.signin = AsyncMock()
        mock.use = AsyncMock()
        mock.close = AsyncMock()
        mock.query = AsyncMock(return_value=[])
        mock.create = AsyncMock(return_value={"id": "test:1"})
        return mock

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return DatabaseConfig(
            url="ws://test:8080/rpc",
            user="testuser",
            password="testpass",
            name="testdb",
            namespace="testns"
        )

    @pytest.mark.asyncio
    async def test_connect(self, mock_surreal, config):
        """Test database connection."""
        with patch("journal_utilities.data.database.AsyncSurreal", return_value=mock_surreal):
            client = DatabaseClient(config)
            await client.connect()

            mock_surreal.connect.assert_called_once()
            mock_surreal.signin.assert_called_once_with({
                'username': 'testuser',
                'password': 'testpass'
            })
            mock_surreal.use.assert_called_once_with('testns', 'testdb')
            assert client._connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_surreal, config):
        """Test database disconnection."""
        with patch("journal_utilities.data.database.AsyncSurreal", return_value=mock_surreal):
            client = DatabaseClient(config)
            await client.connect()
            await client.disconnect()

            mock_surreal.close.assert_called_once()
            assert client._connected is False

    @pytest.mark.asyncio
    async def test_query(self, mock_surreal, config):
        """Test query execution."""
        mock_surreal.query.return_value = [{"id": "test:1", "name": "test"}]

        with patch("journal_utilities.data.database.AsyncSurreal", return_value=mock_surreal):
            client = DatabaseClient(config)
            result = await client.query("SELECT * FROM test")

            assert result == [{"id": "test:1", "name": "test"}]
            mock_surreal.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_create(self, mock_surreal, config):
        """Test record creation."""
        mock_surreal.create.return_value = {"id": "test:new", "data": "value"}

        with patch("journal_utilities.data.database.AsyncSurreal", return_value=mock_surreal):
            client = DatabaseClient(config)
            result = await client.create("test", {"data": "value"})

            assert result == {"id": "test:new", "data": "value"}
            mock_surreal.create.assert_called_once_with("test", {"data": "value"})

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_surreal, config):
        """Test async context manager."""
        with patch("journal_utilities.data.database.AsyncSurreal", return_value=mock_surreal):
            async with DatabaseClient(config) as client:
                assert client._connected is True

            mock_surreal.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_connect_on_query(self, mock_surreal, config):
        """Test auto-connection when querying."""
        with patch("journal_utilities.data.database.AsyncSurreal", return_value=mock_surreal):
            client = DatabaseClient(config)
            assert client._connected is False

            await client.query("SELECT * FROM test")

            # Should have auto-connected
            mock_surreal.connect.assert_called_once()


class TestAuditFunctions:
    """Tests for audit trail functions using correct module patching."""

    DB_PATCH = "journal_utilities.data.database.AsyncSurreal"

    @pytest.fixture
    def db_params(self) -> dict:
        return {
            "db_url": "ws://test:8080/rpc",
            "db_user": "testuser",
            "db_password": "testpass",
            "db_name": "testdb",
            "db_namespace": "testns",
        }

    @pytest.fixture
    def mock_surreal(self):
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.signin = AsyncMock()
        mock.use = AsyncMock()
        mock.close = AsyncMock()
        mock.query = AsyncMock(return_value=[])
        mock.create = AsyncMock(return_value={"id": "audit:1"})
        return mock

    @pytest.mark.asyncio
    async def test_get_recent_runs(self, mock_surreal, db_params):
        """get_recent_import_runs returns formatted list."""
        mock_surreal.query.return_value = [
            {
                "import_run_id": "run_1",
                "timestamp": "2025-01-01T00:00:00",
                "source_file": "/data/coda.json",
                "result_data": {"total": 10},
            }
        ]
        with patch(self.DB_PATCH, return_value=mock_surreal):
            from journal_utilities.data.database import get_recent_import_runs
            runs = await get_recent_import_runs(**db_params)
        assert len(runs) == 1
        assert runs[0]["import_run_id"] == "run_1"

    @pytest.mark.asyncio
    async def test_get_import_summary(self, mock_surreal, db_params):
        """get_import_summary returns stats from summary record."""
        mock_surreal.query.return_value = [
            {"result_data": {"total": 20, "inserted": 15, "skipped": 3, "failed": 2}}
        ]
        with patch(self.DB_PATCH, return_value=mock_surreal):
            from journal_utilities.data.database import get_import_summary
            summary = await get_import_summary("run_1", **db_params)
        assert summary["total"] == 20

    @pytest.mark.asyncio
    async def test_get_failed_imports(self, mock_surreal, db_params):
        """get_failed_imports returns failure details."""
        mock_surreal.query.return_value = [
            {
                "session_name": "Fail Session",
                "operation": "insert",
                "error_message": "Duplicate",
                "timestamp": "2025-01-01T01:00:00",
                "data_attempted": {},
            }
        ]
        with patch(self.DB_PATCH, return_value=mock_surreal):
            from journal_utilities.data.database import get_failed_imports
            failures = await get_failed_imports("run_1", **db_params)
        assert len(failures) == 1
        assert failures[0]["session_name"] == "Fail Session"


class TestImportSummary:
    """Tests for import summary stats calculation logic."""

    def test_stats_calculation(self):
        """Stats are calculated correctly from individual records."""
        records = [
            {"operation": "insert", "status": "success"},
            {"operation": "insert", "status": "success"},
            {"operation": "skip", "status": "skipped"},
            {"operation": "insert", "status": "failed"},
            {"operation": "parse_youtube_id", "status": "failed"},
        ]

        stats = {"total": 0, "inserted": 0, "skipped": 0, "failed": 0}
        for record in records:
            if record["operation"] in ["insert", "skip", "parse_youtube_id"]:
                stats["total"] += 1
                if record["status"] == "success":
                    stats["inserted"] += 1
                elif record["status"] == "skipped":
                    stats["skipped"] += 1
                elif record["status"] == "failed":
                    stats["failed"] += 1

        assert stats["total"] == 5
        assert stats["inserted"] == 2
        assert stats["skipped"] == 1
        assert stats["failed"] == 2

