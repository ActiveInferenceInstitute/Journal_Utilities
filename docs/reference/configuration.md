# Configuration Reference

Journal Utilities is configured via a single `config.ini` file in the project root.
This file controls the pipeline's behavior across download, export, and interface
serving. Secrets and machine-specific values live in `.env` (see
[Environment Variables](#environment-variables) below and `.env.example`).

## File Format

Standard INI format. Boolean values can be `true`/`false`. Empty values use internal
defaults.

## Sections

### `[general]`

Global settings (read by `run.py`).

| Key | Default | Description |
| :--- | :--- | :--- |
| `data_dir` | `data/output` | Base directory for all downloaded and generated files. |
| `log_level` | `INFO` | Verbosity of console output (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

### `[download]`

Controls the download step (`uv run python run.py download`). The standalone
`scripts/download_channel.py` mirrors these as CLI flags.

| Key | Default | Description |
| :--- | :--- | :--- |
| `transcripts` | `true` | Download subtitles (.vtt/.txt). |
| `audio` | `true` | Download audio tracks. |
| `video` | `false` | Download full video files. |
| `resume` | `true` | Skip files that already exist. |
| `max_videos` | `0` | Stop after N videos (0 = unlimited). |
| `delay` | `1` | Seconds to wait between requests (rate limiting). |
| `cookies_from_browser` | | Browser to extract cookies from (`chrome`, `firefox`) to bypass 403s. ⚠ See the cookie-safety note in `CLAUDE.md` — never commit `cookies.txt`. |
| `audio_format` | `mp3` | Format for audio downloads (`mp3`, `wav`, `m4a`). |
| `video_quality` | `best` | Video quality selector (`best`, `720p`, `480p`, `360p`). |
| `transcript_languages` | `en` | Comma-separated list of languages to download (e.g. `en,es`). |

### `[transcribe]`

**Reserved — no current consumer.** The transcription scripts take their options as
CLI flags instead: `scripts/transcribe_missing.py --max-files N` (local mlx-whisper)
and `scripts/transcribe_worklist.py --batch-size N --compute-type float16` (GPU
WhisperX). Engine/model defaults live in code; see `docs/pipeline/transcription.md`.

| Key | Default | Description |
| :--- | :--- | :--- |
| `engine` | `mlx-whisper` | Transcription backend: `mlx-whisper` (Mac) or `whisperx` (GPU). |
| `model` | `mlx-community/whisper-large-v3-turbo` | Model ID (HuggingFace repo or local path). |
| `max_files` | `0` | Limit number of files to transcribe per run. |

### `[export]`

Controls `src/journal_utilities/export/exporter.py` (`run.py export`).

| Key | Default | Description |
| :--- | :--- | :--- |
| `plaintext` | `true` | Generate `.txt` files. |
| `pdf` | `true` | Generate `.pdf` files. |
| `markdown` | `true` | Generate `.md` files with YAML frontmatter. |
| `json` | `true` | Generate `.json` files with metadata. |
| `html` | `true` | Generate standalone `.html` files. |
| `output_dir` | `data/export` | Directory where exported files will be saved. |

### `[interface]`

Controls the Web UI (`uv run python run.py serve`).

| Key | Default | Description |
| :--- | :--- | :--- |
| `host` | `0.0.0.0` | Bind address (0.0.0.0 for all interfaces). |
| `port` | `8000` | Port to listen on. |

### `[database]`

**Informational only — no code reads this section.** The SurrealDB connection is
environment-driven: `journal_utilities.data` reads `DB_URL` / `DB_USER` /
`DB_PASSWORD` / `DB_NAME` / `DB_NAMESPACE`, and `journal_utilities.rag` reads the
`SURREALDB_*` equivalents (see `.env.example`). The values below mirror the common
defaults.

| Key | Default | Description |
| :--- | :--- | :--- |
| `url` | `ws://localhost:8080/rpc` | Database WebSocket URL. |
| `user` | `root` | Username. |
| `password` | `root` | Password. |
| `namespace` | `actinf` | Namespace. |
| `database` | `actinf` | Database name. |

### `[pipeline]`

Controls the default pipeline steps (`uv run python run.py` with no subcommand).

| Key | Default | Description |
| :--- | :--- | :--- |
| `config` | `true` | Show config summary step. |
| `validate` | `true` | Validate data directories and content. |
| `export` | `true` | Export transcripts to configured formats. |
| `test` | `true` | Run the test suite. |
| `serve` | `true` | Start the web interface (final step). |
| `test_strict` | `true` | If `true`, abort the pipeline on test failures; set `false` only for diagnostics. |

## Environment Variables

Secrets and machine-specific values are kept in a `.env` file (copy
`.env.example`, never commit the real `.env`). `run.py` loads it for the CLI; the
modules below read the individual variables.

| Variable | Used By | Purpose |
| :--- | :--- | :--- |
| `HUGGINGFACE_TOKEN` / `HF_TOKEN` | WhisperX (`transcribe_worklist.py`, legacy `transcribe.py`) | Speaker diarization models. |
| `CODA_API_TOKEN` | `make fetch-coda` | Coda session data. |
| `COHERE_API_KEY` | `journal_utilities.rag` | Entity extraction. |
| `COHERE_MODEL` | `journal_utilities.rag` | Cohere model (default `command-a-03-2025`). |
| `OLLAMA_BASE_URL` | chat (`chat_engine.py`) | Ollama API URL (default `http://localhost:11434`). |
| `OLLAMA_MODEL` | chat (`chat_engine.py`) | Chat model (default `gemma3:4b`). |
| `CHAT_MAX_CONTEXT` / `CHAT_MAX_HISTORY` / `CHAT_MAX_SESSIONS` | chat (`chat_engine.py`) | Context size, history length, session cap — see `docs/operations/chat_engine.md`. |
| `DB_URL` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` / `DB_NAMESPACE` | `journal_utilities.data` | SurrealDB connection — see `docs/reference/data.md`. |
| `SURREALDB_URL` / `SURREALDB_USERNAME` / `SURREALDB_PASSWORD` / `SURREALDB_DATABASE` / `SURREALDB_NAMESPACE` | `journal_utilities.rag` | SurrealDB graph connection — see `docs/operations/rag.md`. |
| `PRIVATE_VIDEOS_PATH` | `journal_utilities.youtube` | Where the private-video registry is stored (default: `<repo>/data/private_videos.json`). |
| `PORT` / `HOST` | Web UI (`interface/app.py`) | Web UI host/port overrides (defaults `8000` / `0.0.0.0`). |
