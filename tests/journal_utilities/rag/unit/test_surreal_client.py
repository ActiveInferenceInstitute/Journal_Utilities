"""Storage admission/error contracts at the SDK boundary; not real-schema proof."""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("surrealdb")
pytest.importorskip("structlog")

from journal_utilities.rag.graph.surreal_client import SurrealDBClient
from journal_utilities.rag.models import Entity, Relationship, Transcript


@pytest.fixture
def connected():
    client = SurrealDBClient()
    client.db = AsyncMock()
    client.db.query.return_value = [[]]
    return client, client.db


async def test_ambiguous_entity_does_not_select_first_or_write(connected):
    client, db = connected
    db.query.return_value = [[{"id": "entity:a"}, {"id": "entity:b"}]]
    with pytest.raises(RuntimeError, match="Ambiguous"):
        await client.create_entity(Entity(source="a.txt", type="concept", name="Shared"))
    db.create.assert_not_awaited()


async def test_cross_source_or_wrong_type_endpoints_are_refused(connected):
    client, db = connected
    db.query.return_value = [
        [{"id": "entity:wrong", "source": "other.txt", "type": "concept", "name": "Shared"}]
    ]
    edge = Relationship(
        transcript_source="a.txt",
        source="Shared",
        target="Target",
        source_type="concept",
        target_type="concept",
        relationship_type="related_to",
    )
    with pytest.raises(ValueError, match="trusted source/type/name"):
        await client.create_relationship(edge, source_id="entity:wrong", target_id="entity:target")
    db.relate.assert_not_awaited()


async def test_transcript_update_does_not_replace_date_or_identity(connected):
    client, db = connected
    db.query.side_effect = [
        [[{"id": "transcript:old", "source": "a.txt", "date": datetime(2000, 1, 1)}]],
        [[{"id": "transcript:old"}]],
    ]
    transcript = Transcript(title="Updated", date=datetime.min, source="a.txt", content="New text")
    assert await client.get_or_create_transcript(transcript) == "transcript:old"
    changes = db.query.await_args.args[1]["changes"]
    assert changes == {
        "title": "Updated",
        "content": "New text",
        "metadata": {},
        "processed": False,
    }
    db.create.assert_not_awaited()


async def test_disappeared_status_target_is_not_reported_complete(connected):
    client, _ = connected
    with pytest.raises(RuntimeError, match="disappeared"):
        await client.update_transcript_status("transcript:gone", processed=True)


async def test_pending_without_source_is_not_silently_skipped(connected):
    client, db = connected
    db.query.return_value = [[{"source": None}]]
    with pytest.raises(RuntimeError, match="no trusted source"):
        await client.get_unprocessed_transcript_paths()


async def test_legacy_schema_requires_explicit_admission(monkeypatch):
    db = AsyncMock()
    db.query.side_effect = [
        [{"tables": {"entity": "SCHEMAFULL"}}],
        [{"indexes": {"entity_name_type": "name,type UNIQUE"}}],
    ]
    monkeypatch.setattr("journal_utilities.rag.graph.surreal_client.AsyncSurreal", lambda _: db)
    client = SurrealDBClient()
    with pytest.raises(RuntimeError, match="--migrate-source-identity"):
        await client.connect()
    db.close.assert_awaited_once()
    assert client.db is None


@pytest.mark.parametrize(
    "entities,edges",
    [
        (
            [
                {
                    "id": "entity:a",
                    "name": "Shared",
                    "type": "concept",
                    "source": "a.txt",
                    "metadata": {"source": "b.txt"},
                }
            ],
            [],
        ),
        (
            [
                {"id": "entity:a", "name": "Shared", "type": "concept", "source": "a.txt"},
                {"id": "entity:b", "name": "Shared", "type": "concept", "source": "a.txt"},
            ],
            [],
        ),
        (
            [{"id": "entity:a", "name": "Shared", "type": "concept", "source": "a.txt"}],
            [
                {
                    "id": "relates:x",
                    "source": "b.txt",
                    "in": "entity:a",
                    "out": "entity:a",
                    "relationship_type": "related_to",
                }
            ],
        ),
    ],
)
async def test_explicit_migration_refuses_ambiguous_attribution(monkeypatch, entities, edges):
    db = AsyncMock()
    db.query.side_effect = [
        [{"tables": {"entity": "SCHEMAFULL", "relates": "RELATION"}}],
        [{"indexes": {"entity_name_type": "name,type UNIQUE"}}],
        [entities],
        [edges],
    ]
    monkeypatch.setattr("journal_utilities.rag.graph.surreal_client.AsyncSurreal", lambda _: db)
    client = SurrealDBClient()
    with pytest.raises(RuntimeError, match="[Aa]mbiguous|Conflicting"):
        await client.connect(migrate_source_identity=True)
    # No schema/data write was reached after the four evidence reads.
    assert db.query.await_count == 4
    db.close.assert_awaited_once()


async def test_metadata_only_source_stays_unknown(connected):
    client, db = connected
    db.query.return_value = [
        [
            {
                "id": "entity:old",
                "name": "Insight 1",
                "type": "key_insight",
                "metadata": {"source": "untrusted-claim.txt"},
            }
        ]
    ]
    summary = await client._admit_migration({"entity": "SCHEMAFULL"})
    assert summary["legacy_entities_preserved"] == summary["unknown_source_entities"] == 1
    db.create.assert_not_awaited()
