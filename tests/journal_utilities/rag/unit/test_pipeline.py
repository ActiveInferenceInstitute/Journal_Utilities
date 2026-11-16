"""Unit tests for JournalRAG pipeline.

These tests use mocked dependencies for fast, isolated testing.
For integration tests with real Cohere API, see tests/journal_utilities/rag/integration/test_pipeline_integration.py
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("structlog")
pytest.importorskip("cohere")
pytest.importorskip("surrealdb")

from journal_utilities.rag.main import JournalRAGPipeline, main
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
    mock.create_entity.side_effect = lambda entity: (
        f"entity:{entity.source}-{entity.type}-{entity.name}"
    )
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
    mock_db_client.update_transcript_status.assert_has_awaits(
        [
            call("transcript:test-001", processed=False),
            call("transcript:test-001", processed=True),
        ]
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
    """A required edge failure is visible, stays pending, and can be retried."""
    # Create pipeline with mocked dependencies
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor

    # Make relationship creation fail - the sample fixture only generates 1 relationship
    mock_db_client.create_relationship.side_effect = ValueError("Entity not found")

    with pytest.raises(ValueError, match="Entity not found"):
        await pipeline.process_transcript(sample_transcript)
    assert mock_db_client.update_transcript_status.await_args_list == [
        call("transcript:test-001", processed=False)
    ]
    mock_db_client.create_relationship.side_effect = None
    stats = await pipeline.process_transcript(sample_transcript)
    assert stats["relationships"] == 1
    assert mock_db_client.update_transcript_status.await_args == call(
        "transcript:test-001", processed=True
    )


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
    mock_db_client.update_transcript_status.assert_has_awaits(
        [
            call("transcript:test-001", processed=False),
            call("transcript:test-001", processed=True),
        ]
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


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("talk_2025-10-30.txt", datetime(2025, 10, 30)),
        ("talk_2025.10.30", datetime(2025, 10, 30)),
        ("talk_2025.10.30.txt", datetime(2025, 10, 30)),
        ("undated.txt", datetime.min),
        ("talk_2025-02-30.txt", datetime.min),
    ],
)
async def test_file_and_pending_loaders_share_date_and_source(
    tmp_path, filename, expected, mock_db_client, mock_extractor
):
    path = tmp_path / filename
    path.write_text("Active Inference", encoding="utf-8")
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor
    await pipeline.process_transcript_file(path)
    direct = mock_db_client.get_or_create_transcript.await_args.args[0]
    mock_db_client.get_unprocessed_transcript_paths.return_value = [filename]
    stats = await pipeline.process_from_database(base_path=tmp_path)
    pending = mock_db_client.get_or_create_transcript.await_args.args[0]
    assert stats["processed"] == 1 and stats["failed"] == 0
    assert direct.date == pending.date == expected
    assert direct.source == str(path)
    assert pending.source == filename


async def test_required_missing_endpoint_is_not_discarded(
    sample_transcript, sample_core_entities, mock_db_client, mock_extractor
):
    sample_core_entities.concepts[0].related_concepts = ["Not extracted"]
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor
    with pytest.raises(ValueError, match="Required relationship endpoint missing"):
        await pipeline.process_transcript(sample_transcript)
    assert mock_db_client.update_transcript_status.await_args_list == [
        call("transcript:test-001", processed=False)
    ]
    mock_db_client.create_relationship.assert_not_awaited()


async def test_source_and_type_choose_returned_endpoint_ids(
    sample_transcript, mock_db_client, mock_extractor
):
    from journal_utilities.rag.models import (
        Citation,
        CitationType,
        Concept,
        ConceptCategory,
        Researcher,
        ResearcherRole,
    )

    mock_extractor.extract_core_entities.return_value = CoreEntities(
        concepts=[
            Concept(
                name="Same",
                definition="Concept",
                category=ConceptCategory.THEORETICAL,
                related_concepts=["Same"],
            )
        ],
        researchers=[Researcher(name="Same", role=ResearcherRole.SPEAKER)],
        citations=[Citation(title="Same", type=CitationType.PAPER, authors=["Same"])],
        technical_terms=[],
        key_insights=["One"],
    )
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor
    for source in ("a.txt", "b.txt"):
        await pipeline.process_transcript(sample_transcript.model_copy(update={"source": source}))
    edges = mock_db_client.create_relationship.await_args_list
    assert len(edges) == 4
    for invocation in edges:
        edge = invocation.args[0]
        assert invocation.kwargs == {
            "source_id": f"entity:{edge.transcript_source}-{edge.source_type}-{edge.source}",
            "target_id": f"entity:{edge.transcript_source}-{edge.target_type}-{edge.target}",
        }
    assert {
        invocation.args[0].source for invocation in mock_db_client.create_entity.await_args_list
    } == {"a.txt", "b.txt"}


@pytest.fixture
def cli_boundaries(monkeypatch, mock_db_client, mock_extractor):
    monkeypatch.setattr("journal_utilities.rag.main.SurrealDBClient", lambda: mock_db_client)
    monkeypatch.setattr("journal_utilities.rag.main.CohereExtractor", lambda: mock_extractor)
    return mock_db_client, mock_extractor


def test_cli_requires_work_selection(cli_boundaries):
    db, extractor = cli_boundaries
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    db.connect.assert_not_awaited()
    extractor.extract_core_entities.assert_not_called()


def test_cli_files_perform_work_and_report_missing_file(tmp_path, cli_boundaries):
    db, extractor = cli_boundaries
    path = tmp_path / "2025-10-30.txt"
    path.write_text("Active Inference", encoding="utf-8")
    assert main(["--file", str(path), str(tmp_path / "missing.txt")]) == 1
    extractor.extract_core_entities.assert_called_once_with("Active Inference")
    assert db.update_transcript_status.await_args == call("transcript:test-001", processed=True)
    db.disconnect.assert_awaited_once()


def test_cli_pending_edge_failure_returns_failure_and_disconnects(tmp_path, cli_boundaries):
    db, extractor = cli_boundaries
    (tmp_path / "pending.txt").write_text("Pending", encoding="utf-8")
    db.get_unprocessed_transcript_paths.return_value = ["pending.txt"]
    db.create_relationship.side_effect = RuntimeError("edge write failed")
    assert main(["--pending", "--base-path", str(tmp_path)]) == 1
    extractor.extract_core_entities.assert_called_once_with("Pending")
    assert db.update_transcript_status.await_args_list == [
        call("transcript:test-001", processed=False)
    ]
    db.disconnect.assert_awaited_once()


def test_cli_empty_pending_does_not_invoke_provider(cli_boundaries):
    db, extractor = cli_boundaries
    db.get_unprocessed_transcript_paths.return_value = []
    assert main(["--pending"]) == 0
    extractor.extract_core_entities.assert_not_called()
    db.disconnect.assert_awaited_once()


def test_cli_connect_failure_still_disconnects(cli_boundaries):
    db, extractor = cli_boundaries
    db.connect.side_effect = RuntimeError("offline")
    assert main(["--pending"]) == 1
    extractor.extract_core_entities.assert_not_called()
    db.disconnect.assert_awaited_once()


def test_cli_explicit_migration_does_not_extract(cli_boundaries):
    db, extractor = cli_boundaries
    db.migration_summary = {"unknown_source_entities": 2}
    assert main(["--migrate-source-identity"]) == 0
    db.connect.assert_awaited_once_with(migrate_source_identity=True)
    extractor.extract_core_entities.assert_not_called()
    db.disconnect.assert_awaited_once()


async def test_no_required_relationships_can_complete(
    sample_transcript, mock_db_client, mock_extractor
):
    mock_extractor.extract_core_entities.return_value = CoreEntities(
        concepts=[], researchers=[], citations=[], technical_terms=[], key_insights=["An insight"]
    )
    pipeline = JournalRAGPipeline()
    pipeline.db_client = mock_db_client
    pipeline.extractor = mock_extractor
    assert await pipeline.process_transcript(sample_transcript) == {
        "entities": 1,
        "relationships": 0,
    }
    mock_db_client.create_relationship.assert_not_awaited()
    assert mock_db_client.update_transcript_status.await_args == call(
        "transcript:test-001", processed=True
    )
