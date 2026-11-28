# Agent guide — scripts/

CLI tools over `src/journal_utilities/`. See [`README.md`](README.md) for usage.

## Key scripts
- `download_channel.py` — enumerate (videos+streams+shorts) + download transcripts/audio.
  Runs **cookie-free** when no `cookies.txt` exists; never pass `--cookies-from-browser`
  into a tracked path, never commit `cookies.txt`.
- `transcribe_missing.py` — local Whisper (`mlx-whisper`) for caption-less videos.
- `refactor_journal.py` — build the ActiveInferenceJournal v2 schema (source-namespaced,
  `data/video/activeinferenceinstitute/`); `--build <dir>` stages out-of-place and audits
  for zero data loss before any in-place apply. See [`../docs/reference/JOURNAL_SCHEMA.md`](../docs/reference/JOURNAL_SCHEMA.md).
- `enrich_metadata.py` — preview or explicitly apply Coda/session/manifest enrichment;
  dry-run is the default and journal-owned `sessions[]` are preserved.
- `generate_journal_indexes.py` — derive `INDEX.json` and `INDEX.md` from canonical
  `metadata.json` records.
- `repair_split_transcripts.py` — rebuild complete split-session transcript artifacts;
  `--check` is read-only.
- `validate_journal.py` — run the combined read-only integrity gate before handoff.
- `translate_subtitles_openrouter.py` — translate per-item caption SRTs into 11 languages via the hosted OpenRouter batched engine (idempotent, resumable).

## Conventions
- `PYTHONPATH=src` + the project venv. `timeout` is absent on macOS (use `gtimeout`/none).
- Structured logging via `logging.getLogger(__name__)`; lazy-import heavy deps (whisper).

Parent: [`../README.md`](../README.md) · [`../AGENTS.md`](../AGENTS.md).
