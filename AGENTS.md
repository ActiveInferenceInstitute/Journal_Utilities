# AGENTS.md

> [!IMPORTANT]
> **READ THIS FILE FIRST** before attempting any changes. This repository follows strict architectural and documentation standards.

## 1. Project Overview

Journal-Utilities is a modular, config-driven system for processing the Active Inference Institute's digital library.

### Core Pipelines

| Pipeline | Source | Key Files | Doc Reference |
| :--- | :--- | :--- | :--- |
| **YouTube** | `src/journal_utilities/youtube/` | `channel.py`, `categorizer.py` | [docs/youtube.md](docs/youtube.md) |
| **Download** | `src/journal_utilities/download/` | `downloader.py` | [docs/youtube_download.md](docs/youtube_download.md) |
| **Transcription** | `src/journal_utilities/transcribe/` | `transcriber.py` (Mac), `transcribe.py` (GPU) | [docs/transcription.md](docs/transcription.md) |
| **Data** | `src/journal_utilities/data/` | `database.py`, `importer.py` | [docs/data.md](docs/data.md) |
| **RAG** | `src/journal_utilities/rag/` | `main.py`, `extractors/` | [docs/rag.md](docs/rag.md) |
| **Export** | `src/journal_utilities/export/` | `exporter.py` | [docs/export.md](docs/export.md) |
| **Render** | `src/journal_utilities/render/` | `renderer.py` | [docs/render.md](docs/render.md) |
| **Interface** | `src/journal_utilities/interface/` | `app.py`, `chat_engine.py` | [docs/web_interface.md](docs/web_interface.md) |
| **Site** | `src/journal_utilities/site/` | `builder.py`, `pages_site.py`, `sitemap.py` | [docs/site.md](docs/site.md) |
| **Ingest** | `src/journal_utilities/ingest/` | `enumerate.py`, `ytdlp.py`, `scaffold.py` | [docs/m3-ingest.md](docs/m3-ingest.md) |

The generated journal boundary is maintained by the scripts in `scripts/`. Use
`enrich_metadata.py` for explicit metadata enrichment, then
`repair_split_transcripts.py`, `generate_journal_indexes.py`, and finally the
read-only `validate_journal.py` gate. The sibling checkout and channel manifest
must be passed explicitly when operating outside the default layout.

## 2. Agent Guidelines

### General Rules

1. **Configuration First**: Never hardcode paths or settings. Use `config.ini` (via `run.py` config loader).
2. **Modular Docs**: If you modify a module (e.g., `rag`), you **MUST** update its corresponding doc file (`docs/rag.md`).
3. **Linting**: Ensure all markdown and python code is lint-free.
4. **Testing**: Run `uv run pytest` before submitting changes.

### Common Tasks

#### Adding a New Dependency

1. Add to `pyproject.toml` under the correct dependency group (e.g., `[project.optional-dependencies]`).
2. Run `uv sync`.
3. Update `AGENTS.md` or the specific module doc if the dependency is significant.

#### Modifying the Database Schema

1. Check `src/journal_utilities/data/database.py`.
2. If adding a new table, document it in `docs/data.md`.
3. Ensure `importer.py` audit trails cover the new data.

#### Improving Prompt Engineering

1. Edit `src/journal_utilities/interface/chat_engine.py`.
2. Test changes with the `gemma3:4b` model (the default).
3. Document prompt changes in `docs/chat_engine.md`.

## 3. Development Workflow

### Environment

We use `uv` for dependency management.

```bash
uv sync --all-extras
```

### Running the App

Always use `run.py` as the entry point.

```bash
uv run python run.py full       # Run full pipeline
uv run python run.py serve      # Start web UI
uv run python run.py journal-check  # Validate sibling journal (read-only)
```

## 4. Documentation Standards

- **Format**: GitHub Flavored Markdown.
- **Diagrams**: Use Mermaid (`mermaid`) for flows and architectures.
- **Linking**: Use relative links for file references.
- **Signposting**: `README.md` is the index; `docs/*.md` are the details.

## Architecture

