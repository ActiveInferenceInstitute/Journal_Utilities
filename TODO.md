# Journal-Utilities — Backlog

**Status:** Maintained
**Owner:** Active Inference Institute / Journal-Utilities maintainers
**Last reviewed:** 2026-08-02 (mega-deep documentation pass — full docs review, scoped
findings below, all implemented and pushed; see `REVIEW_LOG_2026-08-02.md`)

---

## Scoped this pass — 2026-08-02 docs mega-deep review

Severity definitions:
- **Minor** = typo, broken link, formatting, small inaccurate claim.
- **Medium** = stale section rewrite, doc restructure, added missing guide, config fix
  that makes a documented command actually work.
- **Major** = new documentation system / high-value missing docs for a public repo.

### Major

- **MA1 — Missing public-repo governance docs** — `CONTRIBUTING.md`, `SECURITY.md`,
  `CITATION.cff` do not exist for this public org repo; add concise versions grounded
  in the actual repo (dev setup, gates, cookie policy, authors from `pyproject.toml`)
  and link them from `README.md`. ✓ `docs: add CONTRIBUTING, SECURITY, CITATION for public repo`
  (commit `bf3449f`)

- **MA2 — Live test-count refresh** — `tests/README.md` ("466 passed / 3 skipped") and
  `tests/AGENTS.md` ("~466") drifted from the 2026-08-01 pass's 471; refresh from a live
  `uv run pytest tests/` run (kept a snapshot, not a hardcoded CI promise). ✓ `docs: refresh live test counts`
  (commit `a3b543a`)

### Medium

- **ME1 — `scripts/README.md` missing guides for 7 scripts** — add sections for
  `speaker_cues.py`, `apply_speaker_names.py`, `transcribe_worklist.py`,
  `transcription_status.py`, `fetch_chapters.py`, `recover_whisperx.py`,
  `refactor_journal.py` (cross-link `docs/JOURNAL_SCHEMA.md`); it currently documents
  only 6 of 13 scripts. ✓ `docs(scripts): document all CLI tools` (commit `60583a4`)

- **ME2 — `make extract-entities` runs a nonexistent module** — `Makefile` target runs
  `uv run python -m journalrag.main`; no `journalrag` package exists (it is
  `journal_utilities.rag.main`). `docs/rag.md` tells users to run `make extract-entities`.
  Fix the target so the documented command works. ✓ `fix(make): extract-entities -> journal_utilities.rag.main`
  (commit `06a1356`)

- **ME3 — `make db-start` hardcodes an internal machine path** — `rocksdb:///mnt/md0/projects/Journal-Utilities/data/database`
  is a private absolute path and broken on every other machine; use the repo-relative
  `rocksdb://./data/database` (matches `data/README.md`). ✓ `fix(make): portable db-start path`
  (commit `06a1356`)

- **ME4 — `.env.example` leaks internal paths and lists unused vars** — `WAV_DIRECTORY` /
  `OUTPUT_DIR` contain `/mnt/docs/…` and `/mnt/md0/…` (legacy WhisperX-only, kept with
  neutral placeholders); remove `API_KEY` (YouTube Data API v3 — module deliberately
  avoids it), `JOURNAL_REPO_DIR`, `YOUTUBE_CHANNEL_ID` (no code consumer). ✓ `chore(env): de-private .env.example`
  (commit `a24a223`)

- **ME5 — README uses static placeholder shields for tests/coverage** — replace the
  fake `tests-pytest` / `coverage-pytest` shields.io badges with the real GitHub Actions
  CI badge for the public workflow. ✓ `docs(readme): real CI badge` (commit `bf3449f`)

- **ME6 — `docs/configuration.md` claims `[transcribe]`/`[database]` control behavior,
  but nothing consumes them** — `[download]`, `[export]`, `[interface]`, `[general]`,
  `[pipeline]` are read by `run.py`; `[transcribe]` and `[database]` are not read by any
  code (env vars `HF_TOKEN`/`DB_*` drive those). Document this accurately, move the
  misplaced `[pipeline]` section out of "Environment Variables", and add the missing env
  rows (`CODA_API_TOKEN`, `CHAT_MAX_*`, `PRIVATE_VIDEOS_PATH`). ✓ `docs(config): accurate section consumers + env reference`
  (commit `d7d8974`)

