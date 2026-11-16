# AGENTS.md - Tests

## Test Suite Overview

Counts and coverage are generated measurements, not maintained prose. See
[`../docs/_generated/gate-arms.md`](../docs/_generated/gate-arms.md) for the
recorded source, runtime, results and limitations. Regenerate only with the
documented gate prerequisites available; historical receipts are not current proof.

## Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Unit tests only (no API keys needed)
uv run pytest tests/journal_utilities/rag/unit/ -v

# Integration tests (requires COHERE_API_KEY)
uv run pytest tests/journal_utilities/rag/integration/ -v -s
```

## Key Fixtures

From `tests/conftest.py`:

- `fixtures_dir` - Path to test fixtures
- `sample_transcript_file` - Sample transcript for testing
- `images_dir` - Test images directory

From `tests/journal_utilities/conftest.py`:

- `sample_transcript` - Sample transcript text

From `tests/journal_utilities/rag/conftest.py`:

- `sample_concept` - Test Concept model
- `sample_researcher` - Test Researcher model
- `sample_citation` - Test Citation model
- `sample_core_entities` - Full CoreEntities example

## Test Patterns

**Unit tests use mocks where needed:**

```python
from unittest.mock import AsyncMock, patch

@patch("journal_utilities.rag.graph.SurrealDBClient")
async def test_pipeline(mock_client):
    mock_client.return_value.connect = AsyncMock()
    # ...
```

**Integration tests use real APIs:**

```python
async def test_real_extraction():
    extractor = CohereExtractor()  # Uses real API key from .env
    result = extractor.extract_core_entities(transcript)
    # ...
```

SDK doubles must match the installed SDK's actual return shapes. They cannot
qualify database schema or persistence behavior. The disposable-database
acceptance in `journal_utilities/rag/test_source_identity.py` requires explicit
service admission and checks migration, source isolation, failure recovery and
replay against a real server. A skipped database case is not qualification.

## Adding Tests

1. Pipeline tests: `tests/journal_utilities/test_*.py`
2. RAG unit tests: `tests/journal_utilities/rag/unit/test_*.py`
3. RAG integration tests: `tests/journal_utilities/rag/integration/test_*.py`
