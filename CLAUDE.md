# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working with this repository.

## Project Overview

Journal-Utilities is a Python processing pipeline for Active Inference Institute YouTube content. It supports six workflows:

1. **YouTube Channel Download** — Enumerate and download transcripts, audio, and video via `yt-dlp`
2. **Local Whisper Transcription** — Apple Silicon–optimized transcription via `mlx-whisper`
3. **WhisperX Transcription** — GPU-based transcription with speaker diarization (CUDA)
4. **Entity Extraction (RAG)** — Cohere AI entity/relationship extraction into SurrealDB graph
5. **Export** — Multi-format transcript export (plaintext, PDF, Markdown, JSON, HTML)
6. **Web Interface** — FastAPI SPA for browsing the video library with Ollama-powered RAG chat

## Journal v2 refactor

`scripts/refactor_journal.py` transforms the sibling `ActiveInferenceJournal` repo into
the uniform v2 schema — see [`docs/JOURNAL_SCHEMA.md`](docs/JOURNAL_SCHEMA.md) and
[`docs/REFACTOR_READINESS.md`](docs/REFACTOR_READINESS.md). Run `--build <dir>` for an
out-of-place staging tree (audit/dry-run); content-based item detection + a passthrough
pass guarantee zero data loss (reconcile total source files == captured + intentional
drops before any in-place apply). Audio is split to the journal's `audio` branch
(`<item>/audio/<name>.64k.m4a`); `main` carries no audio.

## Operational notes (important)

- **Cookie safety:** the downloader runs **cookie-free** when no `cookies.txt` exists. A
  leaked `cookies.txt` once exposed live Google session cookies in this public repo —
  it is now gitignored and purged from history. **Never use `--cookies-from-browser`**
  into a tracked path; never commit `cookies.txt`.
- **Enumeration:** `channel.py` unions the `/videos` + `/streams` + `/shorts` tabs (the
  `UU...` uploads playlist truncates at ~100). The saved channel manifest is the live
  count; do not hardcode corpus totals in documentation.
- `timeout` is not on macOS (use `gtimeout` or none). For transcript-only work, a
  lightweight venv (`yt-dlp` + `youtube-transcript-api`) is enough — `whisperx` is only
  for diarization.

## Development Commands

### Environment Setup

```bash
uv sync --all-extras
```

### Running Tests

```bash
uv run pytest tests/ -v
uv run pytest tests/journal_utilities/ -v       # YouTube download + transcription
uv run pytest tests/journal_utilities/rag/ -v   # Entity extraction (RAG)
```

### Pipeline Runner (run.py)

```bash
uv run python run.py --help           # Show all commands
uv run python run.py config           # Display current configuration
uv run python run.py export           # Export transcripts (formats from config.ini)
uv run python run.py download         # Download from YouTube (options from config.ini)
uv run python run.py serve            # Start web interface
uv run python run.py test             # Run test suite
uv run python run.py full             # Run full pipeline (download → export)
uv run python run.py journal-check    # Validate sibling ActiveInferenceJournal (read-only)
```

### YouTube Channel Download

```bash
python scripts/download_channel.py --transcripts --audio --resume
```

(The downloader runs cookie-free; see the cookie-safety note above.)

### Local Whisper Transcription

```bash
python scripts/transcribe_missing.py --dry-run
python scripts/transcribe_missing.py
python scripts/transcribe_missing.py --max-files 5
```

### WhisperX Transcription (GPU)

```bash
uv run python scripts/transcribe_worklist.py           # plan (dry run)
uv run python scripts/transcribe_worklist.py --run     # transcribe + diarize
```

### Web Interface

```bash
uv pip install -e ".[interface]"
uv run python -m journal_utilities.interface.app   # → http://localhost:8000
```

### Database

```bash
make db-start
surreal sql --endpoint http://localhost:8080 --username root --password root --namespace actinf --database actinf
```

## Architecture

### Core Modules (`src/journal_utilities/`)