### Minor

- **MI1 — `docs/youtube.md` stale enumeration method** — claims the `UU…` uploads
  playlist "contains every public video"; `channel.py` unions the `/videos` +
  `/streams` + `/shorts` tabs (the `UU…` form truncates at ~100). Also add `description`
  / `url` to the documented `VideoInfo` fields. ✓ `docs(youtube): tabs-union enumeration`
  (commit `b7255a0`)

- **MI2 — `make transcribe` described as WhisperX everywhere, but runs local
  mlx-whisper** — `Makefile` `transcribe:` runs `scripts/transcribe_missing.py`.
  Fix in `docs/transcription.md` (GPU section), `src/journal_utilities/AGENTS.md`
  ("Legacy Operations" table), and the Makefile help text. ✓ `docs(transcribe): make transcribe is local mlx-whisper`
  (commit `60583a4`)

- **MI3 — `docs/chat_engine.md` chunk-size and missing env row** — context chunks are
  `MAX_CONTEXT_CHARS // 3` ≈ 2600 chars (not "approx 2000"); add undocumented
  `CHAT_MAX_SESSIONS` (200). ✓ `docs(chat): exact chunk size + CHAT_MAX_SESSIONS`
  (commit `b7255a0`)

- **MI4 — `docs/rag.md` stale model example** — `COHERE_MODEL` default is
  `command-a-03-2025` (`rag/settings.py`, `.env.example`), doc says `command-r-plus`.
  ✓ `docs(rag): current COHERE_MODEL default` (commit `b7255a0`)

- **MI5 — `CLAUDE.md` stale/incorrect rows** — `run.sh` "legacy, still functional" (file
  was removed from the repo), `API_KEY` env row (unused; module avoids the Data API),
  and `[download]` config keys missing `audio_format`, `video_quality`,
  `transcript_languages`. ✓ `docs(claude): drop removed run.sh, fix env/config tables`
  (commit `b6503dc`)

- **MI6 — test-docstring package-name drift** — `tests/journal_utilities/rag/conftest.py`
  and `tests/journal_utilities/rag/unit/test_pipeline.py` reference the old
  `journalrag` package / `tests/journalrag/` path; point at `journal_utilities` and
  `tests/journal_utilities/rag/`. ✓ `chore(tests): fix journalrag naming drift in docstrings`
  (commit `a3b543a`)

- **MI7 — `docs/configuration.md` misplaced `[pipeline]` heading** — `### [pipeline]`
  sits inside "## Environment Variables"; move to the sections list. (Fold into ME6.)

- **MI8 — TODO.md historical stale backticked paths** — the historical section's
  bare test paths (tests/test_downloader.py, tests/test_audit_functions.py) →
  actual tests/journal_utilities/…. (Fixed in this rewrite; see historical
  section below.)

- **MI9 — `docs/JOURNAL_SCHEMA.md` provenance table cites `assets/csv/` but the
  per-item tree omits it** — add `csv/` to the assets listing. ✓ `docs(journal-schema): assets/csv in tree`
  (commit `b7255a0`)

- **MI10 — `data/README.md` stale layout** — documents a `database/` dir that does not
  exist in the repo and `[session_name]_simplified.json` naming; actual output is
  `{video_id}.json` / `{video_id}.simple.json` / `{video_id}.simple.txt` (+
  `youtube_`-prefixed variants from the WhisperX pipeline). ✓ `docs(data): real output layout`
  (commit `d7d8974`)

- **MI11 — `.vscode/settings.json` disables pytest** — `python.testing.pytestEnabled:
  false` contradicts the repo's pytest workflow; enable pytest and drop the unittest
  config. ✓ `chore(vscode): enable pytest for the repo workflow` (commit `06a1356`)

