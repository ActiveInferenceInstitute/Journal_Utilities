# Agent guide — docs/

Module and workflow guides for Journal-Utilities. Start at [`README.md`](README.md).

## For agents
- Hand-written docs (not generated). Keep accurate to the code in `../src/journal_utilities/`
  and `../scripts/`.
- Do **not** hardcode counts (video/item totals) — they drift; cite `data/output/channel_videos.json`
  or the journal `INDEX.json` as the live source.
- The journal **schema of record** is [`JOURNAL_SCHEMA.md`](JOURNAL_SCHEMA.md); mirror any
  change into the journal repo's `docs/SCHEMA.md`.
- Keep [`documentation-index.md`](documentation-index.md) complete: every tracked
  `docs/*.md` is listed there, and every top-level guide is linked from `README.md`.
  `uv run python run.py gate docs` enforces both.
- Never hand-edit measured numbers (test counts, coverage, arm wall time). They live
  in [`_generated/gate-arms.md`](_generated/gate-arms.md), written by
  `uv run python run.py gate report`.

## Parent
Repo root: [`../README.md`](../README.md) · [`../AGENTS.md`](../AGENTS.md) · [`../CLAUDE.md`](../CLAUDE.md).
