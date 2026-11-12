# Documentation index

Flat index of the long-lived documentation in this repository. The hub is
[`README.md`](README.md); this file is the complete list, and the `docs` gate arm
(`scripts/check_docs_links.py`) fails when a tracked `docs/*.md` file is missing
from it.

## Entry points

| Document | Role |
| --- | --- |
| [`../README.md`](../README.md) | Repository overview and quick start |
| [`../AGENTS.md`](../AGENTS.md) | System reference and agent rules |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Dev setup, gate workflow, PR process |
| [`README.md`](README.md) | Documentation hub for `docs/` |
| [`AGENTS.md`](AGENTS.md) | Rules for editing this tree |
| [`RUN_GUIDE.md`](RUN_GUIDE.md) | The one gate/CI entry point (`run.py gate`) |

## Pipeline and module guides

- [`youtube.md`](youtube.md) — enumeration (`youtube/channel.py`), guarded write path, quota, OAuth ownership
- [`youtube_download.md`](youtube_download.md) — `yt-dlp` download engine (`download/downloader.py`)
- [`transcription.md`](transcription.md) — local Whisper (`mlx-whisper`) and WhisperX
- [`translation.md`](translation.md) — hosted OpenRouter subtitle translation
- [`data.md`](data.md) — data layout, manifests, SurrealDB store
- [`rag.md`](rag.md) — Cohere extraction into the SurrealDB graph
- [`export.md`](export.md) — plaintext/PDF/Markdown/JSON/HTML export
- [`render.md`](render.md) — Markdown/HTML rendering and course scaffolding
- [`site.md`](site.md) — static GitHub Pages bundle, URL contract, sitemap
- [`web_interface.md`](web_interface.md) — FastAPI SPA for the library
- [`chat_engine.md`](chat_engine.md) — Ollama-powered RAG chat
- [`m3-ingest.md`](m3-ingest.md) — weekly enumeration / scaffold / reconciliation
- [`configuration.md`](configuration.md) — `config.ini` and `.env` reference
- [`privacy.md`](privacy.md) — processing boundaries and API usage

## Journal refactor

- [`JOURNAL_SCHEMA.md`](JOURNAL_SCHEMA.md) — ActiveInferenceJournal v2 schema and maintenance gate
- [`REFACTOR_READINESS.md`](REFACTOR_READINESS.md) — coverage, local-LLM stack, verification process

## Gates, CI, and generated evidence

- [`RUN_GUIDE.md`](RUN_GUIDE.md) — arms, environment, and how CI calls them
- [`_generated/gate-arms.md`](_generated/gate-arms.md) — measured per-arm wall time (generated)
- [`../.github/README.md`](../.github/README.md) — workflows, Dependabot, local checks
- [`../.github/GNN.md`](../.github/GNN.md) — what the pinned GNN conformance job parses
- [`../tests/README.md`](../tests/README.md) — test suite layout and categories
- [`../scripts/README.md`](../scripts/README.md) — every CLI script

## Generated documents

These files are written by a script; do not hand-edit them.

| Document | Producer |
| --- | --- |
| [`_generated/gate-arms.md`](_generated/gate-arms.md) | `uv run python run.py gate report` |

## Policy

- [`../SECURITY.md`](../SECURITY.md) — security and cookie-handling policy
- [`../CITATION.cff`](../CITATION.cff) — citation metadata
- [`../TODO.md`](../TODO.md) — backlog and pass records