| Module | Purpose |
|--------|---------|
| `youtube/channel.py` | Channel enumeration via `yt-dlp --flat-playlist` |
| `download/downloader.py` | Download transcripts, audio, video |
| `transcribe/transcriber.py` | Local Whisper transcription using `mlx-whisper` (Apple Silicon) |
| `youtube/playlist.py` | Playlist enumeration and metadata |
| `render/renderer.py` | Markdown/HTML rendering of transcripts |
| `youtube/youtube.py` | URL builder helpers |
| `youtube/categorizer.py` | Video categorization by series/type |
| `data/database.py` | Database models and queries |
| `data/importer.py` | Session import with audit trail |
| `transcribe/transcribe.py` | WhisperX transcription with diarization (GPU/CUDA) |
| `interface/app.py` | FastAPI web server, REST API routes |
| `interface/data_loader.py` | Video manifest builder from `data/output/` |
| `interface/chat_engine.py` | Ollama RAG chat engine with transcript context |
| `export/exporter.py` | Multi-format transcript export |
| `site/builder.py` | Static GitHub Pages bundle builder |
| `ingest/enumerate.py` | Channel enumeration/scaffold ingest helpers |

### Entity Extraction (`src/journal_utilities/rag/`)

| Module | Purpose |
|--------|---------|
| `main.py` | Pipeline orchestrator |
| `extractors/cohere_extractor.py` | Cohere AI entity extraction |
| `graph/surreal_client.py` | SurrealDB graph client |
| `models/entities.py` | Pydantic entity/relationship models |
| `adapters/entity_adapter.py` | Entity format conversion |

### Top-Level Files

| File | Purpose |
|------|---------|
| `run.py` | Python CLI runner (argparse + configparser) |
| `config.ini` | Pipeline configuration (all options in INI format) |

### Data Flow

```
YouTube Channel → yt-dlp enumeration → video manifest (JSON)
                → yt-dlp download → transcripts (.txt), audio (.mp3), video (.mp4)
                → mlx-whisper → transcripts for missing videos
                → WhisperX → diarized transcripts → SurrealDB
                → Cohere AI → entities + relationships → SurrealDB graph
                → export → plaintext/PDF/MD/JSON/HTML
```

## Key Configuration

### config.ini

All pipeline options in a single plaintext file:

| Section | Keys |
|---------|------|
| `[general]` | `data_dir`, `log_level` |
| `[download]` | `transcripts`, `audio`, `video`, `resume`, `max_videos`, `delay`, `cookies_from_browser`, `audio_format`, `video_quality`, `transcript_languages` |
| `[transcribe]` | `engine`, `model`, `max_files` |
| `[export]` | `plaintext`, `pdf`, `markdown`, `json`, `html`, `output_dir` |
| `[interface]` | `host`, `port` |
| `[database]` | `url`, `user`, `password`, `namespace`, `database` |
| `[pipeline]` | `config`, `validate`, `export`, `test`, `serve`, `test_strict` |

### Environment Variables (`.env`)

| Variable | Required For | Purpose |
|----------|-------------|---------|
| `HUGGINGFACE_TOKEN` | WhisperX | Speaker diarization models |
| `CODA_API_TOKEN` | Import | Coda session data |
| `COHERE_API_KEY` | RAG | Entity extraction |
| `OLLAMA_MODEL` | Chat | Chat model (default `gemma3:4b`) |
| `OLLAMA_BASE_URL` | Chat | Ollama API URL (default `http://localhost:11434`) |
| `DB_URL` | Database | SurrealDB connection (also `DB_USER`, `DB_PASSWORD`, `DB_NAMESPACE`, `DB_NAME`) |

## Code Patterns

- **Dataclasses & Enums**: `DownloadResult`, `TranscriptionResult`, `ExportResult`
- **Lazy imports**: `mlx-whisper` imported lazily to avoid hard dependency
- **Skip-existing**: All functions default to `skip_existing=True`
- **Async-first**: Database operations use `asyncio`
- **Structured logging**: `logging.getLogger(__name__)`
- **Config-driven**: `run.py` reads `config.ini` via Python `configparser`

## Optional Dependencies

| Group | Install | Purpose |
|-------|---------|---------|
| `transcribe` | `uv pip install -e ".[transcribe]"` | WhisperX (torch + diarization) |
| `transcribe-local` | `uv pip install -e ".[transcribe-local]"` | `mlx-whisper` |
| `rag` | `uv pip install -e ".[rag]"` | Cohere, SurrealDB, structlog |
| `interface` | `uv pip install -e ".[interface]"` | FastAPI, uvicorn, httpx |
| `export` | `uv pip install -e ".[export]"` | fpdf2 for PDF export |
| `dev` | `uv sync --group dev` | pytest, ruff, mypy |
