"""Opt-in real SurrealDB schema acceptance. No Cohere requests.

Requires an existing disposable service, explicit JOURNAL_TEST_SURREALDB_ALLOW_DISPOSABLE=1,
JOURNAL_TEST_SURREALDB_URL, JOURNAL_TEST_SURREALDB_NAMESPACE, USERNAME and PASSWORD.
Creates/removes only a fresh UUID-named database in that namespace. A skip is not proof.
"""

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

pytest.importorskip("surrealdb")
pytest.importorskip("structlog")
pytest.importorskip("cohere")

from surrealdb import AsyncSurreal, RecordID

from journal_utilities.rag.graph.surreal_client import SurrealDBClient
from journal_utilities.rag.main import JournalRAGPipeline
from journal_utilities.rag.models import Concept, ConceptCategory, CoreEntities, Relationship, Transcript


@pytest.fixture
async def disposable_database():
    prefix = "JOURNAL_TEST_SURREALDB_"
    required = ("URL", "NAMESPACE", "USERNAME", "PASSWORD")
    if os.environ.get(prefix + "ALLOW_DISPOSABLE") != "1" or not all(os.environ.get(prefix + name) for name in required):
        pytest.skip("Explicit disposable existing SurrealDB service credentials required; no DB proof")
    options = {name.lower(): os.environ[prefix + name] for name in required}
    options["database"] = "journal_group07_test_" + uuid4().hex
    raw = AsyncSurreal(options["url"])
    await raw.connect()
    try:
        await raw.signin({"username": options["username"], "password": options["password"]})
        await raw.use(options["namespace"], options["database"])
        yield options, raw
    finally:
        # Generated identifier contains only this literal prefix and UUID hex.
        await raw.query(f"REMOVE DATABASE IF EXISTS {options['database']};")
        await raw.close()


