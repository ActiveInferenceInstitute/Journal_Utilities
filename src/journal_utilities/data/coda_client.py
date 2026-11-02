"""
Coda (Superhuman Docs) API client for fetching table rows.

Coda was renamed Superhuman Docs on 2026-07-08; the v1 endpoints at
``coda.io/apis/v1`` continue to work and ``docs.superhuman.com`` is accepted
as an alternative base. Base URL is configurable via ``CODA_API_BASE``.
Uses stdlib ``urllib`` only — no new dependencies.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://coda.io/apis/v1"
DOC_ID = "TwB_SP81yq"
TABLE_ID = "grid-cjvFiXp3a3"
PAGE_LIMIT = 200
MAX_RETRIES = 3
# Hard cap on pagination pages so a misbehaving (self-referencing or
# non-terminating) nextPageLink can never loop forever.
MAX_PAGES = 200


class CodaAuthError(RuntimeError):
    """Raised when no API token is available."""


def fetch_table_rows(
    doc_id: str = DOC_ID,
    table_id: str = TABLE_ID,
    token: str | None = None,
    base_url: str | None = None,
    limit: int = PAGE_LIMIT,
) -> list[dict[str, Any]]:
    """Fetch all rows of a table, following nextPageLink pagination."""
    token = token or os.environ.get("CODA_API_TOKEN", "")
    if not token:
        raise CodaAuthError("CODA_API_TOKEN is not set")
    base = (base_url or os.environ.get("CODA_API_BASE", DEFAULT_BASE)).rstrip("/")
    url = f"{base}/docs/{doc_id}/tables/{table_id}/rows?limit={limit}&useColumnNames=true"

    items: list[dict[str, Any]] = []
    page = 0
    while url:
        page += 1
        if page > MAX_PAGES:
            logger.warning(
                "coda: pagination exceeded %d pages — stopping to avoid an infinite loop",
                MAX_PAGES,
            )
            break
        data = _get_json(url, token)
        batch = data.get("items", [])
        items.extend(batch)
        logger.info("coda: page %d -> %d rows (total %d)", page, len(batch), len(items))
        next_url = data.get("nextPageLink")
        if not next_url:
            break
        if next_url == url:  # self-referencing link — would never terminate
            logger.warning("coda: nextPageLink did not advance; stopping pagination")
            break
        url = next_url
    return items


def _get_json(url: str, token: str) -> dict[str, Any]:
    """GET + parse JSON, retrying transient failures with backoff.

    Retries on HTTP 429, server 5xx, and connection/timeout errors so a
    transient blip doesn't abort a long table fetch, bounded by a total
    deadline rather than an unbounded loop.
    """
    deadline = time.monotonic() + 120  # overall budget for one request
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return cast(dict[str, Any], json.load(resp))
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            if not (retryable and attempt < MAX_RETRIES and time.monotonic() < deadline):
                raise
            wait = min(2 ** (attempt + 1), 30)
            logger.warning("coda: HTTP %d, retrying in %ds", exc.code, wait)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError):
            if not (attempt < MAX_RETRIES and time.monotonic() < deadline):
                raise
            wait = min(2 ** (attempt + 1), 30)
            logger.warning("coda: connection error, retrying in %ds", wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def load_rows(
    snapshot_path: Path,
    cache_path: Path,
    fetch: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """
    Return (rows, source_label).

    Tries a live API fetch (cached to ``cache_path``) when ``fetch`` is true;
    falls back to an existing cache, then to the checked-in snapshot.
    """
    if fetch:
        try:
            items = fetch_table_rows()
            cache_path.write_text(
                json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
            )
            return items, f"api ({len(items)} rows, cached to {cache_path.name})"
        except CodaAuthError as exc:
            logger.warning("coda fetch skipped: %s", exc)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            logger.warning("coda fetch failed: %s", exc)
    if cache_path.exists():
        items = cast(
            list[dict[str, Any]],
            json.loads(cache_path.read_text(encoding="utf-8")).get("items", []),
        )
        return items, f"cache {cache_path.name} ({len(items)} rows)"
    items = cast(
        list[dict[str, Any]], json.loads(snapshot_path.read_text(encoding="utf-8")).get("items", [])
    )
    return items, f"snapshot {snapshot_path.name} ({len(items)} rows — one page, coverage reduced)"
