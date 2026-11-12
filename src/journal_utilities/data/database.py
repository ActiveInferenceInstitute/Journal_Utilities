"""
Database connection and audit trail functionality for Journal Utilities.

This module provides:
- DatabaseClient class for SurrealDB connection management
- Audit trail functions for import tracking
"""

import datetime
import logging
import os
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from surrealdb import AsyncSurreal, AsyncSurrealConnection


def _redact_url(url: str) -> str:
    """Strip userinfo (credentials) from a URL for safe logging."""
    parts = urlsplit(url)
    if parts.username or parts.password:
        netloc = (parts.hostname or "") + (f":{parts.port}" if parts.port else "")
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts)


@dataclass
class DatabaseConfig:
    """Database configuration."""

    url: str = field(default_factory=lambda: os.getenv("DB_URL", "ws://localhost:8080/rpc"))
    user: str = field(default_factory=lambda: os.getenv("DB_USER", "root"))
    password: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", "root"))
    name: str = field(default_factory=lambda: os.getenv("DB_NAME", "actinf"))
    namespace: str = field(default_factory=lambda: os.getenv("DB_NAMESPACE", "actinf"))

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Create config from environment variables."""
        return cls()


class DatabaseClient:
    """Async SurrealDB client wrapper with connection management."""

    def __init__(self, config: DatabaseConfig | None = None) -> None:
        """
        Initialize database client.

        Args:
            config: Database configuration. Uses environment variables if not provided.
        """
        self.config = config or DatabaseConfig.from_env()
        self._db: AsyncSurrealConnection | None = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to the database."""
        if self._connected:
            return

        self._db = AsyncSurreal(self.config.url)
        await self._db.connect()
        await self._db.signin({"username": self.config.user, "password": self.config.password})
        await self._db.use(self.config.namespace, self.config.name)
        self._connected = True
        # Never log the raw URL: it can embed userinfo credentials (ws://u:p@host).
        logging.info("Connected to database at %s", _redact_url(self.config.url))

    async def disconnect(self) -> None:
        """Disconnect from the database."""
        if self._db and self._connected:
            await self._db.close()
            self._connected = False
            logging.info("Disconnected from database")

    async def query(self, sql: str, params: dict | None = None) -> list:
        """Execute a query and return the rows of its first statement.

        surrealdb 3.x answers ``query()`` with one entry per statement; every
        caller here issues a single statement, so the rows are unpacked here
        rather than at each call site.
        """
        if not self._connected:
            await self.connect()
        assert self._db is not None  # connect() guarantees this
        result = await self._db.query(sql, params or {})
        rows: list = cast(list, result[0]) if result else []
        return rows

    async def create(self, table: str, data: dict) -> Any:  # noqa: ANN401
        """Create a record in the specified table."""
        if not self._connected:
            await self.connect()
        assert self._db is not None  # connect() guarantees this
        return await self._db.create(table, data)

    async def __aenter__(self) -> "DatabaseClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.disconnect()


# ============================================================================
# Audit Trail Functions
# ============================================================================


