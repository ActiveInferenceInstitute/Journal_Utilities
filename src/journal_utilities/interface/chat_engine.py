"""
LLM chat engine with RAG retrieval over Active Inference transcripts.

Uses Ollama (local) for inference, with transcript-aware context injection.
Supports streaming responses via Server-Sent Events.
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
MAX_CONTEXT_CHARS = int(os.getenv("CHAT_MAX_CONTEXT", "8000"))
MAX_HISTORY = int(os.getenv("CHAT_MAX_HISTORY", "10"))
# Upper bound on in-memory chat sessions. session_id is client-supplied and
# unbounded growth is a memory-exhaustion denial of service; when the cap is
# reached the oldest session is evicted (FIFO).
MAX_SESSIONS = int(os.getenv("CHAT_MAX_SESSIONS", "200"))

SYSTEM_PROMPT = """You are an expert research assistant for the Active Inference Institute.
You have deep knowledge of Active Inference, the Free Energy Principle, Bayesian brain theory, predictive coding, and related fields.

Your responses should be:
• Scientifically rigorous — cite specific concepts, researchers, and papers when relevant
• Accessible — explain complex ideas clearly for diverse audiences
• Grounded — when transcript context is provided, reference it directly
• Practical — connect theory to applications where appropriate

When given transcript excerpts as context, synthesize information from them to answer the user's question.
If the context doesn't contain enough information, say so honestly and provide what you know from your training.

