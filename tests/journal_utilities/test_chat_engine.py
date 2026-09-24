from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("httpx")  # Requires the interface extra
import httpx

from journal_utilities.interface.chat_engine import ChatEngine


@pytest.fixture
def mock_search_index():
    index = MagicMock()
    index.get_context_chunks.return_value = [
        {"video_id": "v1", "text": "This is a transcript excerpt."},
        {"video_id": "v2", "text": "Another excerpt here."}
    ]
    return index

@pytest.mark.asyncio
async def test_chat_success(mock_search_index):
    engine = ChatEngine()
    engine.search_index = mock_search_index

    with patch("journal_utilities.interface.chat_engine.httpx.AsyncClient") as mock_client:
        mock_post = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Hello! I can help you with that."}}
        mock_post.return_value = mock_response

        mock_client.return_value.__aenter__.return_value.post = mock_post

        response = await engine.chat("test_session", "What is this?", use_rag=True)

        # Check for error first
        if "error" in response:
            pytest.fail(f"Chat failed with error: {response['error']}")

        assert response["response"] == "Hello! I can help you with that."
        assert len(response["context_video_ids"]) == 2

        # Verify prompt construction
        call_args = mock_post.call_args
        assert call_args is not None
        payload = call_args[1]["json"]
        messages = payload["messages"]
        last_msg = messages[-1]["content"]
        assert "This is a transcript excerpt." in last_msg
        assert "User question: What is this?" in last_msg

@pytest.mark.asyncio
async def test_chat_stream_success(mock_search_index):
    engine = ChatEngine()
    engine.search_index = mock_search_index

    with patch("journal_utilities.interface.chat_engine.httpx.AsyncClient") as mock_client:
        # stream is NOT an async function, it returns an async context manager
        mock_stream_ctx = MagicMock()

        # Mock streaming response
        async def mock_aiter_lines():
            yield '{"message": {"content": "Hello"}, "done": false}'
            yield '{"message": {"content": " world"}, "done": true}'

        mock_response = AsyncMock()
        mock_response.aiter_lines = mock_aiter_lines

        mock_stream_ctx.__aenter__.return_value = mock_response
        mock_stream_ctx.__aexit__.return_value = None

        mock_stream = MagicMock(return_value=mock_stream_ctx)

        mock_client.return_value.__aenter__.return_value.stream = mock_stream

        chunks = []
        async for chunk in engine.chat_stream("test_session", "Hi", use_rag=True):
            chunks.append(chunk)

        # Verify chunks
        # 1. Context
        assert 'type": "context"' in chunks[0]
        # 2. Token 1
        assert 'type": "token"' in chunks[1]
        assert 'Hello' in chunks[1]
        # 3. Token 2
        assert 'type": "token"' in chunks[2]
        assert ' world' in chunks[2]
        # 4. Done
        assert 'type": "done"' in chunks[3]

@pytest.mark.asyncio
async def test_chat_error_handling(mock_search_index):
    engine = ChatEngine()

    with patch("journal_utilities.interface.chat_engine.httpx.AsyncClient") as mock_client:
        mock_post = AsyncMock()
        mock_post.side_effect = httpx.RequestError("Connection failed")
        mock_client.return_value.__aenter__.return_value.post = mock_post

        response = await engine.chat("test_session", "Fail me")

        # Sanitized: a generic message, and the raw exception detail must NOT
        # leak to the client (even though it is logged server-side).
        assert "Error communicating with the Ollama model" in response["response"]
        assert "Connection failed" not in response["response"]
        assert response["error"] is True
