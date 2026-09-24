"""Unit tests for JournalRAG pipeline.

These tests use mocked dependencies for fast, isolated testing.
For integration tests with real Cohere API, see tests/journal_utilities/rag/integration/test_pipeline_integration.py
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("structlog")
pytest.importorskip("cohere")
pytest.importorskip("surrealdb")

from journal_utilities.rag.main import JournalRAGPipeline
from journal_utilities.rag.models import CoreEntities, Transcript


@pytest.fixture
def sample_transcript_file() -> Path:
    """Get path to sample transcript file."""
    return Path(__file__).parent.parent.parent.parent / "fixtures" / "sample_transcript.txt"


@pytest.fixture
def sample_transcript(sample_transcript_file: Path) -> Transcript:
    """Create a sample transcript object from the fixture file."""
    content = sample_transcript_file.read_text(encoding="utf-8")
    return Transcript(
        title="Active Inference Test",
        date=datetime(2025, 10, 30),
        content=content,
        source=str(sample_transcript_file),
        processed=False,
    )


@pytest.fixture
def mock_db_client():
    """Mock database client."""
    mock = AsyncMock()
    mock.get_or_create_transcript.return_value = "transcript:test-001"
    mock.create_entity.return_value = "entity:test-001"
    mock.create_relationship.return_value = "relates:test-001"
    mock.update_transcript_status.return_value = None
    return mock


@pytest.fixture
def mock_extractor(sample_core_entities: CoreEntities):
    """Mock Cohere extractor."""
    mock = MagicMock()
    mock.extract_core_entities.return_value = sample_core_entities
    return mock


@pytest.mark.asyncio
async def test_process_transcript_with_file(
    sample_transcript: Transcript,
    sample_core_entities: CoreEntities,
    mock_db_client,
    mock_extractor,
) -> None:
    """Test processing a transcript from a file.

    This test:
    1. Loads a real transcript from tests/fixtures/sample_transcript.txt
    2. Mocks the database and API calls
    3. Runs process_transcript
    4. Verifies entities and relationships were extracted and stored
    """
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Process the transcript
    stats = await pipeline.process_transcript(sample_transcript)

    # Verify database interactions
    mock_db_client.get_or_create_transcript.assert_called_once()
    assert mock_db_client.create_entity.call_count > 0
    mock_db_client.update_transcript_status.assert_called_once_with(
        "transcript:test-001", processed=True
    )

    # Verify extractor was called
    mock_extractor.extract_core_entities.assert_called_once_with(sample_transcript.content)

    # Verify stats
    assert "entities" in stats
    assert "relationships" in stats
    assert stats["entities"] > 0
    assert isinstance(stats["entities"], int)
    assert isinstance(stats["relationships"], int)


@pytest.mark.asyncio
async def test_process_transcript_counts_entities_correctly(
    sample_transcript: Transcript,
    sample_core_entities: CoreEntities,
    mock_db_client,
    mock_extractor,
) -> None:
    """Test that process_transcript correctly counts entities."""
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Process the transcript
    stats = await pipeline.process_transcript(sample_transcript)

    # Calculate expected entity count from sample_core_entities
    # 2 concepts + 2 researchers + 1 citation + 1 technical_term + 2 key_insights
    expected_entity_count = (
        len(sample_core_entities.concepts)
        + len(sample_core_entities.researchers)
        + len(sample_core_entities.citations)
        + len(sample_core_entities.technical_terms)
        + len(sample_core_entities.key_insights)
    )

    assert stats["entities"] == expected_entity_count
    assert mock_db_client.create_entity.call_count == expected_entity_count


@pytest.mark.asyncio
async def test_process_transcript_handles_relationship_errors(
    sample_transcript: Transcript,
    sample_core_entities: CoreEntities,
    mock_db_client,
    mock_extractor,
) -> None:
    """Test that process_transcript handles relationship creation errors gracefully."""
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Make relationship creation fail - the sample fixture only generates 1 relationship
    mock_db_client.create_relationship.side_effect = ValueError("Entity not found")

    # Process the transcript - should not raise exception
    stats = await pipeline.process_transcript(sample_transcript)

    # Should have processed all entities but failed on relationships
    assert "entities" in stats
    assert "relationships" in stats
    # Should have 0 successful relationships since we made it fail
    assert stats["relationships"] == 0


@pytest.mark.asyncio
async def test_process_transcript_updates_transcript_status(
    sample_transcript: Transcript,
    sample_core_entities: CoreEntities,
    mock_db_client,
    mock_extractor,
) -> None:
    """Test that process_transcript marks transcript as processed."""
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Process the transcript
    await pipeline.process_transcript(sample_transcript)

    # Verify transcript was marked as processed
    mock_db_client.update_transcript_status.assert_called_once_with(
        "transcript:test-001", processed=True
    )


@pytest.mark.asyncio
async def test_process_transcript_file_loads_and_processes(
    sample_transcript_file: Path,
    sample_core_entities: CoreEntities,
    mock_db_client,
    mock_extractor,
) -> None:
    """Test process_transcript_file loads file and processes it."""
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Process the file directly
    stats = await pipeline.process_transcript_file(sample_transcript_file)

    # Verify file was loaded and processed
    mock_extractor.extract_core_entities.assert_called_once()
    extracted_content = mock_extractor.extract_core_entities.call_args[0][0]
    assert "Active Inference" in extracted_content
    assert "Karl Friston" in extracted_content

    # Verify stats
    assert stats["entities"] > 0
    assert "relationships" in stats


@pytest.mark.asyncio
async def test_process_transcript_converts_entities_correctly(
    sample_transcript: Transcript,
    sample_core_entities: CoreEntities,
    mock_db_client,
    mock_extractor,
) -> None:
    """Test that CoreEntities are converted to Entity objects correctly."""
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Process the transcript
    await pipeline.process_transcript(sample_transcript)

    # Get all entities that were created
    entity_calls = mock_db_client.create_entity.call_args_list

    # Verify entity types
    entity_types = {call[0][0].type for call in entity_calls}
    assert "concept" in entity_types
    assert "researcher" in entity_types
    assert "citation" in entity_types
    assert "technical_term" in entity_types
    assert "key_insight" in entity_types

    # Verify specific entity names
    entity_names = {call[0][0].name for call in entity_calls}
    assert "Active Inference" in entity_names
    assert "Karl Friston" in entity_names
