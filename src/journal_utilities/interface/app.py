"""
FastAPI web application for the Active Inference Institute interface.

Serves the SPA frontend and provides API endpoints for videos,
transcripts, audio streaming, search, and LLM chat.
"""

import logging
import mimetypes
import os
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError

from journal_utilities.interface.chat_engine import ChatEngine
from journal_utilities.interface.data_loader import DataLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"

MAX_MESSAGE_LENGTH = 32_000
MAX_SESSION_LENGTH = 200
# JSON can escape one non-BMP character as two six-byte Unicode escapes.
MAX_CHAT_BODY_BYTES = 12 * (MAX_MESSAGE_LENGTH + MAX_SESSION_LENGTH) + 1024


class _ChatRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    session_id: str = "default"
    message: str = ""
    use_rag: bool = True


async def _read_chat_request(request: Request, *, require_message: bool) -> _ChatRequest:
    """Bound retained bytes before JSON decoding, independent of Content-Length."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if length > MAX_CHAT_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Chat request body too large")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_CHAT_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Chat request body too large")
        body.extend(chunk)
    try:
        payload = _ChatRequest.model_validate_json(body)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        status = 400 if any(error["type"] == "json_invalid" for error in errors) else 422
        raise HTTPException(status_code=status, detail="Invalid chat request") from exc
    if len(payload.message) > MAX_MESSAGE_LENGTH or len(payload.session_id) > MAX_SESSION_LENGTH:
        raise HTTPException(status_code=413, detail="Message or session id too long")
    if require_message and not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    return payload


def create_app(data_dir: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    # Initialize data loader and chat engine
    loader = DataLoader(data_dir=data_dir)
    chat_engine = ChatEngine()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Load data on startup, cleanup on shutdown."""
        loader.load()
        chat_engine.search_index = loader.search_index
        logger.info("Application ready — %d videos loaded", len(loader.videos))
        yield
        logger.info("Application shutting down")

    app = FastAPI(
        title="Active Inference Institute",
        description="Transcript library and research chat for the Active Inference channel",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS for development. The SPA uses no cookies/credentials, so
    # allow_credentials must stay False — a wildcard origin with credentials is
    # both rejected by browsers and an unrestricted cross-origin attack surface
    # if this is ever bound beyond localhost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # API routes
    # ------------------------------------------------------------------

    @app.get("/api/stats")
    async def get_stats() -> dict[str, Any]:
        """Get aggregate channel statistics."""
        return loader.get_stats()

    @app.get("/api/videos")
    async def get_videos(
        category: str | None = None,
        has_transcript: bool | None = None,
        sort_by: str = "upload_date",
        reverse: bool = True,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        q: str | None = None,
    ) -> dict[str, Any]:
        """Get paginated, filterable list of videos."""
        if q:
            # Search mode: honor the same offset/limit pagination as listing and
            # report the true result count (not the page size).
            all_results = loader.search_index.search(q, limit=None)
            total = len(all_results)
            page = all_results[offset : offset + limit]
            video_dicts = []
            for r in page:
                video = loader.get_video(r.video_id)
                if video:
                    d = video.to_dict()
                    d["search_score"] = r.score
                    d["search_snippet"] = r.snippet
                    video_dicts.append(d)
            return {
                "videos": video_dicts,
                "total": total,
                "query": q,
                "offset": offset,
                "limit": limit,
            }

        # Normal listing
        records, total = loader.get_all_videos(
            category=category,
            has_transcript=has_transcript,
            sort_by=sort_by,
            reverse=reverse,
            offset=offset,
            limit=limit,
        )
        return {
            "videos": [r.to_dict() for r in records],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @app.get("/api/videos/{video_id}")
    async def get_video(video_id: str) -> dict[str, Any]:
        """Get detailed info for a single video."""
        record = loader.get_video(video_id)
        if not record:
            raise HTTPException(status_code=404, detail="Video not found")
        return record.to_dict()

    @app.get("/api/transcripts/{video_id}")
    async def get_transcript(video_id: str) -> dict[str, Any]:
        """Get transcript text for a video."""
        record = loader.get_video(video_id)
        if not record or not record.has_transcript:
            raise HTTPException(status_code=404, detail="Transcript not found")

        text = loader.search_index.get_transcript(video_id)
        if not text and record.transcript_path:
            try:
                text = Path(record.transcript_path).read_text(encoding="utf-8")
            except OSError:
                raise HTTPException(status_code=500, detail="Failed to read transcript") from None

        return {
            "video_id": video_id,
            "text": text or "",
            "size": record.transcript_size,
            "title": record.title,
        }

    @app.get("/api/audio/{video_id}")
    async def stream_audio(video_id: str, request: Request) -> StreamingResponse:
        """Stream audio file with Range header support."""
        record = loader.get_video(video_id)
        if not record or not record.has_audio or not record.audio_path:
            raise HTTPException(status_code=404, detail="Audio not found")

        audio_path = Path(record.audio_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio file missing")

        file_size = audio_path.stat().st_size
        content_type = mimetypes.guess_type(str(audio_path))[0] or "audio/mpeg"

        # Handle Range requests for seeking. Only single byte ranges are
        # supported; suffix ranges ("bytes=-N") and open-ended ranges are
        # normalized, and out-of-bounds requests are clamped so the computed
        # Content-Length/Content-Range can never go negative or malformed.
        range_header = request.headers.get("range")
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not m:
                raise HTTPException(status_code=416, detail="Unsupported range request")
            start_s, end_s = m.groups()
            try:
                if not start_s and not end_s:
                    start, end = 0, file_size - 1
                elif not start_s:  # suffix range: last N bytes
                    length = int(end_s)
                    start = max(0, file_size - length)
                    end = file_size - 1
                else:
                    start = int(start_s)
                    end = int(end_s) if end_s else file_size - 1
            except ValueError:
                raise HTTPException(status_code=416, detail="Invalid range header") from None
            if start >= file_size:
                raise HTTPException(
                    status_code=416,
                    detail=f"Requested range start {start} >= size {file_size}",
                    headers={"Content-Range": f"bytes */{file_size}"},
                )
            start = max(start, 0)
            end = min(end, file_size - 1)
            end = max(end, start)
            content_length = end - start + 1

            def iter_range() -> Iterator[bytes]:
                with open(audio_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        chunk_size = min(8192, remaining)
                        data = f.read(chunk_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return StreamingResponse(
                iter_range(),
                status_code=206,
                media_type=content_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                },
            )

        # Full file
        def iter_file() -> Iterator[bytes]:
            with open(audio_path, "rb") as f:
                while True:
                    data = f.read(8192)
                    if not data:
                        break
                    yield data

        return StreamingResponse(
            iter_file(),
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    @app.get("/api/categories")
    async def get_categories() -> dict[str, Any]:
        """Get all categories with video counts."""
        return {"categories": {cat: len(vids) for cat, vids in sorted(loader.categories.items())}}

    @app.get("/api/search")
    async def search(
        q: str = Query(..., min_length=2),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        """Full-text search across all transcripts."""
        results = loader.search_index.search(q, limit=limit)
        items = []
        for r in results:
            video = loader.get_video(r.video_id)
            items.append(
                {
                    "video_id": r.video_id,
                    "title": video.title if video else "",
                    "category": video.category if video else None,
                    "score": r.score,
                    "snippet": r.snippet,
                    "thumbnail_url": video.thumbnail_url if video else "",
                }
            )
        return {"results": items, "total": len(items), "query": q}

    # ------------------------------------------------------------------
    # Chat API
    # ------------------------------------------------------------------

    @app.get("/api/chat/status")
    async def chat_status() -> dict[str, Any]:
        """Check LLM availability."""
        return await chat_engine.check_ollama()

    @app.post("/api/chat")
    async def chat_message(request: Request) -> dict[str, Any]:
        """Send a validated, bounded chat message (non-streaming)."""
        payload = await _read_chat_request(request, require_message=True)
        return await chat_engine.chat(payload.session_id, payload.message, use_rag=payload.use_rag)

    @app.post("/api/chat/stream")
    async def chat_stream(request: Request) -> StreamingResponse:
        """Validate completely before opening a streaming response."""
        payload = await _read_chat_request(request, require_message=True)
        return StreamingResponse(
            chat_engine.chat_stream(payload.session_id, payload.message, use_rag=payload.use_rag),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.post("/api/chat/clear")
    async def chat_clear(request: Request) -> dict[str, str]:
        """Clear a validated session without calling a provider."""
        payload = await _read_chat_request(request, require_message=False)
        chat_engine.clear_session(payload.session_id)
        return {"status": "cleared"}

    # ------------------------------------------------------------------
    # Static files + SPA fallback
    # ------------------------------------------------------------------

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> HTMLResponse:
        """Serve the SPA."""
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<h1>Active Inference Institute</h1><p>Static files not found.</p>"
        )

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the development server."""
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting Active Inference Institute interface on %s:%d", host, port)

    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
