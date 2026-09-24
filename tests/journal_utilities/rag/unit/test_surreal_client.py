"""
Unit tests for SurrealDBClient with mocks.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("surrealdb")
pytest.importorskip("structlog")

from journal_utilities.rag.graph.surreal_client import SurrealDBClient
from journal_utilities.rag.models import Entity, Relationship, Transcript


class TestSurrealDBClientInit:
    """Tests for SurrealDBClient initialization."""

    def test_default_initialization(self):
        """Test client initializes with default settings."""
        with patch("journal_utilities.rag.graph.surreal_client.settings") as mock_settings:
            mock_settings.surrealdb_url = "ws://localhost:8080"
            mock_settings.surrealdb_namespace = "test"
            mock_settings.surrealdb_database = "test"
            mock_settings.surrealdb_username = "root"
            mock_settings.surrealdb_password = "root"

            client = SurrealDBClient()

            assert client.url == "ws://localhost:8080"
            assert client.namespace == "test"
            assert client.database == "test"

    def test_custom_initialization(self):
        """Test client with custom parameters."""
        client = SurrealDBClient(
            url="ws://custom:9000",
            namespace="custom_ns",
            database="custom_db",
            username="user",
            password="pass"
        )

        assert client.url == "ws://custom:9000"
        assert client.namespace == "custom_ns"
        assert client.database == "custom_db"


class TestSurrealDBClientConnection:
    """Tests for connection management."""

    @pytest.fixture
    def mock_surreal(self):
        """Create a mock Surreal instance."""
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.signin = AsyncMock()
        mock.use = AsyncMock()
        mock.close = AsyncMock()
        mock.query = AsyncMock(return_value=[])
        mock.create = AsyncMock(return_value=[{"id": "test:1"}])
        mock.update = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_surreal):
        """Test successful connection."""
        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )

            await client.connect()

            mock_surreal.connect.assert_called_once()
            mock_surreal.signin.assert_called_once_with({"user": "user", "pass": "pass"})
            mock_surreal.use.assert_called_once_with("ns", "db")

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_surreal):
        """Test disconnection."""
        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )

            await client.connect()
            await client.disconnect()

            mock_surreal.close.assert_called_once()


class TestSurrealDBClientEntities:
    """Tests for entity operations."""

    @pytest.fixture
    def mock_surreal(self):
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.signin = AsyncMock()
        mock.use = AsyncMock()
        mock.query = AsyncMock(return_value=[{"result": []}])
        mock.create = AsyncMock(return_value=[{"id": "entity:1"}])
        mock.update = AsyncMock()
        return mock

    @pytest.fixture
    def sample_entity(self):
        return Entity(
            name="Test Entity",
            type="concept",
            description="A test entity",
            confidence=0.9,
            mentions=5,
            context=["test context"]
        )

    @pytest.mark.asyncio
    async def test_create_new_entity(self, mock_surreal, sample_entity):
        """Test creating a new entity."""
        mock_surreal.query = AsyncMock(return_value=[{"result": []}])  # No existing

        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )
            await client.connect()

            result = await client.create_entity(sample_entity)

            assert result == "entity:1"
            mock_surreal.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_existing_entity(self, mock_surreal, sample_entity):
        """Test updating an existing entity."""
        mock_surreal.query = AsyncMock(return_value=[{
            "result": [{
                "id": "entity:existing",
                "confidence": 0.8,
                "context": ["old context"],
                "description": "Old description"
            }]
        }])

        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )
            await client.connect()

            result = await client.create_entity(sample_entity)

            assert result == "entity:existing"
            mock_surreal.update.assert_called_once()


class TestSurrealDBClientTranscripts:
    """Tests for transcript operations."""

    @pytest.fixture
    def mock_surreal(self):
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.signin = AsyncMock()
        mock.use = AsyncMock()
        mock.query = AsyncMock(return_value=[{"result": []}])
        mock.create = AsyncMock(return_value=[{"id": "transcript:1"}])
        mock.update = AsyncMock()
        return mock

    @pytest.fixture
    def sample_transcript(self):
        return Transcript(
            title="Test Transcript",
            date=datetime.now(UTC),
            content="Test content",
            source="/path/to/file.txt"
        )

    @pytest.mark.asyncio
    async def test_create_transcript(self, mock_surreal, sample_transcript):
        """Test creating a transcript."""
        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )
            await client.connect()

            result = await client.create_transcript(sample_transcript)

            assert result == "transcript:1"
            mock_surreal.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_unprocessed_transcripts(self, mock_surreal):
        """Test getting unprocessed transcript paths."""
        mock_surreal.query = AsyncMock(return_value=[{
            "result": [
                {"source": "/path/1.txt"},
                {"source": "/path/2.txt"}
            ]
        }])

        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )
            await client.connect()

            paths = await client.get_unprocessed_transcript_paths()

            assert len(paths) == 2
            assert "/path/1.txt" in paths
            assert "/path/2.txt" in paths


class TestSurrealDBClientRelationships:
    """Tests for relationship operations."""

    @pytest.fixture
    def mock_surreal(self):
        mock = AsyncMock()
        mock.connect = AsyncMock()
        mock.signin = AsyncMock()
        mock.use = AsyncMock()
        mock.query = AsyncMock(return_value=[{"result": [{"id": "entity:1"}]}])
        return mock

    @pytest.fixture
    def sample_relationship(self):
        return Relationship(
            source="Entity A",
            target="Entity B",
            relationship_type="relates_to",
            confidence=0.85
        )

    @pytest.mark.asyncio
    async def test_create_relationship_entities_not_found(self, mock_surreal, sample_relationship):
        """Test creating relationship when entities not found."""
        mock_surreal.query = AsyncMock(return_value=[{"result": []}])  # No entities found

        with patch("journal_utilities.rag.graph.surreal_client.Surreal", return_value=mock_surreal):
            client = SurrealDBClient(
                url="ws://test:8080",
                namespace="ns",
                database="db",
                username="user",
                password="pass"
            )
            await client.connect()

            with pytest.raises(ValueError, match="Source or target entity not found"):
                await client.create_relationship(sample_relationship)


class TestSurrealDBClientErrors:
    """Tests for error handling."""

    def test_query_without_connection(self):
        """Test that queries fail without connection."""
        client = SurrealDBClient(
            url="ws://test:8080",
            namespace="ns",
            database="db",
            username="user",
            password="pass"
        )

        # db is None until connect() is called
        assert client.db is None

    @pytest.mark.asyncio
    async def test_create_entity_not_connected(self):
        """Test create_entity raises error when not connected."""
        client = SurrealDBClient(
            url="ws://test:8080",
            namespace="ns",
            database="db",
            username="user",
            password="pass"
        )

        entity = Entity(
            name="Test",
            type="concept",
            confidence=0.9,
            mentions=1,
            context=["test"]
        )

        with pytest.raises(RuntimeError, match="Database not connected"):
            await client.create_entity(entity)