async def get_recent_import_runs(
    db_url: str, db_user: str, db_password: str, db_name: str, db_namespace: str, limit: int = 10
) -> list[dict]:
    """
    Get list of recent import runs.

    Args:
        db_url: Database URL
        db_user: Database username
        db_password: Database password
        db_name: Database name
        db_namespace: Database namespace
        limit: Number of recent runs to return

    Returns:
        List of recent import run IDs with their summaries
    """
    config = DatabaseConfig(
        url=db_url, user=db_user, password=db_password, name=db_name, namespace=db_namespace
    )

    async with DatabaseClient(config) as db:
        result = await db.query(
            """
            SELECT import_run_id, timestamp, source_file, result_data
            FROM import_audit
            WHERE operation = 'import_summary'
            ORDER BY timestamp DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )

        import_runs = []
        if result and len(result) > 0:
            for record in result:
                import_runs.append(
                    {
                        "import_run_id": record.get("import_run_id"),
                        "timestamp": record.get("timestamp"),
                        "source_file": record.get("source_file"),
                        "stats": record.get("result_data", {}),
                    }
                )

        return import_runs


async def get_import_summary(
    import_run_id: str, db_url: str, db_user: str, db_password: str, db_name: str, db_namespace: str
) -> dict:
    """
    Get summary statistics for an import run.

    Args:
        import_run_id: The import run ID to get summary for
        db_url: Database URL
        db_user: Database username
        db_password: Database password
        db_name: Database name
        db_namespace: Database namespace

    Returns:
        Summary dictionary with total, inserted, skipped, failed counts
    """
    config = DatabaseConfig(
        url=db_url, user=db_user, password=db_password, name=db_name, namespace=db_namespace
    )

    async with DatabaseClient(config) as db:
        # Get the import summary record
        result = await db.query(
            """
            SELECT * FROM import_audit
            WHERE import_run_id = $id
            AND operation = 'import_summary'
            """,
            {"id": import_run_id},
        )

        if result and len(result) > 0:
            return cast(dict[Any, Any], result[0].get("result_data", {}))

        # If no summary record, calculate from individual records
        all_records = await db.query(
            """
            SELECT operation, status FROM import_audit
            WHERE import_run_id = $id
            """,
            {"id": import_run_id},
        )

        stats = {"total": 0, "inserted": 0, "skipped": 0, "failed": 0}
        for record in all_records:
            if record["operation"] in ["insert", "skip", "parse_youtube_id"]:
                stats["total"] += 1
                if record["status"] == "success":
                    stats["inserted"] += 1
                elif record["status"] == "skipped":
                    stats["skipped"] += 1
                elif record["status"] == "failed":
                    stats["failed"] += 1

        return stats


async def get_failed_imports(
    import_run_id: str, db_url: str, db_user: str, db_password: str, db_name: str, db_namespace: str
) -> list[dict]:
    """
    Get all failed operations from an import run.

    Args:
        import_run_id: The import run ID to check
        db_url: Database URL
        db_user: Database username
        db_password: Database password
        db_name: Database name
        db_namespace: Database namespace

    Returns:
        List of failed operations with details
    """
    config = DatabaseConfig(
        url=db_url, user=db_user, password=db_password, name=db_name, namespace=db_namespace
    )

    async with DatabaseClient(config) as db:
        result = await db.query(
            """
            SELECT * FROM import_audit
            WHERE import_run_id = $id
            AND status = 'failed'
            """,
            {"id": import_run_id},
        )

        failed_imports = []
        if result and len(result) > 0:
            for record in result:
                failed_imports.append(
                    {
                        "session_name": record.get("session_name", "unknown"),
                        "operation": record.get("operation"),
                        "error": record.get("error_message"),
                        "timestamp": record.get("timestamp"),
                        "data_attempted": record.get("data_attempted", {}),
                    }
                )

        return failed_imports


async def rollback_import(
    import_run_id: str, db_url: str, db_user: str, db_password: str, db_name: str, db_namespace: str
) -> dict:
    """
    Rollback all sessions created during a specific import run.

    Args:
        import_run_id: The import run ID to rollback
        db_url: Database URL
        db_user: Database username
        db_password: Database password
        db_name: Database name
        db_namespace: Database namespace

    Returns:
        Summary of rollback operations
    """
    config = DatabaseConfig(
        url=db_url, user=db_user, password=db_password, name=db_name, namespace=db_namespace
    )

    async with DatabaseClient(config) as db:
        # Get all successful inserts from this import run
        result = await db.query(
            """
            SELECT * FROM import_audit
            WHERE import_run_id = $id
            AND operation = 'insert'
            AND status = 'success'
            """,
            {"id": import_run_id},
        )

        rollback_count = 0
        errors = []

        if result and len(result) > 0:
            for audit_record in result:
                session_name = audit_record.get("session_name")
                # Delete the EXACT session record created during this run (its
                # id is captured in the audit's result_data), never re-match by
                # session_name — that would also delete legitimate records from
                # an earlier run that shares the same YouTube id.
                result_data = audit_record.get("result_data")
                session_id = result_data.get("id") if isinstance(result_data, dict) else None
                if not session_id:
                    errors.append(
                        {
                            "session_name": session_name,
                            "error": "no created session id in audit result_data",
                        }
                    )
                    continue
                try:
                    await db.query("DELETE $id", {"id": session_id})

                    # Mark the audit record as rolled back
                    await db.query(
                        """
                        UPDATE $rid MERGE {
                            status: 'rolled_back',
                            rollback_timestamp: $ts
                        };
                        """,
                        {"rid": audit_record["id"], "ts": datetime.datetime.now().isoformat()},
                    )

                    rollback_count += 1
                    logging.info("Rolled back session record %s", session_id)
                except Exception as e:
                    errors.append({"session_name": session_name, "error": str(e)})
                    logging.error("Failed to rollback session %s: %s", session_id, e)

        # Create rollback summary audit record
        summary = {"rollback_count": rollback_count, "errors": errors}

        await db.create(
            "import_audit",
            {
                "import_run_id": import_run_id,
                "timestamp": datetime.datetime.now().isoformat(),
                "operation": "rollback_summary",
                "status": "completed",
                "result_data": summary,
            },
        )

        logging.info(f"Rollback Summary for {import_run_id}: {rollback_count} sessions rolled back")

        return summary
