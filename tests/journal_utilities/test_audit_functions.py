"""
Test suite for audit trail functions in journal_utilities.data.database.

Tests get_recent_import_runs, get_import_summary, get_failed_imports,
and rollback_import against mocked SurrealDB connections.
"""

from unittest.mock import AsyncMock, patch

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("surrealdb")

from journal_utilities.data.database import (
    get_failed_imports,
    get_import_summary,
    get_recent_import_runs,
    rollback_import,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DB_PATCH_TARGET = "journal_utilities.data.database.AsyncSurreal"


def _make_mock_surreal(query_return_value=None):
    """Create a mocked AsyncSurreal with sensible defaults."""
    mock = AsyncMock()
    mock.connect = AsyncMock()
    mock.signin = AsyncMock()
    mock.use = AsyncMock()
    mock.close = AsyncMock()
    mock.create = AsyncMock(return_value={"id": "audit:1"})
    mock.query = AsyncMock(return_value=query_return_value if query_return_value is not None else [])
    return mock


# ---------------------------------------------------------------------------
# Tests — get_recent_import_runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recent_import_runs(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """get_recent_import_runs returns formatted list of runs."""
    mock_runs = [
        {
            "import_run_id": "run_123",
            "timestamp": "2023-01-01T12:00:00Z",
            "source_file": "test.json",
            "result_data": {"total": 10, "inserted": 5, "skipped": 3, "failed": 2},
        }
    ]

    mock = _make_mock_surreal(query_return_value=mock_runs)
    with patch(DB_PATCH_TARGET, return_value=mock):
        runs = await get_recent_import_runs(
            db_url, db_user, db_password, db_name, db_namespace, limit=5
        )

    assert isinstance(runs, list)
    assert len(runs) == 1
    first = runs[0]
    assert first["import_run_id"] == "run_123"
    assert first["source_file"] == "test.json"
    assert first["stats"]["total"] == 10


@pytest.mark.asyncio
async def test_get_recent_import_runs_empty(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """get_recent_import_runs returns empty list when no runs exist."""
    mock = _make_mock_surreal(query_return_value=[])
    with patch(DB_PATCH_TARGET, return_value=mock):
        runs = await get_recent_import_runs(
            db_url, db_user, db_password, db_name, db_namespace
        )

    assert runs == []


# ---------------------------------------------------------------------------
# Tests — get_import_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_import_summary_from_record(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """get_import_summary returns stats from a summary record."""
    mock_result = [
        {"result_data": {"total": 10, "inserted": 5, "skipped": 3, "failed": 2}}
    ]

    mock = _make_mock_surreal(query_return_value=mock_result)
    with patch(DB_PATCH_TARGET, return_value=mock):
        summary = await get_import_summary(
            "run_123", db_url, db_user, db_password, db_name, db_namespace
        )

    assert summary["total"] == 10
    assert summary["inserted"] == 5


@pytest.mark.asyncio
async def test_get_import_summary_calculates(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """get_import_summary calculates stats when no summary record exists."""
    individual_records = [
        {"operation": "insert", "status": "success"},
        {"operation": "insert", "status": "success"},
        {"operation": "skip", "status": "skipped"},
        {"operation": "insert", "status": "failed"},
    ]

    mock = _make_mock_surreal()
    mock.query = AsyncMock(side_effect=[[], individual_records])
    with patch(DB_PATCH_TARGET, return_value=mock):
        summary = await get_import_summary(
            "run_123", db_url, db_user, db_password, db_name, db_namespace
        )

    assert summary["total"] == 4
    assert summary["inserted"] == 2
    assert summary["skipped"] == 1
    assert summary["failed"] == 1


# ---------------------------------------------------------------------------
# Tests — get_failed_imports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_failed_imports(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """get_failed_imports returns formatted failure records."""
    mock_failures = [
        {
            "session_name": "Session 1",
            "operation": "insert",
            "error_message": "Duplicate key",
            "timestamp": "2023-01-01T01:00:00",
            "data_attempted": {"title": "Test"},
        }
    ]

    mock = _make_mock_surreal(query_return_value=mock_failures)
    with patch(DB_PATCH_TARGET, return_value=mock):
        failed = await get_failed_imports(
            "run_123", db_url, db_user, db_password, db_name, db_namespace
        )

    assert isinstance(failed, list)
    assert len(failed) == 1
    assert failed[0]["session_name"] == "Session 1"
    assert failed[0]["error"] == "Duplicate key"


@pytest.mark.asyncio
async def test_get_failed_imports_empty(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """get_failed_imports returns empty list when no failures."""
    mock = _make_mock_surreal(query_return_value=[])
    with patch(DB_PATCH_TARGET, return_value=mock):
        failed = await get_failed_imports(
            "run_123", db_url, db_user, db_password, db_name, db_namespace
        )

    assert failed == []


# ---------------------------------------------------------------------------
# Tests — rollback_import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_import(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """rollback_import deletes ONLY the exact run's session record (M4)."""
    mock = _make_mock_surreal()
    mock.query = AsyncMock(
        side_effect=[
            # 1. Get successful inserts for this run (audit carries the
            #    created session id in result_data)
            [{"id": "audit:1", "session_name": "Session A",
              "result_data": {"id": "session:1"}}],
            # 2. DELETE the exact session record
            [],
            # 3. UPDATE the audit record to rolled_back
            [],
        ]
    )

    with patch(DB_PATCH_TARGET, return_value=mock):
        result = await rollback_import(
            "run_123", db_url, db_user, db_password, db_name, db_namespace
        )

    assert result["rollback_count"] == 1
    assert result["errors"] == []
    # The DELETE must target the exact record id (not re-match by session_name,
    # which would delete legitimate records from other runs).
    delete_call = mock.query.await_args_list[1]
    assert delete_call.args[0] == "DELETE $id"
    assert delete_call.args[1] == {"id": "session:1"}
    # And the audit update must be parameterized (no f-string interpolation).
    update_sql = mock.query.await_args_list[2].args[0]
    assert "$rid" in update_sql and "$ts" in update_sql


@pytest.mark.asyncio
async def test_rollback_import_empty(
    db_url: str,
    db_user: str,
    db_password: str,
    db_name: str,
    db_namespace: str,
) -> None:
    """rollback_import handles case with nothing to rollback."""
    mock = _make_mock_surreal(query_return_value=[])
    with patch(DB_PATCH_TARGET, return_value=mock):
        result = await rollback_import(
            "run_123", db_url, db_user, db_password, db_name, db_namespace
        )

    assert result["rollback_count"] == 0
