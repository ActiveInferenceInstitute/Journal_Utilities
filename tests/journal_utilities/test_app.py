"""
Test suite for the web interface application (app.py).

Tests the FastAPI endpoints using the TestClient, exercising all API
routes: stats, videos, transcripts, search, categories, and chat.
"""

import json
from pathlib import Path

import pytest

# Requires the interface extra; skip cleanly when it is not installed.
pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from journal_utilities.interface import chat_engine
from journal_utilities.interface.app import (
    MAX_CHAT_BODY_BYTES,
    MAX_MESSAGE_LENGTH,
    MAX_SESSION_LENGTH,
    create_app,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def ollama_transport(monkeypatch):
    """Run real ChatEngine logic, with only HTTP transport replaced; never sockets."""
    state = {"requests": [], "fail": False}
    client_type = httpx.AsyncClient

    def handle(request):
        state["requests"].append(request)
        if state["fail"]:
            raise httpx.ConnectError(
                "Connection to http://private-host:11434 failed", request=request
            )
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": chat_engine.OLLAMA_MODEL}]})
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        if payload["stream"]:
            return httpx.Response(
                200,
                content=(
                    json.dumps({"message": {"content": "Bounded answer"}, "done": False})
                    + "\n"
                    + json.dumps({"done": True})
                    + "\n"
                ),
                headers={"content-type": "application/x-ndjson"},
            )
        return httpx.Response(200, json={"message": {"content": "Bounded answer"}})

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handle)
        return client_type(*args, **kwargs)

    monkeypatch.setattr(chat_engine.httpx, "AsyncClient", client)
    return state