async def test_legacy_migration_source_identity_retry_and_dates(disposable_database, monkeypatch):
    options, raw = disposable_database
    # Historical schema: global name/type uniqueness, no source field on graph records.
    await raw.query("""
        DEFINE TABLE entity SCHEMAFULL;
        DEFINE FIELD name ON entity TYPE string;
        DEFINE FIELD type ON entity TYPE string;
        DEFINE FIELD description ON entity TYPE option<string>;
        DEFINE FIELD confidence ON entity TYPE number;
        DEFINE FIELD mentions ON entity TYPE number;
        DEFINE FIELD context ON entity TYPE array;
        DEFINE FIELD metadata ON entity TYPE object;
        DEFINE FIELD created_at ON entity TYPE datetime;
        DEFINE INDEX entity_name_type ON entity FIELDS name, type UNIQUE;
        DEFINE TABLE relates SCHEMAFULL TYPE RELATION;
        DEFINE FIELD relationship_type ON relates TYPE string;
        DEFINE FIELD description ON relates TYPE option<string>;
        DEFINE FIELD confidence ON relates TYPE number;
        DEFINE FIELD context ON relates TYPE option<string>;
        DEFINE FIELD metadata ON relates TYPE object;
        DEFINE FIELD created_at ON relates TYPE datetime;
    """)
    payload = {"description": "Legacy", "confidence": 1.0, "mentions": 1, "context": [],
               "metadata": {}, "created_at": datetime(2000, 1, 1, tzinfo=UTC)}
    await raw.create(RecordID("entity", "legacy_insight"), dict(payload, name="Insight 1", type="key_insight"))
    await raw.create(RecordID("entity", "legacy_concept"), dict(payload, name="Shared", type="concept"))
    await raw.relate(RecordID("entity", "legacy_concept"), RecordID("relates", "legacy"),
                     RecordID("entity", "legacy_insight"),
                     {"relationship_type": "related_to", "description": "Legacy", "confidence": 1.0,
                      "context": "", "metadata": {}, "created_at": datetime(2000, 1, 1, tzinfo=UTC)})
    legacy_entities = (await raw.query("SELECT * FROM entity ORDER BY id;"))[0]
    legacy_edges = (await raw.query("SELECT * FROM relates ORDER BY id;"))[0]
    refused = SurrealDBClient(**options)
    with pytest.raises(RuntimeError, match="--migrate-source-identity"):
        await refused.connect()
    client = SurrealDBClient(**options)
    await client.connect(migrate_source_identity=True)
    try:
        assert client.migration_summary["unknown_source_entities"] == 2
        assert client.migration_summary["unknown_source_relationships"] == 1
        assert (await raw.query("SELECT * FROM entity ORDER BY id;"))[0] == legacy_entities
        assert (await raw.query("SELECT * FROM relates ORDER BY id;"))[0] == legacy_edges
        info = (await raw.query("INFO FOR TABLE entity;"))[0]
        assert "entity_name_type" not in info["indexes"]
        assert "entity_source_type_name" in info["indexes"]
        core = CoreEntities(concepts=[
            Concept(name="Shared", definition="A", category=ConceptCategory.THEORETICAL, related_concepts=["Target"]),
            Concept(name="Target", definition="B", category=ConceptCategory.THEORETICAL, related_concepts=["Shared"]),
        ], researchers=[], citations=[], technical_terms=[], key_insights=["An insight"])
        pipeline = JournalRAGPipeline()
        pipeline.db_client = client
        pipeline.extractor = MagicMock()
        pipeline.extractor.extract_core_entities.return_value = core
        a = Transcript(title="A", date=datetime.min, source="a.txt", content="A")
        b = Transcript(title="B", date=datetime(2025, 10, 30), source="b.txt", content="B")
        await pipeline.process_transcript(a)
        relate = client.db.relate
        calls = 0

        def fail_second_edge(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Injected external edge write failure")
            return relate(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(client.db, "relate", fail_second_edge)
            with pytest.raises(RuntimeError, match="edge write failure"):
                await pipeline.process_transcript(b)
        pending = await client.get_transcript_by_source("b.txt")
        assert pending["processed"] is False and pending["content"] == "B"
        assert pending["source"] == "b.txt"
        original_date = pending["date"]
        await pipeline.process_transcript(b.model_copy(update={"date": datetime.min}))
        assert (await client.get_transcript_by_source("b.txt"))["date"] == original_date
        before_replay = await client.query("SELECT * FROM entity;")
        edge_ids = {str(row["id"]) for row in await client.query("SELECT * FROM relates;")}
        await pipeline.process_transcript(a)
        await pipeline.process_transcript(b)
        entities = await client.query("SELECT * FROM entity;")
        edges = await client.query("SELECT * FROM relates;")
        assert {str(row["id"]) for row in entities} == {str(row["id"]) for row in before_replay}
        assert {str(row["id"]) for row in edges} == edge_ids
        assert len(entities) == 8 and len(edges) == 5
        by_id = {str(row["id"]): row for row in entities}
        for edge in edges:
            if edge.get("source"):
                assert by_id[str(edge["in"])]["source"] == edge["source"] == by_id[str(edge["out"])]["source"]
        assert sorted((row for row in entities if not row.get("source")), key=lambda row: str(row["id"])) == legacy_entities
        assert [row for row in edges if not row.get("source")] == legacy_edges
        assert {row["source"] for row in entities if row["name"] == "Insight 1" and row.get("source")} == {"a.txt", "b.txt"}
        assert (await client.get_transcript_by_source("a.txt"))["processed"] is True
        assert (await client.get_transcript_by_source("b.txt"))["processed"] is True
        a_entity = await client.get_entity_by_name("Shared", entity_type="concept", source="a.txt")
        b_entity = await client.get_entity_by_name("Target", entity_type="concept", source="b.txt")
        edge = Relationship(transcript_source="a.txt", source="Shared", source_type="concept",
                            target="Target", target_type="concept", relationship_type="related_to")
        with pytest.raises(ValueError, match="trusted source/type/name"):
            await client.create_relationship(edge, source_id=str(a_entity["id"]), target_id=str(b_entity["id"]))
        # Explicit migration must refuse contradictory claims without changing data.
        await raw.query("UPDATE $id MERGE { metadata: { source: 'contradictory.txt' } };", {"id": a_entity["id"]})
        snapshot = await client.query("SELECT * FROM entity ORDER BY id;")
        ambiguous = SurrealDBClient(**options)
        with pytest.raises(RuntimeError, match="Conflicting legacy source claims"):
            await ambiguous.connect(migrate_source_identity=True)
        assert await client.query("SELECT * FROM entity ORDER BY id;") == snapshot
    finally:
        await client.disconnect()
