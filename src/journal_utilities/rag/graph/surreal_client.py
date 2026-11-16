"""Source-qualified SurrealDB storage; legacy attribution is never inferred."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from surrealdb import AsyncSurreal, AsyncSurrealConnection, RecordID, StringRecordId

from journal_utilities.rag.models import Entity, Relationship, Transcript
from journal_utilities.rag.settings import settings


def _first_statement(result: object) -> object:
    """The installed SDK 3.x returns one entry per statement."""
    if not isinstance(result, list) or len(result) != 1:
        raise RuntimeError("Unexpected SurrealDB statement result")
    return result[0]


def _single(rows: Sequence[Mapping[str, Any]], identity: str) -> Mapping[str, Any] | None:
    if len(rows) > 1:
        raise RuntimeError(f"Ambiguous {identity}; explicit data review required")
    return rows[0] if rows else None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_SCHEMA = """
DEFINE TABLE IF NOT EXISTS entity SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON entity TYPE string;
DEFINE FIELD IF NOT EXISTS type ON entity TYPE string;
DEFINE FIELD IF NOT EXISTS source ON entity TYPE option<string>;
DEFINE FIELD IF NOT EXISTS description ON entity TYPE option<string>;
DEFINE FIELD IF NOT EXISTS confidence ON entity TYPE number;
DEFINE FIELD IF NOT EXISTS mentions ON entity TYPE number;
DEFINE FIELD IF NOT EXISTS context ON entity TYPE array<string>;
DEFINE FIELD OVERWRITE metadata ON entity TYPE object FLEXIBLE;
DEFINE FIELD IF NOT EXISTS created_at ON entity TYPE datetime;
DEFINE INDEX IF NOT EXISTS entity_source_type_name ON entity FIELDS source, type, name UNIQUE;
DEFINE TABLE IF NOT EXISTS relates SCHEMAFULL TYPE RELATION;
DEFINE FIELD IF NOT EXISTS source ON relates TYPE option<string>;
DEFINE FIELD IF NOT EXISTS relationship_type ON relates TYPE string;
DEFINE FIELD IF NOT EXISTS description ON relates TYPE option<string>;
DEFINE FIELD IF NOT EXISTS confidence ON relates TYPE number;
DEFINE FIELD IF NOT EXISTS context ON relates TYPE option<string>;
DEFINE FIELD OVERWRITE metadata ON relates TYPE object FLEXIBLE;
DEFINE FIELD IF NOT EXISTS created_at ON relates TYPE datetime;
DEFINE INDEX IF NOT EXISTS relates_source_endpoints ON relates FIELDS source, in, out, relationship_type;
DEFINE TABLE IF NOT EXISTS transcript SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS title ON transcript TYPE string;
DEFINE FIELD IF NOT EXISTS date ON transcript TYPE datetime;
DEFINE FIELD IF NOT EXISTS content ON transcript TYPE string;
DEFINE FIELD IF NOT EXISTS source ON transcript TYPE option<string>;
DEFINE FIELD OVERWRITE metadata ON transcript TYPE object FLEXIBLE;
DEFINE FIELD IF NOT EXISTS processed ON transcript TYPE bool;
DEFINE FIELD IF NOT EXISTS created_at ON transcript TYPE datetime;
"""


class SurrealDBClient:
    """Persist identities using trusted transcript source, entity type and name."""

    def __init__(
        self,
        url: str | None = None,
        namespace: str | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.url = url or settings.surrealdb_url
        self.namespace = namespace or settings.surrealdb_namespace
        self.database = database or settings.surrealdb_database
        self.username = username or settings.surrealdb_username
        self.password = password or settings.surrealdb_password
        self.db: AsyncSurrealConnection | None = None
        self.migration_summary: dict[str, int] | None = None

    async def connect(self, *, migrate_source_identity: bool = False) -> None:
        """Refuse legacy schema unless migration was explicitly selected.

        Migration requires a quiescent database. It changes schema, not legacy
        data: absent provenance stays absent and ambiguous attribution fails.
        """
        self.db = AsyncSurreal(self.url)
        try:
            await self.db.connect()
            await self.db.signin({"username": self.username, "password": self.password})
            await self.db.use(self.namespace, self.database)
            await self._initialize_schema(migrate_source_identity=migrate_source_identity)
        except Exception:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        if self.db is not None:
            db, self.db = self.db, None
            await db.close()

    async def _initialize_schema(self, *, migrate_source_identity: bool = False) -> None:
        if self.db is None:
            raise RuntimeError("Database not connected")
        info = cast(Mapping[str, Any], _first_statement(await self.db.query("INFO FOR DB;")))
        tables = info["tables"]
        indexes = {}
        if "entity" in tables:
            entity_info = cast(
                Mapping[str, Any], _first_statement(await self.db.query("INFO FOR TABLE entity;"))
            )
            indexes = entity_info["indexes"]
        legacy = ("entity" in tables or "relates" in tables) and (
            "entity_source_type_name" not in indexes or "entity_name_type" in indexes
        )
        if legacy and not migrate_source_identity:
            raise RuntimeError(
                "Legacy graph schema: review a backup, stop other writers, then explicitly "
                "run --migrate-source-identity. No legacy provenance will be assigned."
            )
        if migrate_source_identity:
            self.migration_summary = await self._admit_migration(tables)
        remove_old = (
            "REMOVE INDEX entity_name_type ON entity;" if "entity_name_type" in indexes else ""
        )
        # A failed index definition must not leave a partially migrated schema.
        await self.db.query("BEGIN TRANSACTION;" + _SCHEMA + remove_old + "COMMIT TRANSACTION;")

    async def _admit_migration(self, tables: Mapping[str, Any]) -> dict[str, int]:
        entities = list(await self.query("SELECT * FROM entity;")) if "entity" in tables else []
        edges = list(await self.query("SELECT * FROM relates;")) if "relates" in tables else []
        transcripts = (
            list(await self.query("SELECT * FROM transcript;")) if "transcript" in tables else []
        )
        by_id = {str(row["id"]): row for row in entities}
        identities: set[tuple[str | None, str, str]] = set()
        unknown = 0
        for row in entities:
            source = self._legacy_source(row)
            unknown += source is None
            identity = (source, row["type"], row["name"])
            if identity in identities:
                raise RuntimeError("Ambiguous legacy entity identity; migration refused")
            identities.add(identity)
        edge_keys: set[tuple[str, str, str, str]] = set()
        unknown_edges = 0
        for row in edges:
            source = self._legacy_source(row)
            if source is None:
                unknown_edges += 1
                continue
            for endpoint in ("in", "out"):
                entity = by_id.get(str(row[endpoint]))
                if entity is None or self._legacy_source(entity) != source:
                    raise RuntimeError(
                        "Ambiguous legacy relationship attribution; migration refused"
                    )
            key = (source, str(row["in"]), str(row["out"]), row["relationship_type"])
            if key in edge_keys:
                raise RuntimeError("Ambiguous legacy relationship identity; migration refused")
            edge_keys.add(key)
        sources: set[str] = set()
        for row in transcripts:
            source = self._legacy_source(row)
            if source is not None:
                if source in sources:
                    raise RuntimeError("Ambiguous legacy transcript source; migration refused")
                sources.add(source)
        return {
            "legacy_entities_preserved": len(entities),
            "unknown_source_entities": unknown,
            "legacy_relationships_preserved": len(edges),
            "unknown_source_relationships": unknown_edges,
        }

    @staticmethod
    def _legacy_source(row: Mapping[str, Any]) -> str | None:
        source = row.get("source")
        if source is None or source == "":
            # A metadata claim alone is not trusted provenance. Keep it untouched.
            return None
        if not isinstance(source, str) or not source.strip():
            raise RuntimeError("Ambiguous legacy source value; migration refused")
        claim = (row.get("metadata") or {}).get("source")
        if claim is not None and claim != source:
            raise RuntimeError("Conflicting legacy source claims; migration refused")
        return source

    async def query(
        self, query: str, params: Mapping[str, Any] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        if self.db is None:
            raise RuntimeError("Database not connected")
        rows = _first_statement(await self.db.query(query, dict(params) if params else None))
        if not isinstance(rows, list):
            raise RuntimeError("Expected SurrealDB records")
        return cast(Sequence[Mapping[str, Any]], rows)

    async def _record(self, record_id: str) -> Mapping[str, Any] | None:
        return _single(
            await self.query("SELECT * FROM $id;", {"id": StringRecordId(record_id)}), record_id
        )

    async def _merge(self, record_id: str, changes: Mapping[str, Any]) -> None:
        rows = await self.query(
            "UPDATE $id MERGE $changes;",
            {"id": StringRecordId(record_id), "changes": dict(changes)},
        )
        if _single(rows, record_id) is None:
            raise RuntimeError(f"Record disappeared during update: {record_id}")

    async def get_entity_by_name(
        self, name: str, *, entity_type: str, source: str
    ) -> Mapping[str, Any] | None:
        if not source.strip():
            raise ValueError("A trusted transcript source is required")
        return _single(
            await self.query(
                "SELECT * FROM entity WHERE source = $source AND type = $type AND name = $name;",
                {"source": source, "type": entity_type, "name": name},
            ),
            "source-qualified entity",
        )

    async def create_entity(self, entity: Entity) -> str:
        if self.db is None:
            raise RuntimeError("Database not connected")
        existing = await self.get_entity_by_name(
            entity.name, entity_type=entity.type, source=entity.source
        )
        payload: dict[str, Any] = entity.model_dump()
        if existing:
            # MERGE, not replacement: preserve identity and original creation time.
            payload["confidence"] = max(entity.confidence, existing["confidence"])
            payload["context"] = list(dict.fromkeys([*existing["context"], *entity.context]))
            payload["description"] = entity.description or existing.get("description", "")
            entity_id = str(existing["id"])
            await self._merge(entity_id, payload)
            return entity_id
        payload["created_at"] = datetime.now(UTC)
        row = await self.db.create("entity", payload)
        if not isinstance(row, Mapping) or "id" not in row:
            raise RuntimeError("Entity creation returned no record")
        return str(row["id"])

    async def create_relationship(
        self, relationship: Relationship, *, source_id: str, target_id: str
    ) -> str:
        if self.db is None:
            raise RuntimeError("Database not connected")
        for record_id, name, entity_type in (
            (source_id, relationship.source, relationship.source_type),
            (target_id, relationship.target, relationship.target_type),
        ):
            endpoint = await self._record(record_id)
            if endpoint is None or (
                endpoint.get("source"),
                endpoint.get("type"),
                endpoint.get("name"),
            ) != (relationship.transcript_source, entity_type, name):
                raise ValueError("Relationship endpoint does not match trusted source/type/name")
        params = {
            "source": relationship.transcript_source,
            "in": StringRecordId(source_id),
            "out": StringRecordId(target_id),
            "type": relationship.relationship_type,
        }
        existing = _single(
            await self.query(
                "SELECT * FROM relates WHERE source = $source AND in = $in AND out = $out "
                "AND relationship_type = $type;",
                params,
            ),
            "source-qualified relationship",
        )
        payload: dict[str, Any] = {
            "source": relationship.transcript_source,
            "relationship_type": relationship.relationship_type,
            "description": relationship.description,
            "confidence": relationship.confidence,
            "context": relationship.context,
            "metadata": relationship.metadata,
        }
        if existing:
            edge_id = str(existing["id"])
            await self._merge(edge_id, payload)
            return edge_id
        # Deterministic record identity also prevents duplicate edges on concurrent retries.
        key = json.dumps(
            [relationship.transcript_source, source_id, target_id, relationship.relationship_type],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        edge = RecordID("relates", hashlib.sha256(key.encode("utf-8")).hexdigest())
        if await self._record(str(edge)) is not None:
            raise RuntimeError("Relationship identity collision; refusing to overwrite")
        payload["created_at"] = datetime.now(UTC)
        row = await self.db.relate(
            StringRecordId(source_id), edge, StringRecordId(target_id), payload
        )
        if not isinstance(row, Mapping) or "id" not in row:
            raise RuntimeError("Relationship creation returned no record")
        return str(row["id"])

    async def create_transcript(self, transcript: Transcript) -> str:
        if self.db is None:
            raise RuntimeError("Database not connected")
        payload = transcript.model_dump()
        payload.update(
            date=_utc(transcript.date), created_at=_utc(transcript.created_at), processed=False
        )
        row = await self.db.create("transcript", payload)
        if not isinstance(row, Mapping) or "id" not in row:
            raise RuntimeError("Transcript creation returned no record")
        return str(row["id"])

    async def get_transcript_by_source(self, source_path: str) -> Mapping[str, Any] | None:
        return _single(
            await self.query(
                "SELECT * FROM transcript WHERE source = $source;", {"source": source_path}
            ),
            "transcript source",
        )

    async def get_unprocessed_transcript_paths(self) -> Sequence[str]:
        rows = await self.query("SELECT source FROM transcript WHERE processed = false;")
        paths = []
        for row in rows:
            source = row.get("source")
            if not isinstance(source, str) or not source.strip():
                raise RuntimeError(
                    "Pending transcript has no trusted source path; explicit review required"
                )
            paths.append(source)
        return paths

    async def update_transcript_status(self, transcript_id: str, processed: bool) -> None:
        await self._merge(transcript_id, {"processed": processed})

    async def get_or_create_transcript(self, transcript: Transcript) -> str:
        existing = await self.get_transcript_by_source(transcript.source)
        if existing:
            transcript_id = str(existing["id"])
            # Do not rewrite historical date/source/created_at on a retry.
            await self._merge(
                transcript_id,
                {
                    "title": transcript.title,
                    "content": transcript.content,
                    "metadata": transcript.metadata,
                    "processed": False,
                },
            )
            return transcript_id
        return await self.create_transcript(transcript)
