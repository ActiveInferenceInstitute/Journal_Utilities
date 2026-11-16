# Web Interface (FastAPI + Vanilla JS)

The Journal Utilities **Web Interface** (`src/journal_utilities/interface/`) is a lightweight, responsive Single Page Application (SPA) for browsing the Active Inference video library.

## Features

- **Video Library**: List all videos with thumbnails, durations, and metadata.
- **Search**: Full-text search over video titles, descriptions, and transcripts (BM25 + TF-IDF).
- **Video Detail**: Embedded YouTube player, transcript viewer with synchronized highlighting, and metadata panel.
- **Chat (RAG)**: Interactive Q&A powered by Ollama and local transcript retrieval.
- **Categories**: Browse videos by series (e.g., "Math Group", "Morphology", "Livestreams") or type.
- **Knowledge Graph**: Visualize relationships between speakers, concepts, and entities (future integration with SurrealDB).

## Architecture

The interface is built with a **backend-heavy** approach using FastAPI and HTMX principles (though implemented via vanilla JS fetching for dynamic components):

### Backend (`app.py`)

- **Framework**: FastAPI (async Python)
- **Data Loader**: `src/journal_utilities/interface/data_loader.py` loads the JSON manifest and builds the in-memory search index on startup.
- **API Endpoints**:
  - `GET /api/stats`: Library statistics
  - `GET /api/videos`: List all videos (paginated, filterable by category)
  - `GET /api/videos/{id}`: Detailed info for a single video
  - `GET /api/transcripts/{id}`: Transcript text for a video
  - `GET /api/audio/{id}`: Stream audio with Range header support
  - `GET /api/categories`: All categories with video counts
  - `GET /api/search`: Full-text search across transcripts
  - `GET /api/chat/status`: Check LLM (Ollama) availability
  - `POST /api/chat`: Send a chat message (non-streaming)
  - `POST /api/chat/stream`: Send a chat message with SSE streaming response
  - `POST /api/chat/clear`: Clear a chat session

### Frontend (`static/`)

- **HTML**: `index.html` (single entry point)
- **CSS**: `styles.css` (custom CSS variables, dark mode default)
- **JavaScript**: `app.js` (client-side router, state management, API calls)
  - **Router**: Hash-based routing (`#library`, `#video/ID`, `#chat`)
  - **Components**: Dynamic DOM creation for video cards, chat bubbles, etc.
  - **State**: Central `state` object for current view, search query, and pagination.

### Source Structure

```text
src/journal_utilities/interface/
├── app.py             # FastAPI application entry point
├── chat_engine.py     # RAG logic and Ollama integration
├── data_loader.py     # Loads metrics and search index
└── static/            # Frontend assets (served directly)
    ├── index.html     # Single Page App entry
    ├── styles.css     # CSS variables and dark mode
    └── app.js         # Client-side router and logic
```

### Setup & Running

1. **Install Interface Dependencies**:

    ```bash
    uv pip install -e ".[interface]"
    ```

2. **Start the Server**:

    ```bash
    uv run python run.py serve
    ```

    Or directly:

    ```bash
    uv run uvicorn journal_utilities.interface.app:create_app --factory --reload
    ```

3. **Access**: Open `http://localhost:8000` in your browser.

## Development

The frontend files are served directly from `src/journal_utilities/interface/static/`. Changes to HTML/CSS/JS are reflected immediately on refresh (if running with `--reload` or similar dev server).

**Key Files:**

- `src/journal_utilities/interface/app.py`: Main application logic.
- `src/journal_utilities/interface/static/app.js`: Core frontend logic (routing, rendering).
- `src/journal_utilities/interface/static/index.html`: Base layout.

## Request admission limits

Chat, streaming chat and clear-session requests must be JSON objects with
string `session_id` (default `default`, at most 200 characters), string `message`
(default empty, at most 32000 characters), and boolean `use_rag` (default true).
Chat and streaming require a nonblank message. Clear validates provided fields
but does not require a message. Malformed JSON or an empty required message
returns 400; invalid shapes/types return 422; byte or field limits return 413
before a provider request or streaming response starts.

The application retains at most 387424 body bytes before JSON decoding and
rejects an over-limit chunk before appending it. Streamed bytes are checked even
with missing or understated Content-Length. This does not bound upstream
server/ASGI transport allocations.

Video pagination requires offset >= 0 and limit 1..200. Search requires limit
1..100; internal unlimited search remains available through `limit=None`.

`run.py serve` uses the configured corpus and refuses occupied ports without
terminating another process. Browser fixtures must use canonical 11-character
YouTube IDs; external thumbnails, fonts and embedded video still need network
access independently of the locally served transcript.
