"""Integration tests for JournalRAG pipeline with real Cohere API.

These tests make actual API calls to Cohere and should be run less frequently
than unit tests. They require a valid COHERE_API_KEY environment variable.

Run these tests with:
    uv run pytest tests/journal_utilities/rag/integration/ -v -s
"""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("structlog")
pytest.importorskip("cohere")
pytest.importorskip("surrealdb")

from journal_utilities.rag.main import JournalRAGPipeline
from journal_utilities.rag.models import Transcript
from journal_utilities.rag.settings import settings


@pytest.fixture
def sample_transcript_file() -> Path:
    """Get path to sample transcript file."""
    return Path(__file__).parent.parent.parent / "fixtures" / "sample_transcript.txt"


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
    """Mock database client to avoid needing SurrealDB."""
    mock = AsyncMock()
    mock.get_or_create_transcript.return_value = "transcript:test-001"
    mock.create_entity.return_value = "entity:test-001"
    mock.create_relationship.return_value = "relates:test-001"
    mock.update_transcript_status.return_value = None
    return mock


def has_real_cohere_api_key() -> bool:
    """Check if a real Cohere API key is available (not the test mock)."""
    api_key = os.environ.get("COHERE_API_KEY", settings.cohere_api_key)
    return api_key not in ("", "test-api-key", None)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not has_real_cohere_api_key(),
    reason="Requires real COHERE_API_KEY environment variable",
)
async def test_process_transcript_with_real_extractor(
    sample_transcript: Transcript,
    mock_db_client,
) -> None:
    """Integration test: Process transcript with real Cohere API extraction.

    This test:
    1. Uses the real CohereExtractor to call the Cohere API
    2. Processes the sample transcript from tests/fixtures/
    3. Mocks only the database to avoid needing SurrealDB
    4. Validates that real entities are extracted and converted properly

    Note: This test requires a valid COHERE_API_KEY environment variable
    and will make actual API calls, so it may be slower and cost credits.
    """
    # Create pipeline with only DB mocked (extractor is real)
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    # pipeline.extractor is the real CohereExtractor

    # Process the transcript with real API extraction
    stats = await pipeline.process_transcript(sample_transcript)

    # Verify database interactions occurred
    mock_db_client.get_or_create_transcript.assert_called_once()
    assert mock_db_client.create_entity.call_count > 0
    mock_db_client.update_transcript_status.assert_called_once_with(
        "transcript:test-001", processed=True
    )

    # Verify stats from real extraction
    assert "entities" in stats
    assert "relationships" in stats
    assert stats["entities"] > 0, "Should extract at least some entities from the transcript"

    # Verify that real entities were created with proper types
    entity_calls = mock_db_client.create_entity.call_args_list
    entity_types = {call[0][0].type for call in entity_calls}

    # The real extractor should find multiple entity types
    print(f"\nExtracted {stats['entities']} entities of types: {entity_types}")
    print(f"Extracted {stats['relationships']} relationships")

    # Verify we got some of the expected entity types
    # (the actual types depend on what the Cohere API extracts)
    assert len(entity_types) > 0, "Should have extracted entities of various types"

    # Sample some entity names to verify they're reasonable
    entity_names = [call[0][0].name for call in entity_calls[:5]]  # First 5 entities
    print(f"Sample entity names: {entity_names}")

    # Basic sanity check - entities should have names
    for entity_call in entity_calls:
        entity = entity_call[0][0]
        assert entity.name, "Entity should have a name"
        assert entity.type, "Entity should have a type"
        assert isinstance(entity.confidence, float), "Entity should have a confidence score"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not has_real_cohere_api_key(),
    reason="Requires real COHERE_API_KEY environment variable",
)
async def test_real_extraction_finds_expected_content(
    sample_transcript: Transcript,
    mock_db_client,
) -> None:
    """Integration test: Verify real extraction finds expected entities from sample transcript.

    This test validates that the Cohere API successfully extracts specific
    entities we know are in the sample transcript (Active Inference, Karl Friston, etc.).
    """
    # Create pipeline with only DB mocked
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client

    # Process the transcript
    stats = await pipeline.process_transcript(sample_transcript)

    # Get all extracted entity names
    entity_calls = mock_db_client.create_entity.call_args_list
    entity_names_lower = {call[0][0].name.lower() for call in entity_calls}

    print(f"\nExtracted {len(entity_names_lower)} unique entities")
    print(f"Sample entities: {sorted(list(entity_names_lower)[:10])}")

    # Verify some expected entities are found
    # The transcript contains these key terms
    expected_terms = [
        "active inference",
        "free energy",
        "variational",
        "markov",
    ]

    found_terms = []
    for term in expected_terms:
        # Check if the term appears in any extracted entity name
        if any(term in name for name in entity_names_lower):
            found_terms.append(term)

    print(f"Found expected terms: {found_terms}")
    print(f"Total entities: {stats['entities']}, relationships: {stats['relationships']}")

    # We should find at least some of the expected terms
    assert len(found_terms) >= 2, (
        f"Should find at least 2 expected terms from the transcript. "
        f"Found: {found_terms}, Expected: {expected_terms}"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not has_real_cohere_api_key(),
    reason="Requires real COHERE_API_KEY environment variable",
)
async def test_full_pipeline_with_real_file(
    sample_transcript_file: Path,
    mock_db_client,
) -> None:
    """Integration test: Full end-to-end pipeline with file loading and real extraction.

    This test simulates the complete user workflow:
    1. Load transcript from file
    2. Extract entities with real Cohere API
    3. Store in database (mocked)
    """
    # Create pipeline
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client

    # Process file directly (like a user would)
    stats = await pipeline.process_transcript_file(sample_transcript_file)

    # Verify complete workflow succeeded
    assert stats["entities"] > 0, "Should extract entities from the file"
    assert "relationships" in stats

    # Verify the content was actually read and processed
    extractor_call = mock_db_client.get_or_create_transcript.call_args
    assert extractor_call is not None

    print(f"\n✓ Successfully processed {sample_transcript_file.name}")
    print(f"  Entities: {stats['entities']}")
    print(f"  Relationships: {stats['relationships']}")
