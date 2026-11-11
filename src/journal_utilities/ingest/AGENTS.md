# Agent guide — journal_utilities.ingest

The `journal_utilities.ingest` package. See [`README.md`](README.md) for the module
map and [`../../../docs/m3-ingest.md`](../../../docs/m3-ingest.md) for the workflow.

## Conventions
- Default to dry-run; only write behind the module's explicit opt-in flag.
- Read-only toward YouTube (handoff Rules 1/2): this package never mutates channel
  state and must not grow a write path.
- Prefer the secret-free `ytdlp.py` path; `enumerate.py` is the quota-spending Data
  API alternative and requires `YOUTUBE_API_KEY`.
- Structured logging (`logging.getLogger(__name__)`); lazy-import heavy deps.
- Never overwrite existing journal `metadata.json`; scaffolds are additive only.
- Tests mirror this package under `../../../tests/journal_utilities/ingest/`.

Parent: [`../../../README.md`](../../../README.md) · [`../../../AGENTS.md`](../../../AGENTS.md).
