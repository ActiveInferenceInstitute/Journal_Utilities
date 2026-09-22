# Review Log — 2026-08-02 (mega-deep docs pass)

**Repo:** Journal-Utilities (`ActiveInferenceInstitute/Journal_Utilities`)
**Branch:** `main` → `origin/main` (default branch)
**HEAD at start:** `6a4185d` — "fix(journal-utils): harden pipeline, close 11 review majors, green gates"
**Review type:** Documentation-focused mega-deep review + implementation pass.

---

## Phase 0 — Preflight

- `git fetch origin` + `git pull --ff-only` → already up to date on `main`.
- Inventory: `README.md`, `AGENTS.md`, `CLAUDE.md`, `LICENSE`, `TODO.md`, `Makefile`,
  `config.ini`, `.env.example`, `.github/workflows/test.yml`, `pyproject.toml`,
  `docs/` (14 tracked markdown files: README, AGENTS, JOURNAL_SCHEMA, REFACTOR_READINESS,
  and 10 module guides), `scripts/README.md` + `scripts/AGENTS.md`, per-module
  `README.md`/`AGENTS.md` under `src/journal_utilities/*`, `tests/README.md` +
  `tests/AGENTS.md`, `data/README.md`, `.aii/config.yaml` (InstituteOS sidecar).
- **Pre-existing dirty state (left untouched, NOT committed):**
  - `README.md` modified: one line adding a `docs/translation.md` row to the docs table.
  - Untracked: `docs/translation.md`, `scripts/translate_subtitles.py`,
    `scripts/translate_openrouter.py`, `scripts/translate_subtitles_openrouter.py`,
    `scripts/translate_tb_watchdog.sh`, `tests/journal_utilities/test_translate_subtitles.py`,
    `insights_findings.md`, `.translate_tb_watchdog.lock`.
  - These belong to an in-progress subtitle-translation feature; excluded from this pass.
    The README translation row is therefore excluded too (see TODO: deferred).

## Phase 1 — Mega-deep docs review (findings)

Methods: full read of every tracked markdown doc; code verification of every
quantitative/environmental/CLI claim against `src/`, `scripts/`, `run.py`, `Makefile`,
`config.ini`, `.env.example`, `pyproject.toml`, CI; automated whole-repo link + anchor
audit (all tracked `.md` files; 5 findings, 3 of which are sibling-repo refs or the
excluded WIP row); live `uv run pytest tests/` run for real test counts.

### Verified accurate (no change needed)
- `docs/web_interface.md` endpoint list matches `app.py` routes exactly (incl.
  `create_app` factory and `GET /`).
- `docs/chat_engine.md` env defaults (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `CHAT_MAX_CONTEXT=8000`,
  `CHAT_MAX_HISTORY=10`) match `chat_engine.py`.
- `docs/data.md` `DB_*` env vars match `database.py`; audit-trail ops match `importer.py`.
- `docs/transcription.md` WhisperX details (`large-v3`, `BATCH_SIZE=48`,
  `COMPUTE_TYPE=float16`, `HF_TOKEN`) match `transcribe.py`.
- `docs/export.md` formats/writers match `exporter.py` (`ExportFormat` enum).
- `docs/configuration.md` `[download]`/`[export]`/`[interface]`/`[general]`/`[pipeline]`
  keys match `config.ini` and `run.py` consumers.
- Root README pipeline order (`config → validate → export → test → serve`) matches
  `run.py cmd_default`; `full` = download → export matches `cmd_full`.
- `docs/JOURNAL_SCHEMA.md` matches `scripts/refactor_journal.py`/`validate_journal.py`
  behavior (verified via TODO.md M-series notes + script docstrings).

### Findings by severity
See `TODO.md` (scoped Minor / Medium / Major) for the full list with file paths and
completion status. Summary:
- **Minor (13):** stale `docs/youtube.md` enumeration claim (UU playlist vs
  tabs-union); `make transcribe` described as WhisperX but runs local mlx-whisper
  (docs/transcription.md, src AGENTS.md, Makefile help); chat chunk size 2000→~2600
  chars; `COHERE_MODEL` stale example; CLAUDE.md stale `run.sh` row + unused
  `API_KEY` row + missing `[download]` keys; journalrag naming drift in two test
  docstrings; misplaced `[pipeline]` heading in configuration.md; stale test counts
  in tests/README.md + tests/AGENTS.md; TODO.md stale backticked paths;
  JOURNAL_SCHEMA `assets/csv/` missing from tree; `data/README.md` stale layout
  (nonexistent `database/` dir, wrong artifact naming); `.vscode/settings.json`
  disables pytest.