- **MI12 — `Makefile` help + `make lint` mismatch with CI** — `make lint` checks only
  `src/ tests/` while CI checks `src/ tests/ scripts/`; align so `make lint` reproduces
  the CI gate. ✓ `fix(make): lint covers scripts/ like CI` (commit `06a1356`)

---

## Completed / Closed

### Historical — 2026-08-01 pass (deepest hostile red-team review)

Everything below was implemented and verified in the 2026-08-01 pass. Final gates:
`uv run pytest tests/` = **471 passed, 3 API-gated skips, 2 warnings (~100s)**;
`uv run ruff check src/ tests/ scripts/` = **All checks passed**;
`uv run mypy src` = **Success: no issues in 41 files**; CI golded gate
`scripts/validate_journal.py` = **All checks passed**. No further action required.

> Historical note: the earlier "Major — Scoped (deferred)" list from that pass is now fully
> resolved. All items below were previously scoped; each has since been **implemented** in
> source + tests + docs and verified green. Nothing major remains open from that pass.

#### MAJORS — implemented in the 2026-08-01 pass (M1–M11)

**M1 — yt-dlp transcript strategy dead path — `download/downloader.py` + `tests/journal_utilities/test_downloader.py`**
`_convert_vtt_to_text(best_file, final_path)` (was a one-arg `TypeError` swallowed at runtime, always
falling back to the API). Added `_pick_transcript_vtt` (manual-over-auto, deterministic) and a no-mock
regression test asserting the yt-dlp `SUCCESS` path converts a real VTT → `.txt`.

