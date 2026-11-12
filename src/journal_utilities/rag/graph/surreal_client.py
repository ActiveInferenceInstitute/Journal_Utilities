"""SurrealDB client for storing entities and relationships."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from surrealdb import AsyncSurreal, AsyncSurrealConnection

from journal_utilities.rag.models import Entity, Relationship, Transcript
from journal_utilities.rag.settings import settings

logger = structlog.get_logger(__name__)


def _first_statement(result: Sequence[Any]) -> list[Any]:
    """Rows produced by the first statement of a ``query()`` response.

    surrealdb 3.x answers ``query()`` with one entry per statement, so a
    single-statement query arrives as ``[rows]``. Every caller here issues one
    statement and wants those rows, which is the shape the pre-3.x client
    returned directly.
    """
    if not result:
        return []
    rows = result[0]
    return rows if isinstance(rows, list) else []


class SurrealDBClient:
    """Client for interacting with SurrealDB graph database."""

    def __init__(
        self,
        url: str | None = None,
        namespace: str | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the SurrealDB client.

        Args:
            url: SurrealDB connection URL.
            namespace: Database namespace.
            database: Database name.
            username: Authentication username.
            password: Authentication password.
        """
        self.url = url or settings.surrealdb_url
        self.namespace = namespace or settings.surrealdb_namespace
        self.database = database or settings.surrealdb_database
        self.username = username or settings.surrealdb_username
        self.password = password or settings.surrealdb_password
        self.db: AsyncSurrealConnection | None = None
        logger.info(
            "Initialized SurrealDBClient",
            namespace=self.namespace,
            database=self.database,
        )

    async def connect(self) -> None:
        """Connect to SurrealDB."""
        try:
            self.db = AsyncSurreal(self.url)
            await self.db.connect()
            await self.db.signin({"user": self.username, "pass": self.password})
            await self.db.use(self.namespace, self.database)
            logger.info("Connected to SurrealDB")
            await self._initialize_schema()
        except Exception as e:
            logger.error("Failed to connect to SurrealDB", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Disconnect from SurrealDB."""
        if self.db:
            await self.db.close()
            logger.info("Disconnected from SurrealDB")

    async def _initialize_schema(self) -> None:
        """Initialize database schema."""
        if not self.db:
            raise RuntimeError("Database not connected")

        # Define entity table
        await self.db.query(
            """
            DEFINE TABLE IF NOT EXISTS entity SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS name ON TABLE entity TYPE string;
            DEFINE FIELD IF NOT EXISTS type ON TABLE entity TYPE string;
            DEFINE FIELD IF NOT EXISTS description ON TABLE entity TYPE option<string>;
            DEFINE FIELD IF NOT EXISTS confidence ON TABLE entity TYPE number;
            DEFINE FIELD IF NOT EXISTS mentions ON TABLE entity TYPE number;
            DEFINE FIELD IF NOT EXISTS context ON TABLE entity TYPE array;
            DEFINE FIELD IF NOT EXISTS metadata ON TABLE entity TYPE object;
            DEFINE FIELD IF NOT EXISTS created_at ON TABLE entity TYPE datetime;
            DEFINE INDEX IF NOT EXISTS entity_name_type ON TABLE entity COLUMNS name, type UNIQUE;
            """
        )

        # Define relationship table
        await self.db.query(
            """
            DEFINE TABLE IF NOT EXISTS relates SCHEMAFULL TYPE RELATION;
            DEFINE FIELD IF NOT EXISTS relationship_type ON TABLE relates TYPE string;
            DEFINE FIELD IF NOT EXISTS description ON TABLE relates TYPE option<string>;
            DEFINE FIELD IF NOT EXISTS confidence ON TABLE relates TYPE number;
            DEFINE FIELD IF NOT EXISTS context ON TABLE relates TYPE option<string>;
            DEFINE FIELD IF NOT EXISTS metadata ON TABLE relates TYPE object;
            DEFINE FIELD IF NOT EXISTS created_at ON TABLE relates TYPE datetime;
            """
        )

        # Define transcript table
        await self.db.query(
            """
            DEFINE TABLE IF NOT EXISTS transcript SCHEMAFULL;
            DEFINE FIELD IF NOT EXISTS title ON TABLE transcript TYPE string;
            DEFINE FIELD IF NOT EXISTS date ON TABLE transcript TYPE datetime;
            DEFINE FIELD IF NOT EXISTS content ON TABLE transcript TYPE string;
            DEFINE FIELD IF NOT EXISTS source ON TABLE transcript TYPE option<string>;
            DEFINE FIELD IF NOT EXISTS metadata ON TABLE transcript TYPE object;
            DEFINE FIELD IF NOT EXISTS processed ON TABLE transcript TYPE bool;
            DEFINE FIELD IF NOT EXISTS created_at ON TABLE transcript TYPE datetime;
            """
        )

        logger.info("Initialized database schema")

    async def create_entity(self, entity: Entity) -> str:
        """Create or update an entity in the database.

        Args:
            entity: Entity to create or update.

        Returns:
            Entity ID.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            # Check if entity exists. Generic/truncated names (e.g. "Insight 1")
            # collide across transcripts, so merge is scoped to the entity's
            # source when it is known — otherwise a "Insight 1" from two
            # different videos would silently merge into one record (M10).
            entity_type = entity.type.value if hasattr(entity.type, "value") else entity.type
            source = (entity.metadata or {}).get("source")
            if source:
                existing = _first_statement(
                    await self.db.query(
                        "SELECT * FROM entity WHERE name = $name AND type = $type"
                        " AND source = $source",
                        {"name": entity.name, "type": entity_type, "source": source},
                    )
                )
            else:
                existing = _first_statement(
                    await self.db.query(
                        "SELECT * FROM entity WHERE name = $name AND type = $type",
                        {"name": entity.name, "type": entity_type},
                    )
                )

            if existing:
                # Update existing entity
                current = existing[0]
                entity_id = current["id"]
                await self.db.update(
                    entity_id,
                    {
                        "mentions": entity.mentions,
                        "confidence": max(entity.confidence, current["confidence"]),
                        "context": list(set(entity.context + current["context"])),
                        "description": entity.description or current["description"],
                    },
                )
                logger.debug("Updated entity", entity_id=entity_id)
                return str(entity_id)
            else:
                # Create new entity
                payload: dict[str, Any] = {
                    "name": entity.name,
                    "type": entity_type,
                    "description": entity.description,
                    "confidence": entity.confidence,
                    "mentions": entity.mentions,
                    "context": entity.context,
                    "metadata": entity.metadata,
                    "created_at": datetime.now(UTC).isoformat(),
                }
                if source:
                    payload["source"] = source
                # ``create`` on a table answers with the created records.
                created = cast(list[dict[str, Any]], await self.db.create("entity", payload))
                entity_id = created[0]["id"]
                logger.debug("Created entity", entity_id=entity_id)
                return str(entity_id)

        except Exception as e:
            logger.error("Failed to create entity", entity=entity.name, error=str(e))
            raise

    async def create_relationship(self, relationship: Relationship) -> str:
        """Create a relationship between entities.

        Args:
            relationship: Relationship to create.

        Returns:
            Relationship ID.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            # Get entity IDs (support both old and new field names)
            source_name = (
                relationship.source_entity
                if hasattr(relationship, "source_entity")
                else relationship.source
            )
            target_name = (
                relationship.target_entity
                if hasattr(relationship, "target_entity")
                else relationship.target
            )

            source = _first_statement(
                await self.db.query(
                    "SELECT id FROM entity WHERE name = $name LIMIT 1",
                    {"name": source_name},
                )
            )
            target = _first_statement(
                await self.db.query(
                    "SELECT id FROM entity WHERE name = $name LIMIT 1",
                    {"name": target_name},
                )
            )

            if not source or not target:
                raise ValueError("Source or target entity not found")

            source_id = source[0]["id"]
            target_id = target[0]["id"]

            # Create relationship
            result = _first_statement(
                await self.db.query(
                    f"""
                    RELATE {source_id}->relates->{target_id} CONTENT {{
                        relationship_type: $type,
                        description: $description,
                        confidence: $confidence,
                        context: $context,
                        metadata: $metadata,
                        created_at: $created_at
                    }}
                    """,
                    {
                        "type": relationship.relationship_type,
                        "description": relationship.description,
                        "confidence": relationship.confidence,
                        "context": relationship.context,
                        "metadata": relationship.metadata,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                )
            )

            rel_id = result[0]["id"]
            logger.debug("Created relationship", relationship_id=rel_id)
            return str(rel_id)

        except Exception as e:
            logger.error(
                "Failed to create relationship",
                source=source_name,
                target=target_name,
                error=str(e),
            )
            raise

    async def create_transcript(self, transcript: Transcript) -> str:
        """Store a transcript in the database.

        Args:
            transcript: Transcript to store.

        Returns:
            Transcript ID.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            created = cast(
                list[dict[str, Any]],
                await self.db.create(
                    "transcript",
                    {
                        "title": transcript.title,
                        "date": transcript.date.isoformat(),
                        "content": transcript.content,
                        "source": transcript.source,
                        "metadata": transcript.metadata,
                        "processed": transcript.processed,
                        "created_at": transcript.created_at.isoformat(),
                    },
                ),
            )
            transcript_id = created[0]["id"]
            logger.info("Created transcript", transcript_id=transcript_id)
            return str(transcript_id)

        except Exception as e:
            logger.error("Failed to create transcript", title=transcript.title, error=str(e))
            raise

    async def get_entity_by_name(
        self, name: str, entity_type: str | None = None
    ) -> dict[str, Any] | None:
        """Get an entity by name.

        Args:
            name: Entity name.
            entity_type: Optional entity type filter.

        Returns:
            Entity data or None if not found.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            if entity_type:
                rows = _first_statement(
                    await self.db.query(
                        "SELECT * FROM entity WHERE name = $name AND type = $type LIMIT 1",
                        {"name": name, "type": entity_type},
                    )
                )
            else:
                rows = _first_statement(
                    await self.db.query(
                        "SELECT * FROM entity WHERE name = $name LIMIT 1",
                        {"name": name},
                    )
                )

            if rows:
                return cast(dict[str, Any], rows[0])
            return None

        except Exception as e:
            logger.error("Failed to get entity", name=name, error=str(e))
            raise

    async def query(
        self, query: str, params: Mapping[str, Any] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        """Execute a custom SurrealQL query.

        Args:
            query: SurrealQL query string.
            params: Optional query parameters.

        Returns:
            Query results.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            result = await self.db.query(query, dict(params) if params else None)
            return cast(Sequence[Mapping[str, Any]], _first_statement(result))
        except Exception as e:
            logger.error("Query failed", query=query, error=str(e))
            raise

    async def get_transcript_by_source(self, source_path: str) -> dict[str, Any] | None:
        """Get a transcript by its source path.

        Args:
            source_path: Path to the source transcript file.

        Returns:
            Transcript data or None if not found.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            rows = _first_statement(
                await self.db.query(
                    "SELECT * FROM transcript WHERE source = $source LIMIT 1",
                    {"source": source_path},
                )
            )

            if rows:
                return cast(dict[str, Any], rows[0])
            return None

        except Exception as e:
            logger.error("Failed to get transcript by source", source=source_path, error=str(e))
            raise

    async def get_unprocessed_transcript_paths(self) -> Sequence[str]:
        """Get paths of all unprocessed transcripts.

        Returns:
            List of source paths for unprocessed transcripts.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            rows = _first_statement(
                await self.db.query("SELECT source FROM transcript WHERE processed = false")
            )

            if rows:
                return [rec["source"] for rec in rows if rec.get("source")]
            return []

        except Exception as e:
            logger.error("Failed to get unprocessed transcript paths", error=str(e))
            raise

    async def update_transcript_status(self, transcript_id: str, processed: bool) -> None:
        """Update the processed status of a transcript.

        Args:
            transcript_id: ID of the transcript to update.
            processed: New processed status.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            await self.db.update(transcript_id, {"processed": processed})
            logger.debug(
                "Updated transcript status", transcript_id=transcript_id, processed=processed
            )

        except Exception as e:
            logger.error(
                "Failed to update transcript status",
                transcript_id=transcript_id,
                error=str(e),
            )
            raise

    async def get_or_create_transcript(self, transcript: Transcript) -> str:
        """Get existing transcript by source path or create new one.

        Args:
            transcript: Transcript to get or create.

        Returns:
            Transcript ID.
        """
        if not self.db:
            raise RuntimeError("Database not connected")

        try:
            # Check if transcript exists by source path
            existing = await self.get_transcript_by_source(transcript.source)

            if existing:
                transcript_id = existing["id"]
                logger.debug("Found existing transcript", transcript_id=transcript_id)
                # Update content and metadata if needed
                await self.db.update(
                    transcript_id,
                    {
                        "title": transcript.title,
                        "content": transcript.content,
                        "metadata": transcript.metadata,
                    },
                )
                return str(transcript_id)
            else:
                # Create new transcript
                return await self.create_transcript(transcript)

        except Exception as e:
            logger.error(
                "Failed to get or create transcript",
                source=transcript.source,
                error=str(e),
            )
            raise