- **Medium (6):** scripts/README.md missing 7 script guides; Makefile
  `extract-entities` runs nonexistent `journalrag.main` module; Makefile `db-start`
  hardcodes internal `/mnt/md0/...` path; `.env.example` internal paths + unused
  vars (`API_KEY`, `JOURNAL_REPO_DIR`, `YOUTUBE_CHANNEL_ID`); README static
  shields → real CI badge; configuration.md `[transcribe]`/`[database]` "Controls…"
  claims have no consumer (env-driven).
- **Major (2):** no `CONTRIBUTING.md` / `SECURITY.md` / `CITATION.cff` for a public
  repo (add concise, grounded versions + README links); live test-count refresh.

### Deferred / not done (with reasons)
- `.github/workflows/test.yml` duplicate "Lint the journal integrity gate" step
  (already covered by the repo-wide ruff check) — left untouched: CI stability,
  zero-risk policy, not docs.
- README `docs/translation.md` row (part of excluded WIP feature) — left as-is.
- Heavy GPU/WhisperX, SurrealDB, Cohere, and network-dependent flows — not run;
  docs claims verified by code reading instead (noted in TODO.md "Open" list).
- Full `uv run pytest` was run once for live counts; no code was modified by this pass.

## Phase 4 — Final state

Pushed to `origin/main` on 2026-08-02. 10 commits, 25 files changed:

| Commit | Summary |
| :--- | :--- |
| `b7255a0` | docs: align module guides with current code behavior |
| `60583a4` | docs(scripts): document all CLI tools incl. journal v2 transcription workflow |
| `06a1356` | fix(make): portable db-start, working extract-entities, lint parity with CI |
| `f098ec8` | fix(meta): align project license metadata with LICENSE (CC0-1.0) |
| `b6503dc` | docs(claude): drop removed run.sh, fix env/config tables, cookie-safe examples |
| `a24a223` | chore(env): de-private .env.example, drop unused vars |
| `d7d8974` | docs(config): accurate section consumers + full env reference; docs(data): real output layout |
| `a3b543a` | docs(tests): refresh live counts; fix journalrag naming drift in docstrings |
| `bf3449f` | docs: add CONTRIBUTING, SECURITY, CITATION for the public repo |
| *(this commit)* | docs: record 2026-08-02 docs pass — scoped TODO with results, review log |

Verification: `uv run pytest tests/` = **475 passed, 3 skipped, 2 warnings (~102s)** —
no code changed by this pass, so the suite was untouched except the 3 docstring
one-liners; `uv run ruff check src/ tests/ scripts/` = clean on the tracked tree
(34 errors exist only in the untracked WIP translation scripts, excluded from this
pass); whole-repo markdown link audit clean for tracked files (remaining flags are
the excluded WIP `docs/translation.md` row and the sibling-repo `docs/SCHEMA.md`
refs).

Open / deferred items and notes for the next reviewer: see `TODO.md`.

## Phase 5 — Follow-up pass (deferred items landed)

After the main pass, the user asked to proceed with the remaining open items.
Landed (2 commits, 10 files):

| Commit | Summary |
| :--- | :--- |
| `177d2cf` | feat(translate): land subtitle translation pipeline (local Ollama + hosted OpenRouter) |
| `e0e0dd8` | ci: drop duplicate lint step (covered by the repo-wide ruff check) |

What happened:

- **Translation feature landed** — the previously-untracked WIP
  (`scripts/translate_subtitles.py`, `scripts/translate_subtitles_openrouter.py`,
  `scripts/translate_tb_watchdog.sh`, two unit-test files, `docs/translation.md`,
  the README docs-table row, and the `.translate_tb_watchdog.lock*` gitignore
  pattern) is now committed. The duplicate earlier OpenRouter variant
  `scripts/translate_openrouter.py` was consolidated into
  `translate_subtitles_openrouter.py` (placeholder-hash skip, batch echo guard,
  per-cue fallback ported; 34 ruff errors fixed; black-formatted; API-key
  fallback switched from `~/.hermes/.env` to the repo's gitignored `.env`).
  A privacy sweep confirmed no personal paths/tool names remain in any committed
  file. The superseded script was preserved at `/tmp/translate_openrouter.py.superseded`.
- **CI cleanup** — removed the redundant "Lint the journal integrity gate" step.
- **Still open (genuinely cannot run here)** — WhisperX/GPU, live SurrealDB,
  live Cohere, YouTube network flows. A live OpenRouter translation run was
  observed against the sibling journal during the pass; left untouched (its CLI
  contract is unchanged by the consolidation).
- **`insights_findings.md`** — kept untracked per its own "Do not commit until
  the user asks" note.
- Verification: `uv run pytest tests/` = **479 passed, 3 skipped, 2 warnings
  (~80s)**; `ruff check` clean on all touched files; watchdog `bash -n` OK;
  OpenRouter script pure-logic smoke + 4 new unit tests pass.
