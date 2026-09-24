# docs — Journal-Utilities

Technical documentation for the Journal-Utilities pipeline (the engine that produces the
[ActiveInferenceJournal](https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal)
data repository). The repo [`../README.md`](../README.md) is the overview; these are the
module- and workflow-level guides.

## Pipeline / module guides

| Doc | Covers |
| --- | --- |
| [`youtube_download.md`](youtube_download.md) | Downloading transcripts/audio/video via `yt-dlp` (`download/downloader.py`). |
| [`transcription.md`](transcription.md) | Local Whisper (`mlx-whisper`) and WhisperX transcription. |
| [`data.md`](data.md) | Data layout, manifests, and the SurrealDB store. |
| [`rag.md`](rag.md) | Entity/relationship extraction (Cohere → SurrealDB graph). |
| [`export.md`](export.md) | Multi-format transcript export (plaintext/PDF/MD/JSON/HTML). |
| [`render.md`](render.md) | Markdown/HTML rendering, course scaffolding. |
| [`web_interface.md`](web_interface.md) | FastAPI SPA for browsing the library. |
| [`chat_engine.md`](chat_engine.md) | Ollama-powered RAG chat over transcripts. |
| [`translation.md`](translation.md) | Hosted OpenRouter subtitle translation (`scripts/translate_subtitles_openrouter.py`). |
| [`configuration.md`](configuration.md) | `config.ini` + `.env` reference. |
| [`youtube.md`](youtube.md) | YouTube integration — enumeration (`youtube/channel.py`), guarded write path, quota rules, OAuth ownership. |
| [`m3-ingest.md`](m3-ingest.md) | Weekly channel enumeration / scaffold / reconciliation (M3). |
| [`privacy.md`](privacy.md) | What the pipeline processes, what it never does, API usage, retention. |

## Journal refactor

| Doc | Covers |
| --- | --- |
| [`JOURNAL_SCHEMA.md`](JOURNAL_SCHEMA.md) | The ActiveInferenceJournal v2 schema, source-namespaced layout, and maintenance gate. |
| [`REFACTOR_READINESS.md`](REFACTOR_READINESS.md) | Coverage, the local-LLM stack, and the refactor/verification process. |

## Collaboration

Journal-Utilities is the **code**; ActiveInferenceJournal is the **content**. The schema
of record is mirrored in both: `docs/JOURNAL_SCHEMA.md` here and `docs/SCHEMA.md` in the
journal. Keep them in sync when the per-item structure changes.

CLI tools (channel download, transcription, journal maintenance) are documented in
[`scripts/README.md`](../scripts/README.md); contribution and security guidance in
[`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`SECURITY.md`](../SECURITY.md).