```text
src/journal_utilities/
├── youtube/                # YouTube API and data handling
│   ├── channel.py          # Channel enumeration (yt-dlp --flat-playlist)
│   ├── playlist.py         # Playlist enumeration and metadata
│   ├── youtube.py          # URL builder helpers
│   └── categorizer.py      # Video categorization by series/type
├── download/               # Download management
│   └── downloader.py       # Download transcripts/audio/video per-video
├── transcribe/             # Transcription engines
│   ├── transcriber.py      # Local Whisper (mlx-whisper)
│   └── transcribe.py       # WhisperX (GPU/CUDA)
├── data/                   # Data storage and database
│   ├── database.py         # Database models and queries
│   └── importer.py         # Session import with audit trail
├── interface/              # Web interface (FastAPI SPA)
│   ├── app.py              # FastAPI server + REST API
│   ├── data_loader.py      # Video manifest from data/output/
│   ├── chat_engine.py      # Ollama RAG chat engine
│   └── static/             # HTML, CSS, JS frontend
├── rag/                    # Entity extraction pipeline
│   ├── main.py             # Pipeline orchestrator
│   ├── extractors/         # Cohere AI extraction
│   ├── graph/              # SurrealDB graph client
│   ├── models/             # Pydantic entity models
│   ├── schemas/            # JSON schemas for extraction
│   └── adapters/           # Entity format conversion
├── render/                 # Content rendering
│   └── renderer.py         # Markdown/HTML rendering
├── export/                 # Transcript export
│   └── exporter.py         # Plaintext, PDF, Markdown, JSON, HTML
├── ingest/                 # Channel enumeration/scaffold ingest helpers
│   ├── enumerate.py        # Channel enumeration helpers
│   ├── ytdlp.py            # yt-dlp invocation helpers
│   ├── scaffold.py         # Course scaffold helpers
│   └── diff.py             # Manifest reconciliation
├── site/                   # Static GitHub Pages generation
│   ├── builder.py          # SPA bundle builder
│   ├── pages_site.py       # Per-item static pages
│   └── sitemap.py          # sitemap.xml/robots.txt
├── llm/                    # LLM tool integration (placeholder)
└── utils/                  # General utilities
```

## Key Entry Points

| Task | Command | Main File |
| :--- | :--- | :--- |
| Show config | `uv run python run.py config` | `run.py` + `config.ini` |
| Export transcripts | `uv run python run.py export` | `export/exporter.py` |
| Download content | `uv run python run.py download` | `downloader.py` |
| Start web interface | `uv run python run.py serve` | `interface/app.py` |
| Run full pipeline | `uv run python run.py full` | `run.py` |
| Run tests | `uv run python run.py test` | pytest |
| Check sibling journal | `uv run python run.py journal-check` | `scripts/validate_journal.py` |
| Enumerate channel | `python scripts/download_channel.py --enumerate-only` | `channel.py` |
| Local Whisper | `python scripts/transcribe_missing.py` | `transcriber.py` |
| Entity extraction | `make extract-entities` | `rag/main.py` |
| Build static site | `uv run python scripts/build_pages_site.py --apply` | `site/builder.py` |

## Configuration

All pipeline options live in `config.ini` (plaintext INI format):

- `[general]` — data directory, log level
- `[download]` — transcript/audio/video flags, cookies, rate limiting
- `[transcribe]` — engine, model, max files
- `[export]` — enabled formats, output directory
- `[interface]` — host, port
- `[database]` — SurrealDB connection

## Testing

- Tests prefer real methods and real fixtures; mocks are reserved for external
  I/O that can't run in CI (live SurrealDB, Cohere API, Ollama, GPU/WhisperX,
  network downloads). See `tests/AGENTS.md`.
- Run: `uv run pytest tests/ -v`
- Coverage: `uv run pytest tests/ -v --cov=src --cov-report=term-missing`

## Environment Variables

Required in `.env` (copy from `.env.example`):

- `HUGGINGFACE_TOKEN` — WhisperX speaker diarization
- `CODA_API_TOKEN` — Coda session data
- `COHERE_API_KEY` — Entity extraction
- `OLLAMA_MODEL` — Chat model (default: `gemma3:4b`)
- `OLLAMA_BASE_URL` — Ollama API URL (default: `http://localhost:11434`)

## Code Patterns

- **Dataclasses & Enums**: Structured results (`DownloadResult`, `TranscriptionResult`, `ExportResult`)
- **Async-first**: Database operations use `asyncio`
- **Pydantic models**: Type-safe entity definitions
- **Structured logging**: `logging.getLogger(__name__)` throughout
- **Skip-existing**: All download/transcription/export functions support `skip_existing=True`
- **Config-driven**: `run.py` reads `config.ini` via `configparser`
- **User-Agent**: All `yt-dlp` calls MUST use a modern browser User-Agent to avoid 403s
- **Cookies**: The downloader runs cookie-free by default. Never write cookies into a
  tracked path and never commit `cookies.txt`; never pass `--cookies-from-browser`
  into a tracked path

## Optional Dependencies

| Group | Install | Purpose |
| :--- | :--- | :--- |
| `transcribe-local` | `uv pip install -e ".[transcribe-local]"` | `mlx-whisper` for Apple Silicon |
| `interface` | `uv pip install -e ".[interface]"` | FastAPI, uvicorn, httpx |
| `export` | `uv pip install -e ".[export]"` | fpdf2 for PDF export |
| `dev` | `uv pip install -e ".[dev]"` | Testing, linting, type checking |