@pytest.fixture
def sample_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with realistic sample data."""
    data_dir = tmp_path / "data" / "output"
    data_dir.mkdir(parents=True)

    # Create channel_videos.json
    manifest = {
        "channel_id": "UCtest123456789012345",
        "channel_url": "https://www.youtube.com/channel/UCtest123456789012345",
        "enumerated_at": "2025-01-01T00:00:00Z",
        "total_videos": 3,
        "videos": [
            {
                "id": "vid_aaa11111111",
                "title": "Active Inference Livestream #1",
                "upload_date": "20240101",
                "duration": 3600.0,
                "description": "First livestream about active inference.",
                "view_count": 1000,
            },
            {
                "id": "vid_bbb22222222",
                "title": "Textbook Group Session 5",
                "upload_date": "20240215",
                "duration": 5400.0,
                "description": "Discussion of chapter 5.",
                "view_count": 500,
            },
            {
                "id": "vid_ccc33333333",
                "title": "Symposium 2024 Keynote",
                "upload_date": "20240320",
                "duration": 2700.0,
                "description": "Keynote presentation.",
                "view_count": 2000,
            },
        ],
    }
    (data_dir / "channel_videos.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Create transcript files
    transcripts_dir = data_dir / "transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "vid_aaa11111111.txt").write_text(
        "This is the transcript for the first livestream about active inference and free energy principle.",
        encoding="utf-8",
    )
    (transcripts_dir / "vid_bbb22222222.txt").write_text(
        "In this session we discuss chapter five of the textbook covering Bayesian inference.",
        encoding="utf-8",
    )
    # vid_ccc has no transcript intentionally

    return data_dir


@pytest.fixture
def test_client(sample_data_dir: Path):
    """Create a FastAPI test client with sample data loaded.

    The ``with`` block triggers the FastAPI *lifespan* context-manager,
    which in turn calls ``loader.load()``.
    """
    app = create_app(data_dir=sample_data_dir)
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


class TestStatsEndpoint:
    """Tests for GET /api/stats."""

    def test_stats_returns_valid_structure(self, test_client: TestClient):
        """Stats endpoint returns a dict with expected keys."""
        resp = test_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_videos" in data
        assert "with_transcripts" in data
        assert data["total_videos"] == 3

    def test_stats_transcript_count(self, test_client: TestClient):
        """Stats correctly counts videos with transcripts."""
        data = test_client.get("/api/stats").json()
        assert data["with_transcripts"] == 2  # Only 2 of 3 have transcripts


# ---------------------------------------------------------------------------
# Videos endpoint
# ---------------------------------------------------------------------------


class TestVideosEndpoint:
    """Tests for GET /api/videos."""

    def test_list_all_videos(self, test_client: TestClient):
        """Videos endpoint returns paginated video list."""
        resp = test_client.get("/api/videos")
        assert resp.status_code == 200
        data = resp.json()
        assert "videos" in data
        assert "total" in data
        assert data["total"] == 3

    def test_pagination_offset_limit(self, test_client: TestClient):
        """Pagination works with offset and limit."""
        resp = test_client.get("/api/videos?offset=1&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["videos"]) == 1
        assert data["offset"] == 1
        assert data["limit"] == 1

    def test_filter_has_transcript(self, test_client: TestClient):
        """Filter by has_transcript=true."""
        resp = test_client.get("/api/videos?has_transcript=true")
        assert resp.status_code == 200
        data = resp.json()
        for v in data["videos"]:
            assert v["has_transcript"] is True

    def test_search_via_query(self, test_client: TestClient):
        """Search mode via ?q= parameter."""
        resp = test_client.get("/api/videos?q=active+inference")
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert data["query"] == "active inference"


# ---------------------------------------------------------------------------
# Single video endpoint
# ---------------------------------------------------------------------------


class TestSingleVideoEndpoint:
    """Tests for GET /api/videos/{video_id}."""

    def test_get_existing_video(self, test_client: TestClient):
        """Retrieve a known video by ID."""
        resp = test_client.get("/api/videos/vid_aaa11111111")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "vid_aaa11111111"
        assert "Active Inference" in data["title"]

    def test_get_nonexistent_video(self, test_client: TestClient):
        """404 for unknown video ID."""
        resp = test_client.get("/api/videos/nonexistent_id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Transcript endpoint
# ---------------------------------------------------------------------------


class TestTranscriptEndpoint:
    """Tests for GET /api/transcripts/{video_id}."""

    def test_get_existing_transcript(self, test_client: TestClient):
        """Retrieve transcript for a video that has one."""
        resp = test_client.get("/api/transcripts/vid_aaa11111111")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "active inference" in data["text"].lower()

    def test_get_missing_transcript(self, test_client: TestClient):
        """404 for a video without a transcript."""
        resp = test_client.get("/api/transcripts/vid_ccc33333333")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------


class TestSearchEndpoint:
    """Tests for GET /api/search."""

    def test_search_returns_results(self, test_client: TestClient):
        """Search finds matching transcripts."""
        resp = test_client.get("/api/search?q=active+inference")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) > 0
        assert data["query"] == "active inference"

    def test_search_too_short_query(self, test_client: TestClient):
        """Search rejects queries shorter than 2 characters."""
        resp = test_client.get("/api/search?q=a")
        assert resp.status_code == 422  # FastAPI validation error

    def test_search_result_structure(self, test_client: TestClient):
        """Each search result has expected fields."""
        resp = test_client.get("/api/search?q=bayesian+inference")
        data = resp.json()
        if data["results"]:
            result = data["results"][0]
            assert "video_id" in result
            assert "title" in result
            assert "score" in result
            assert "snippet" in result


# ---------------------------------------------------------------------------
# Categories endpoint
# ---------------------------------------------------------------------------


class TestCategoriesEndpoint:
    """Tests for GET /api/categories."""

    def test_categories_returns_dict(self, test_client: TestClient):
        """Categories endpoint returns category → count mapping."""
        resp = test_client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert isinstance(data["categories"], dict)


# ---------------------------------------------------------------------------
# Chat endpoints
# ---------------------------------------------------------------------------


class TestChatEndpoints:
    """Tests for the chat API endpoints."""

    def test_chat_status(self, test_client: TestClient):
        """GET /api/chat/status returns availability info."""
        resp = test_client.get("/api/chat/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["current_model"] == chat_engine.OLLAMA_MODEL

    def test_chat_empty_message_rejected(self, test_client: TestClient):
        """POST /api/chat rejects empty messages."""
        resp = test_client.post(
            "/api/chat",
            json={"session_id": "test", "message": "   "},
        )
        assert resp.status_code == 400

    def test_chat_stream_empty_message_rejected(self, test_client: TestClient):
        """POST /api/chat/stream rejects empty messages."""
        resp = test_client.post(
            "/api/chat/stream",
            json={"session_id": "test", "message": ""},
        )
        assert resp.status_code == 400

    def test_chat_clear_session(self, test_client: TestClient):
        """POST /api/chat/clear successfully clears a session."""
        resp = test_client.post(
            "/api/chat/clear",
            json={"session_id": "test_clear"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cleared"


# ---------------------------------------------------------------------------
# SPA / Static fallback
# ---------------------------------------------------------------------------


class TestSPAFallback:
    """Tests for the root endpoint and SPA serving."""

    def test_root_returns_html(self, test_client: TestClient):
        """Root returns HTML content."""
        resp = test_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Additional endpoint coverage
# ---------------------------------------------------------------------------


class TestStatsEndpointAdditional:
    """Additional stats tests for completeness."""

    def test_stats_has_audio_field(self, test_client: TestClient):
        """Stats endpoint includes with_audio count."""
        resp = test_client.get("/api/stats")
        data = resp.json()
        assert "with_audio" in data
        assert isinstance(data["with_audio"], int)

    def test_stats_has_category_count(self, test_client: TestClient):
        """Stats endpoint includes category_count."""
        resp = test_client.get("/api/stats")
        data = resp.json()
        assert "category_count" in data


class TestVideosEndpointAdditional:
    """Additional videos endpoint tests."""

    def test_videos_sorted_by_date_descending(self, test_client: TestClient):
        """Default video listing is sorted newest-first."""
        resp = test_client.get("/api/videos")
        videos = resp.json()["videos"]
        dates = [v.get("upload_date", "") for v in videos if v.get("upload_date")]
        assert dates == sorted(dates, reverse=True)

    def test_filter_by_category(self, test_client: TestClient):
        """Videos can be filtered by category query parameter."""
        resp = test_client.get("/api/videos", params={"category": "Livestream"})
        assert resp.status_code == 200
        videos = resp.json()["videos"]
        for v in videos:
            assert v.get("category") == "Livestream"


class TestTranscriptEndpointAdditional:
    """Additional transcript endpoint tests."""

    def test_transcript_content_roundtrip(self, test_client: TestClient):
        """Transcript endpoint returns the actual transcript text."""
        resp = test_client.get("/api/transcripts/vid_aaa11111111")
        assert resp.status_code == 200
        data = resp.json()
        assert "active inference" in data.get("text", "").lower()


class TestSearchEndpointAdditional:
    """Additional search endpoint tests."""

    def test_search_snippet_contains_query_term(self, test_client: TestClient):
        """Search result snippets contain the searched term."""
        resp = test_client.get("/api/search", params={"q": "Bayesian"})
        assert resp.status_code == 200
        results = resp.json().get("results", [])
        if results:
            snippet = results[0].get("snippet", "").lower()
            assert "bayesian" in snippet or "bayes" in snippet

    def test_search_no_results(self, test_client: TestClient):
        """Search for non-existent term returns empty results."""
        resp = test_client.get("/api/search", params={"q": "xyznonexistent12345"})
        assert resp.status_code == 200
        assert len(resp.json().get("results", [])) == 0


class TestChatEndpointsAdditional:
    """Additional chat endpoint tests."""

    def test_chat_with_valid_message_returns_response(self, test_client: TestClient):
        resp = test_client.post("/api/chat", json={"message": "What is active inference?"})
        assert resp.status_code == 200
        assert resp.json()["response"] == "Bounded answer"

    def test_transport_failure_is_sanitized(self, test_client: TestClient, ollama_transport):
        ollama_transport["fail"] = True
        resp = test_client.post("/api/chat", json={"message": "What is active inference?"})
        assert resp.status_code == 200
        assert resp.json()["error"] is True
        assert "private-host" not in resp.text
        assert "http://" not in resp.text

    def test_chat_rejects_oversized_message(self, test_client: TestClient):
        """An over-long message is rejected (413), not forwarded to Ollama."""
        resp = test_client.post(
            "/api/chat",
            json={"session_id": "s", "message": "x" * 40_000},
        )
        assert resp.status_code == 413


CHAT_ROUTES = ["/api/chat", "/api/chat/stream", "/api/chat/clear"]


@pytest.mark.parametrize("route", CHAT_ROUTES)
@pytest.mark.parametrize(
    "body,status",
    [
        (b"null", 422),
        (b"[]", 422),
        (b"3", 422),
        (b'"text"', 422),
        (b"true", 422),
        (b"{broken", 400),
        (b"\xff", 400),
        (b'{"message": null}', 422),
        (b'{"message": []}', 422),
        (b'{"message": 1}', 422),
        (b'{"message": "hello", "session_id": null}', 422),
        (b'{"message": "hello", "session_id": {}}', 422),
        (b'{"message": "hello", "session_id": 1}', 422),
        (b'{"message": "hello", "use_rag": "false"}', 422),
        (b'{"message": "hello", "use_rag": 0}', 422),
        (b'{"message": "hello", "use_rag": null}', 422),
    ],
)
def test_invalid_chat_payloads_are_client_errors(
    test_client, ollama_transport, route, body, status
):
    response = test_client.post(route, content=body, headers={"content-type": "application/json"})
    assert response.status_code == status
    assert ollama_transport["requests"] == []


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
def test_exact_field_bounds_allow_escaped_unicode(test_client, route):
    payload = {
        "message": "😀" * MAX_MESSAGE_LENGTH,
        "session_id": "s" * MAX_SESSION_LENGTH,
        "use_rag": False,
    }
    response = test_client.post(
        route, content=json.dumps(payload), headers={"content-type": "application/json"}
    )
    assert response.status_code == 200
    if route.endswith("/stream"):
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert [event["type"] for event in events] == ["context", "token", "done"]
        assert events[1]["content"] == "Bounded answer"
    else:
        assert response.json()["response"] == "Bounded answer"


@pytest.mark.parametrize("route", CHAT_ROUTES)
@pytest.mark.parametrize(
    "field,length", [("message", MAX_MESSAGE_LENGTH + 1), ("session_id", MAX_SESSION_LENGTH + 1)]
)
def test_field_limit_plus_one_never_reaches_transport(
    test_client, ollama_transport, route, field, length
):
    payload = {"message": "hello", "session_id": "session", "use_rag": False, field: "x" * length}
    assert test_client.post(route, json=payload).status_code == 413
    assert ollama_transport["requests"] == []


@pytest.mark.parametrize("extra,status", [(0, 200), (1, 413)])
def test_exact_body_limit(test_client, extra, status):
    message = b'{"message":"hello","use_rag":false}'
    body = message + b" " * (MAX_CHAT_BODY_BYTES + extra - len(message))
    assert test_client.post("/api/chat", content=body).status_code == status


@pytest.mark.parametrize("route", CHAT_ROUTES)
@pytest.mark.parametrize("declared", [None, b"1", str(MAX_CHAT_BODY_BYTES + 1).encode()])
@pytest.mark.parametrize("single_chunk", [False, True])
async def test_streamed_body_stops_before_full_accumulation(
    sample_data_dir, ollama_transport, route, declared, single_chunk
):
    app = create_app(data_dir=sample_data_dir)
    chunks = (
        [b"x" * (MAX_CHAT_BODY_BYTES + 1), b"unread"]
        if single_chunk
        else [b"x" * (MAX_CHAT_BODY_BYTES - 5), b"0123456789", b"unread"]
    )
    consumed = 0
    sent = []
    headers = [(b"content-type", b"application/json")]
    if declared is not None:
        headers.append((b"content-length", declared))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": route,
        "raw_path": route.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "server": ("test", 80),
        "client": ("test", 1234),
    }

    async def receive():
        nonlocal consumed
        if consumed >= len(chunks) - 1:
            pytest.fail("request drained beyond the byte cap")
        chunk = chunks[consumed]
        consumed += 1
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    assert (
        next(message["status"] for message in sent if message["type"] == "http.response.start")
        == 413
    )
    assert consumed == (
        0 if declared == str(MAX_CHAT_BODY_BYTES + 1).encode() else (1 if single_chunk else 2)
    )
    assert ollama_transport["requests"] == []


@pytest.mark.parametrize(
    "url",
    [
        "/api/videos?offset=-1",
        "/api/videos?limit=0",
        "/api/videos?limit=-1",
        "/api/videos?limit=201",
        "/api/videos?q=active&offset=-1",
        "/api/search?q=active&limit=0",
        "/api/search?q=active&limit=-1",
        "/api/search?q=active&limit=101",
    ],
)
def test_pagination_rejects_invalid_bounds(test_client, url):
    assert test_client.get(url).status_code == 422


def test_pagination_upper_bounds_remain_valid(test_client):
    videos = test_client.get("/api/videos?offset=0&limit=200")
    assert videos.status_code == 200
    assert videos.json()["total"] == 3
    results = test_client.get("/api/search?q=Bayesian&limit=100")
    assert results.status_code == 200
    assert results.json()["results"][0]["video_id"] == "vid_bbb22222222"


def test_clear_removes_history_without_provider_call(test_client, ollama_transport):
    assert (
        test_client.post(
            "/api/chat", json={"session_id": "s", "message": "first", "use_rag": False}
        ).status_code
        == 200
    )
    before = len(ollama_transport["requests"])
    assert test_client.post("/api/chat/clear", json={"session_id": "s"}).json() == {
        "status": "cleared"
    }
    assert len(ollama_transport["requests"]) == before
    assert (
        test_client.post(
            "/api/chat", json={"session_id": "s", "message": "second", "use_rag": False}
        ).status_code
        == 200
    )
    payload = json.loads(ollama_transport["requests"][-1].content)
    assert [message["content"] for message in payload["messages"] if message["role"] == "user"] == [
        "second"
    ]
