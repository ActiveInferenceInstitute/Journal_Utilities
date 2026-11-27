# Journal Refactor — Readiness & Pipeline State

Preparation status for the ActiveInferenceJournal v2 refactor + mega-push. Read with
[`JOURNAL_SCHEMA.md`](../reference/JOURNAL_SCHEMA.md) (target schema) and the repo `CLAUDE.md`.

_Last validated: 2026-06-29._

> **Historical snapshot.** This page records refactor-readiness state as of
> 2026-06-29. The hardcoded corpus counts below are a point-in-time audit and
> drift by design — see `docs/AGENTS.md` ("do not hardcode counts"). The
> converter has since moved to **content-based item detection + passthrough +
> an idempotent uncovered-video coverage pass** (see `scripts/refactor_journal.py`
> and `docs/reference/JOURNAL_SCHEMA.md`), so the BLOCKER section below no longer applies
> to the current code.

## Coverage — Institute channel (UCbPq2w41ZaJSWtpCq4BE6Dg)

| Metric | Value |
| --- | --- |
| Full channel (videos 269 + streams 460 + shorts 0, unioned) | **729** |
| Transcripts on disk (`data/output/transcripts/`) | **722** (99%) |
| Caption-less (no YouTube transcript) | **7** → local Whisper |

The 7 caption-less: `5oSqT8a6-dQ` (GuestStream 002.1), `93lAa-xEmHY` (Livestream 016.2),
`S5nXqPysU3I` (Livestream 033.2), `zVvTAnRwigQ` (GuestStream 012.1), and 3 untitled/likely
private (`WrixYErQot0`, `jhIzOXA1ZFg`, `t2TgSuYH-K8`). Being transcribed via `mlx-whisper`
(`download_channel.py --manifest <7> --audio --transcribe-missing`).

## Utilities improvements made

- **Enumeration fixed** (`youtube/channel.py`): unions `/videos` + `/streams` + `/shorts`
  tabs → full 729 (was capped at ~100 by the `UU...` uploads-playlist form). Validated:
  52 channel/categorizer tests pass.
- **Cookie-safe**: downloader runs cookie-free when no `cookies.txt` exists; `cookies.txt`
  is gitignored and was purged from history (see security note below). **Never** use
  `--cookies-from-browser` into a tracked path.
- **v2 schema converter** (`scripts/refactor_journal.py`): dry-run audit of the journal —
  **317 items, 9,263 files, 0 UNMAPPED**; drops 2,715 placeholder files; routes 49 audio
  files to the `audio` branch.

## Local LLM / transcription stack

| Tool | State | Use |
| --- | --- | --- |
| Ollama | running — `aya-expanse:8b`, `gemma3:4b`, `qwen2.5:3b` | RAG chat + entity extraction |
| mlx-whisper | installed | transcribe caption-less videos (Apple Silicon) |
| WhisperX | not installed | GPU diarization (optional) |
| Cohere | needs `COHERE_API_KEY` | entity/relationship graph (optional) |

## ⚠️ BLOCKER before in-place apply — converter coverage gap *(historical — see note above)*

The converter's `find_items` only matches `<Series>_<number>` folders. Full-journal
reconciliation (10,987 files total vs. 9,263 captured) found **1,725 files it does NOT
reach** and would lose in an in-place swap:

| Area | Files | Cause |
| --- | --- | --- |
| `Applied Active Inference Symposium/` | 1,128 | spaces in name; non-standard item dirs |
| `Courses/` | 552 | Discussion/Lecture nesting + course-level files |
| `ReviewStream/` | 43 | non-standard item naming |
| top-level `README.md` | 1 | outside any item |

**Gate:** the in-place apply must not run until `total files == captured + intentional
drops` (placeholders + redundant `.simple.json`). The bulk (9,263 files / 4,725 moved)
is reconciled to **0 loss**; these series need `find_items`/classification extended +
top-level file passthrough first.

## Mega-push plan (after prep verified)

1. `refactor_journal.py --apply` → in-place convert the journal to v2 (git mv preserves
   history; reconcile in==out against the 9,263 audit; UNMAPPED must stay 0).
2. Build `metadata.json` / `README.md` / `transcript.*` per item + top-level `INDEX.json`/
   `INDEX.md` + mirror `SCHEMA.md`.
3. Commit + push **main without audio** (audio gitignored).
4. Create the **`audio` branch** = main + `audio/<video_id>.64k.m4a` (configurable bitrate).
5. Assess & refine.

## Security note

`data/output/cookies.txt` once leaked live Google cookies to this public repo. History was
rewritten (`git filter-repo`), force-pushed, `.gitignore` now blocks it, and the affected
Google passwords were rotated. Treat any `cookies.txt` as a live secret — never commit it.

## Reproduce / run

```bash
uv venv && uv pip install yt-dlp youtube-transcript-api requests   # transcripts (cookie-free)
uv pip install mlx-whisper                                         # caption-less videos
PYTHONPATH=src python scripts/download_channel.py --transcripts --resume   # full 729
PYTHONPATH=src python scripts/refactor_journal.py --report plan.json        # dry-run audit
```