Format responses with markdown for readability. Use LaTeX notation (e.g. $F = E_q[\\ln q - \\ln p]$) for equations."""


# ---------------------------------------------------------------------------
# Chat data models
# ---------------------------------------------------------------------------


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class ChatSession:
    """In-memory chat session with history."""

    session_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    context_video_ids: list[str] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """Add a message and trim history."""
        self.messages.append(ChatMessage(role=role, content=content))
        # Keep system + last N messages
        if len(self.messages) > MAX_HISTORY + 1:
            system_msgs = [m for m in self.messages if m.role == "system"]
            other_msgs = [m for m in self.messages if m.role != "system"]
            self.messages = system_msgs + other_msgs[-MAX_HISTORY:]

    def to_ollama_messages(self) -> list[dict[str, str]]:
        """Convert to Ollama API format."""
        return [{"role": m.role, "content": m.content} for m in self.messages]


# ---------------------------------------------------------------------------
# Chat engine
# ---------------------------------------------------------------------------


class ChatEngine:
    """RAG-augmented chat engine using Ollama."""

    def __init__(self, search_index: Any = None) -> None:  # noqa: ANN401 - injected dependency
        self.search_index = search_index
        self.sessions: dict[str, ChatSession] = {}
        self._ollama_available: bool | None = None

    async def check_ollama(self) -> dict[str, Any]:
        """Check if Ollama is available and list models.

        Also updates self.current_model to a valid available model if necessary.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]

                    # Smart model selection
                    # 1. Prefer configured model
                    # 2. Prefer standard chat models (llama, mistral, gemma, qwen)
                    # 3. Fallback to first available non-embedding model

                    selected_model = OLLAMA_MODEL

                    # Check if configured model exists (allowing for :latest or specific tags)
                    model_exists = any(m.startswith(OLLAMA_MODEL) for m in models)

                    if not model_exists and models:
                        # Try to find a good fallback
                        candidates = ["gemma", "llama", "mistral", "qwen", "deepSeek", "phi"]
                        fallback = None

                        # Filter out embedding models if possible (heuristic: "embed" in name)
                        chat_models = [m for m in models if "embed" not in m.lower()]

                        if chat_models:
                            for candidate in candidates:
                                for m in chat_models:
                                    if candidate.lower() in m.lower():
                                        fallback = m
                                        break
                                if fallback:
                                    break

                            if not fallback:
                                fallback = chat_models[0]
                        else:
                            # If all look like embeddings, just take first
                            fallback = models[0] if models else None

                        if fallback:
                            logger.info(
                                "Configured model %s not found. Falling back to %s",
                                OLLAMA_MODEL,
                                fallback,
                            )
                            selected_model = fallback

                    self._ollama_available = True
                    self.current_model = selected_model  # persist; avoids a re-probe per request
                    return {
                        "available": True,
                        "models": models,
                        "current_model": selected_model,
                        "url": OLLAMA_BASE_URL,
                    }
        except Exception as exc:  # noqa: BLE001 — probe failure is routine (Ollama not running)
            logger.debug("Ollama not available: %s", exc)

        self._ollama_available = False
        return {
            "available": False,
            "models": [],
            "current_model": OLLAMA_MODEL,
            "url": OLLAMA_BASE_URL,
            "message": "Ollama is not running. Start it with: ollama serve",
        }

    def get_or_create_session(self, session_id: str) -> ChatSession:
        """Get existing session or create new one (bounded, FIFO eviction)."""
        if session_id not in self.sessions:
            if len(self.sessions) >= MAX_SESSIONS:
                oldest = next(iter(self.sessions))
                logger.warning("evicting oldest chat session %r (cap %d)", oldest, MAX_SESSIONS)
                del self.sessions[oldest]
            session = ChatSession(session_id=session_id)
            session.add_message("system", SYSTEM_PROMPT)
            self.sessions[session_id] = session
        return self.sessions[session_id]

    def _build_rag_context(self, query: str) -> tuple[str, list[str]]:
        """Retrieve relevant transcript chunks for the query."""
        if not self.search_index:
            return "", []

        chunks = self.search_index.get_context_chunks(
            query, top_k=3, chunk_size=MAX_CONTEXT_CHARS // 3
        )
        if not chunks:
            return "", []

        video_ids = [c["video_id"] for c in chunks]
        context_parts = []
        for c in chunks:
            context_parts.append(f"[Transcript excerpt from video {c['video_id']}]\n{c['text']}\n")

        context = "\n---\n".join(context_parts)
        return context, video_ids

    async def chat(
        self,
        session_id: str,
        user_message: str,
        use_rag: bool = True,
    ) -> dict[str, Any]:
        """Send a message and get a response (non-streaming)."""
        session = self.get_or_create_session(session_id)

        # Build RAG context
        context = ""
        context_ids: list[str] = []
        if use_rag and self.search_index:
            context, context_ids = self._build_rag_context(user_message)

        # Construct user message with context
        full_message = user_message
        if context:
            full_message = (
                f"Here are relevant transcript excerpts:\n\n{context}\n\n"
                f"User question: {user_message}"
            )

        session.add_message("user", full_message)
        session.context_video_ids = context_ids

        # Call Ollama. Probe availability once, then reuse the persisted
        # model selection across requests.
        if self._ollama_available is None:
            await self.check_ollama()
        current_model = getattr(self, "current_model", OLLAMA_MODEL)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": current_model,
                        "messages": session.to_ollama_messages(),
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                assistant_msg = data.get("message", {}).get("content", "")
                session.add_message("assistant", assistant_msg)
                return {
                    "response": assistant_msg,
                    "context_video_ids": context_ids,
                    "model": current_model,
                }
        except Exception as exc:
            logger.error("Ollama chat error: %s", exc)
            # Do not echo the exception text to the client — it can leak
            # host/port/internal detail. Return a generic error instead.
            return {
                "response": "Error communicating with the Ollama model. Please try again.",
                "context_video_ids": context_ids,
                "model": OLLAMA_MODEL,
                "error": True,
            }

    async def chat_stream(
        self,
        session_id: str,
        user_message: str,
        use_rag: bool = True,
    ) -> AsyncIterator[str]:
        """Send a message and stream the response as SSE events."""
        session = self.get_or_create_session(session_id)

        # Build RAG context
        context = ""
        context_ids: list[str] = []
        if use_rag and self.search_index:
            context, context_ids = self._build_rag_context(user_message)

        # Yield context info first
        yield f"data: {json.dumps({'type': 'context', 'video_ids': context_ids})}\n\n"

        # Construct user message with context
        full_message = user_message
        if context:
            full_message = (
                f"Here are relevant transcript excerpts:\n\n{context}\n\n"
                f"User question: {user_message}"
            )

        session.add_message("user", full_message)

        # Stream from Ollama. Probe availability once, then reuse the persisted
        # model selection across requests.
        if self._ollama_available is None:
            await self.check_ollama()
        current_model = getattr(self, "current_model", OLLAMA_MODEL)

        full_response = ""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": current_model,
                        "messages": session.to_ollama_messages(),
                        "stream": True,
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                full_response += token
                                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue

            session.add_message("assistant", full_response)

        except Exception as exc:
            logger.error("Ollama stream error: %s", exc)
            # Generic message to the browser; the real exception stays in logs.
            yield f"data: {json.dumps({'type': 'error', 'message': 'Streaming error from the Ollama model.'})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    def clear_session(self, session_id: str) -> None:
        """Clear a chat session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