**M2 — lint/type gates green + CI enforcement — repo-wide (`src/`, `tests/`, `scripts/`, `pyproject.toml`, `.github/workflows/test.yml`)**
Auto-fixed 399 mechanical ruff issues; fixed the substantive remaining rules (F401/F841/B904/E702/N806/
E402/UP031 + script + src annotations). `make lint` (`ruff check src/ tests/`) and `ruff check scripts/`
now pass. mypy strict reduced 91→0: parametrized/typed fixes across the `data/`/`youtube/`/`rag/`/
`download/`/`export` modules, plus documented mypy config (third-party SDK
stub noise disabled; legacy untyped GPU/Cohere modules scoped via per-module ignore; bare-generic
relaxation). CI now runs `ruff check src/ tests/ scripts/` + `mypy src` in addition to the existing gate.
(A `ruff format --check` CI step was considered and dropped: the tree is black-formatted, so a ruff-format
gate would force a 50-file style-only diff against the repo's established `black` convention.)

**M3 — SurrealQL injection via f-string interpolation — `data/database.py`, `youtube/youtube.py`, `transcribe/transcribe.py`, `scripts/fix_scheduled_dates.py`**
All dynamic values parameterized through `query(sql, params)` (`WHERE import_run_id = $id`,
`UPDATE $id …`, `LIMIT $limit`, youtube metadata `UPDATE $id MERGE {…}`); invalid backslash "escaping"
removed.

**M4 — `rollback_import` cross-run delete — `data/database.py` + `tests/journal_utilities/test_audit_functions.py`**
Rollback now deletes the **exact** record id created during that run (from `import_audit.result_data`),
never re-matching by `session_name`; audit update parameterized (`$rid`/`$ts`). Test updated to the new
contract and asserts the delete/update bind params.

**M5 — transient error permanently marked a video private — `youtube/youtube.py`**
`insert_metadata_youtube_api` now only calls `mark_video_private` on definitive 403/404/
"not found"/"unauthorized"; transient failures log + skip instead of silently dropping the video forever.

**M6 — runtime state written into the source tree — `youtube/youtube.py`**
Private-video registry moved out of the package dir via `_private_videos_path()`: honors
`PRIVATE_VIDEOS_PATH`, otherwise resolves under `<repo>/data/`. Env-configurable and non-editable-install safe.

**M7 — library module global side effects — `transcribe/transcribe.py`**
Removed import-time `load_dotenv('../.env')` + root-`logging.basicConfig`; added
`logger = logging.getLogger(__name__)` (%-style); `.env` loaded only in `__main__`.

**M8 — rows without a YouTube URL silently dropped — `data/importer.py`**
Empty-`YouTube` rows now each write a `parse_youtube_id`/`skipped` `import_audit` record and are counted
in `stats["skipped"]` — every row is accounted for (no invisible provenance break).

**M9 — DOM / markup XSS in the SPA — `interface/static/app.js`**
`renderMarkdown()` now HTML-escapes as its first step (assistant/streamed output can no longer execute).
`video_id` sanitized through a new `safeVideoId()` (`^[A-Za-z0-9_-]{11}$`) at all four interpolation
sites (card onclick/data-id, youtube embed src, `askAboutVideo`, chat context tags). Replaced the
no-op `patch(ChatEngine)` test with a real behavioral test + a 413 oversized-message test.

**M10 — cross-transcript entity merging in the graph — `rag/adapters/entity_adapter.py` + `rag/graph/surreal_client.py`**
`convert_extracted_entities` stamps `metadata["source"]` (from `core.source`) onto every entity;
`SurrealDBClient.create_entity` scopes the merge (SELECT/create) by source when present — generic names
like "Insight 1" no longer merge across videos.

**M11 — `refactor_journal.py --apply` no-op stub — `scripts/refactor_journal.py`**
`--apply` now refuses (exit 1, clear message) pointing at the safe out-of-place `--build <dir>` +
`validate_journal.py` workflow; the misleading docstring was corrected. No more silent false-success.

#### Deferred backlog from that pass — now all implemented (previously MINOR/MEDIUM)

- `/api/videos?q=` search mode now honors `offset`/`limit` and reports the **true** result total
  (`SearchIndex.search(limit=None)`; `Interface app.py` returns real `total`).
- `fix_scheduled_dates.py`: `.env` load made CWD-independent; `UPDATE {id}` parameterized to `UPDATE $id`.
- `apply_speaker_names.py` / `patch_whisperx.py` / `recover_whisperx.py` annotations + cleanups.
- `transcriber.find_missing_transcripts`: single-pass count (minor double-iteration removed).
- `render/renderer.py`: `course.json` `last_updated` only bumps when a module was actually created
  (idempotent scaffolding).
- `transcribe/transcribe.py`: blocking WhisperX run moved onto `asyncio.to_thread`.
- RAG: `settings.py` secrets optional at import (no import crash); transcript `date` derived
  deterministically from the filename (`_date_from_filename`) instead of `datetime.now()`.

#### Earlier same-day pass — implemented (Medium/Minor)

**Download/source:** yt-dlp UA centralized on every path; `download_audio`/`download_video` no longer
report false SUCCESS on 0-byte/missing artifacts; `channel.py`/`playlist.py` UA; `playlist.py`
`TimeoutExpired` handled; `transcribe.py` `download_audio` UA + timeout.

**Interface/chat:** `/api/audio` Range handler (suffix/open-ended/bounds/416); CORS
`allow_credentials=False`; chat session bound + size caps; chat error sanitization; `data_loader` sort
whitelist + numeric coercion + tail-window + tokenizer threshold; chat model persistence.

**Export:** HTML title/URL escaping; markdown YAML frontmatter escaping.

**Data/scripts/utils:** `--transcribe-missing` import fix; coda pagination cap + retry deadline;
`naming.slugify` no longer collapses to "" (+2 tests); `patch_whisperx` `rmtree(ignore_errors=True)`;
`importer` print→logger; `database` URL credential redaction; `youtube` lazy `pyytdata` + module logger;
`categorizer` dead code removed.

**Docs/policy:** `tests/README.md` + `tests/AGENTS.md` live test counts; `interface/AGENTS.md` API table;
root `AGENTS.md` mock-policy reconciled; `docs/REFACTOR_READINESS.md` marked a historical snapshot.

---

## Open / deferred (after this pass)

- **Heavy external flows not executed** — WhisperX/GPU, live SurrealDB, live
  Cohere, YouTube network downloads. Claims verified by code reading instead; run
  these only on the target hardware with real credentials. (During the follow-up
  pass a live OpenRouter subtitle-translation run was observed against the
  sibling journal — it was left untouched, and its CLI contract is unchanged.)
- **`insights_findings.md` (working notes)** — Insights-series caption-fix and
  translation-status notes; kept untracked per its own "Do not commit/push until
  the user asks." note. Recurring translation-work logs like this should live
  outside the repo or be deleted once the run is done.
- **Coverage %** — intentionally not hardcoded anywhere (docs policy); see live
  `uv run pytest tests/ --cov-report=term-missing`. Confirmed no-action.

---

## Follow-up pass — deferred items landed (2026-08-02)

- **TR1 — Land the subtitle-translation feature** (was "README `docs/translation.md`
  row" + untracked WIP): committed `scripts/translate_subtitles.py` (local Ollama),
  `scripts/translate_subtitles_openrouter.py` (hosted OpenRouter),
  `scripts/translate_tb_watchdog.sh` (portable resumable watchdog),
  `tests/journal_utilities/test_translate_subtitles{,_openrouter}.py`, the new
  `docs/translation.md`, the README docs-table row, and the
  `.translate_tb_watchdog.lock*` gitignore pattern. The earlier duplicate OpenRouter
  variant (`scripts/translate_openrouter.py`) was **consolidated** into
  `translate_subtitles_openrouter.py` — its placeholder-hash skip, batch echo
  guard, and per-cue fallback were ported, all 34 ruff errors fixed (annotations),
  black-formatted, and the `~/.hermes/.env` API-key fallback replaced with the
  repo's gitignored `.env` (public-repo safe). No personal paths remain in any
  committed file (swept). ✓ `feat(translate): land subtitle translation pipeline (local Ollama + hosted OpenRouter)` (commit `177d2cf`)
- **TR2 — Drop the duplicate CI lint step** — the "Lint the journal integrity
  gate" step (`ruff check scripts/validate_journal.py`) was a subset of the
  repo-wide `ruff check src/ tests/ scripts/`; removed. ✓ `ci: drop duplicate lint step (covered by the repo-wide ruff check)` (commit `e0e0dd8`)
- **TR3 — Coverage policy** — confirmed: counts/coverage stay out of committed
  docs by design; nothing to implement.

---

## Round-2 agent-ergonomics pass — 2026-08-31 (lane E)

- [x] **scripts/README.md covered 6 of 24 scripts by name; 4 on-disk scripts
      entirely undocumented** (`build_pages_site.py`, `derive_captions_from_json.py`,
      `sync_youtube_metadata.py`, `txt_to_segments.py`). Added a pipeline map
      (ingest → transcribe → captions → speakers → journal v2 maintenance →
      pages/translation surfaces) at the top plus per-script sections for the four
      missing ones. Acceptance: a mechanical name-scan of `scripts/*.py` vs
      `scripts/README.md` reports zero undocumented scripts; all referenced paths
      exist on disk. ✓ this pass
- [x] **Verified Makefile target references and docs script references resolve**
      (`-m` module paths and `scripts/*.py` args in `Makefile`, plus every
      `scripts/…py` mention in `docs/*.md`). All resolve; no stale commands found
      this pass. Acceptance: zero missing refs in the same mechanical scan. ✓
- [ ] **Documentation test-count snapshot drift** — `tests/README.md` /
      `tests/AGENTS.md` counts are dated snapshots by policy; refresh from a live
      `uv run pytest tests/ -q` whenever a pass touches tests. Deferred: this
      round changed docs only; no test surface moved.

## E2 M0 CI-gates pass — 2026-09-23 (feat/m0-ci-gates)

- [ ] **E2 remainder — formatting-only commit + black removal (sibling-owned files)** — the
  CI surface `.github/workflows/test.yml` now gates `ruff format --check src/ tests/ scripts/`
  (required check: `test`) and the new `.pre-commit-config.yaml` runs ruff (check + fix),
  ruff format, and mypy on src; `.git-blame-ignore-revs` holds a placeholder for the
  formatting commit. This reverses the M2 decision that dropped the ruff-format gate
  (the black convention is retired in favor of ruff format). Blocking on ju-repo-diet:
  land the formatting-only commit (`uv run ruff format src/ tests/ scripts/`, ~63 files,
  style-only, SHA goes into `.git-blame-ignore-revs`) and remove `[tool.black]` + the
  `black` dev dependency from `pyproject.toml` and the `make format` target from `Makefile`;
  update the black rows in `CONTRIBUTING.md` / `CLAUDE.md` in the same PR.

## Notes for the next reviewer

- Test/corpus counts are live snapshots — run `uv run pytest tests/ -q`; do not hardcode totals
  (`docs/AGENTS.md`).
- Gate workflow: `uv run pytest tests/ -q`, `uv run ruff check src/ tests/ scripts/`,
  `uv run mypy src`. Both ruff and mypy are enforced in `.github/workflows/test.yml`.
- The v2 journal maintenance pipeline lives in `docs/JOURNAL_SCHEMA.md` and the read-only/idempotent
  gate scripts `scripts/{enrich_metadata,repair_split_transcripts,generate_journal_indexes,validate_journal}.py`.
- This pass (2026-08-02) was docs-only + config fixes; the follow-up pass landed the
  subtitle-translation feature (local Ollama + hosted OpenRouter engines, see
  `docs/translation.md`). `insights_findings.md` remains untracked working notes.

---

## I4 — site-builder language coverage fix (2026-09-23, fleet agent ju-site-langs)

**Finding (verified):** `site/builder.py` read only the lowercase `translations/`
subdirectory with `tr_dir.glob("*.srt")` and used the raw penultimate dot
segment as the language key. Against the canonical journal repo (560 of 573
items keep translations in legacy capital-T `Translations/`, per the 2026-09-23
handoff), that made almost every item report `languages: []` in the site
manifest. The sibling local checkout has all 178 translation-bearing items in
lowercase `translations/`, so the before/after item count there is flat; the
spellings fix is proven by unit tests (both spellings, `.SRT` extension case,
both-spelling dedupe on case-sensitive CI).

**Fixed this pass:**
- `builder.py`: translation discovery is now case-insensitive for the directory
  (`translations/` or `Translations/`, lowercase preferred, files deduped by
  name) and the `.srt` extension; language keys strip trailing parenthetical
  annotations (`.chi(translated)` → `chi`, `.en(ca)` → `en`) and reject
  non-language segments (real junk existed: two transcript-dump SRTs in
  BookStream_001 exposed as fake "languages" like
  `08 ~  Governing Continuous Transformation_transcript`).
- `translate_subtitles_openrouter.py`: the resume guard (`existing_translation`)
  checks both `translations/` spellings, so a run never re-pays OpenRouter for
  output already produced in either spelling.
- Tests: `tests/journal_utilities/test_site_builder.py` (lang-key variants,
  capital dir, `.SRT` extension, both-spelling dedupe — skipped on
  case-insensitive filesystems, runs in CI — and manifest `languages` from a
  capital-`Translations/` tree) and
  `tests/journal_utilities/test_translate_subtitles_openrouter.py` (guard unit
  test + end-to-end `main()` skip proof with no API call).

**Real-data measurement** (local sibling checkout
`instituteos/repos/ActiveInferenceJournal`, 573 items with metadata.json):
items with ≥1 language 178 → 178 (all lowercase dirs locally); distinct lang
keys 26 → 22, dropping 2 garbage keys and un-annotating 12 `(translated)`-tag
keys. On the canonical repo the same change lifts language-bearing items from
13 to all items holding either spelling (~144+ per the handoff's
~2,880 capital-T SRTs), pending the M2 migration to a single normalized tree.

**Follow-up:** J2/M2 still owns the `Translations/` → `translations/` git mv +
BCP-47 normalization (`chi` → `zh-Hans`, `dut` → `nl`, …); this fix is the
reader-side bridge until that migration lands.
