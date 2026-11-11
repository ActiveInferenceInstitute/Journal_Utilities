# tests/journal_utilities/rag/unit

Unit tests for the RAG entity-extraction pipeline
([`journal_utilities/rag/`](../../../../src/journal_utilities/rag/)). No API keys
or live services — external clients are mocked.

| File | Covers |
| --- | --- |
| `test_cohere_extractor.py` | Cohere extraction orchestration (mocked client). |
| `test_entity_adapter.py` | Extracted-entity → graph-record conversion and source stamping. |
| `test_models.py` | Pydantic entity/relationship models. |
| `test_pipeline.py` | `rag/main.py` orchestration. |
| `test_surreal_client.py` | SurrealDB graph client (mocked). |

```bash
uv run pytest tests/journal_utilities/rag/unit/ -q
```

Integration counterparts that need `COHERE_API_KEY` live under
`tests/journal_utilities/rag/integration/`. Part of the suite described in
[`../../../README.md`](../../../README.md).
