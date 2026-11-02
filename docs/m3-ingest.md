# M3 — Weekly Ingest (secret-free yt-dlp enumeration, diff, scaffolds)

> [!NOTE]
> For the **journal-infra** agent: this module lives in Journal-Utilities
> (`src/journal_utilities/ingest/`); the weekly schedule/workflow itself belongs
> in ActiveInferenceJournal. Everything below is what the journal-side workflow
> needs to call.

## What it does

Four read-only steps (dry-run is the **default** for every CLI; files are only
written behind `--no-dry-run`):

1. **Flat enumerate** — `journal_utilities.youtube.channel` runs
   `yt-dlp --flat-playlist` over the `/videos`, `/streams` and `/shorts` tabs of
   `UCbPq2w41ZaJSWtpCq4BE6Dg` (@ActiveInference) and saves one channel manifest
   (id/title/upload_date/duration/description). **No API key, no quota.**
2. **Delta** — the flat manifest is diffed against the journal's `INDEX.json`
   (`items[].parts[]` video ids) to select the **new** videos only.
3. **Full per-video extraction** — every new video gets one full `yt-dlp`
   extraction (`--dump-single-json --skip-download`, no media downloaded).
   Bounded work: just the weekly delta, capped by `--max-new` (default 50).
   This is the step that can see `availability` and `live_status`, which the
   flat pass does not report.
4. **Scaffold / diff** — per-item `metadata.json` scaffolds for worklist
   entries: `transcript_kind: "youtube"` placeholders and `status` from the
   evidence rules below. Naming via the shared categorizer reproduces the
   journal tree exactly: streams →
   `data/video/activeinferenceinstitute/<Category>/<Category>_NNN`
   (e.g. `GuestStream/GuestStream_141`), textbook sessions → the nested
   `TextbookGroup/<Book>/Cohort_N/<Session|Meeting>_NNN` (the categorizer's
   `category` is that full nested dir), unmatched titles → the existing
   `Other/<slug>` series. Existing items are never overwritten; canonical
   episode numbers are never renumbered. `ingest.diff` is the
   channel-vs-manifest-vs-INDEX reconciliation report (quota-free; consumes a
   saved channel manifest or worklist JSON).

No YouTube writes anywhere in this module (handoff Rules 1/2).

## Status evidence rules (the `unknown` rule)

`status` is an ingest-scaffold field (it is **not** part of the journal's
`metadata.json` schema). It is derived from recorded evidence only:

| `status` | Requires |
| --- | --- |
| `scheduled` | premiere evidence: `broadcast_status == "upcoming"` (yt-dlp `live_status == "is_upcoming"`) or `upload_status == "unpublished"` |
| `published` | availability evidence: `privacy_status` ∈ {`public`, `unlisted`} **and** a broadcast state that is explicitly not upcoming (`none`/`live`) |
| `unknown` | anything else |

- **No status is ever upgraded without evidence.** Anything the extractor
  cannot determine is recorded as the literal `"unknown"`; a field recorded as
  `unknown` can never yield `published`, and the flat pass never produces
  `published` on its own (it carries no status information at all).
- `privacy_status` is mapped from yt-dlp `availability` (`public` / `unlisted` /
  `private`; anything else → `unknown`).
- `broadcast_status` is mapped from yt-dlp `live_status`
  (`is_upcoming`→`upcoming`, `is_live`→`live`, `post_live`/`was_live`/`not_live`
  →`none`, anything else → `unknown`).
- `upload_status` is **permanently `unknown`** on this path: yt-dlp has no
  equivalent of the Data API's `status.uploadStatus`. The field stays in the
  worklist schema (the Data API path fills it) and is always recorded as
  `unknown` here — scheduling leans on `broadcast_status`.
- Failed or skipped extractions (past `--max-new`, network error, malformed
  JSON) leave that video `unknown`; it is still listed in the worklist, with a
  warning, and must not be treated as published.
- `published_at` is only set from a date the source actually reported
  (`upload_date` on the flat pass, `timestamp`/`release_timestamp` from a full
  extraction); an absent/garbled date stays empty.

## CLI entry points

```bash
# 1. Weekly enumeration + delta resolution (secret-free; writes only with --no-dry-run)
uv run --no-sync python -m journal_utilities.ingest.ytdlp \
  --journal /path/to/ActiveInferenceJournal \
  --output data/output/ingest-worklist.json \
  --channel-output data/output/channel_videos.json \
  --max-new 50 --no-dry-run

# The same step, offline/reproducible: reuse a saved flat manifest and replay
# saved full extractions from <details-dir>/<video_id>.json
uv run --no-sync python -m journal_utilities.ingest.ytdlp \
  --journal /path/to/ActiveInferenceJournal \
  --channel-manifest data/output/channel_videos.json \
  --details-dir saved-details/ --no-dry-run

# 2. Scaffolds from the worklist (default dry-run; prints planned paths)
uv run --no-sync python -m journal_utilities.ingest.scaffold \
  --journal /path/to/ActiveInferenceJournal \
  --worklist data/output/ingest-worklist.json --no-dry-run

# 3. Reconciliation report (never writes YouTube state; quota-free)
uv run --no-sync python -m journal_utilities.ingest.diff \
  --journal /path/to/ActiveInferenceJournal \
  --channel-manifest data/output/channel_videos.json --output recon-report.json
```

`--no-resolve` skips the full extractions entirely (every status stays
`unknown`); `--details-dir` and `--no-resolve` are mutually exclusive. The step
refuses to diff against a missing/empty `INDEX.json` (`refusing to diff` is a
fatal error, never "everything is new").

### Data API alternative (not used by the weekly workflow)

`python -m journal_utilities.ingest.enumerate` is the older Data API path
(`playlistItems.list` + batched `videos.list`) and needs `YOUTUBE_API_KEY`
(`--api-key` defaults to that env var; without it the CLI exits nonzero with
guidance). It costs ≈32 units/run against the 10,000/day budget
(`channels.list` 1 + ~16 playlist pages + ~15 video batches). It fills
`upload_status` for real, which is the only thing the secret-free path cannot.
Keep it for ad-hoc/manual runs; the weekly workflow stays secret-free.

## Programmatic API

```python
from journal_utilities.ingest import (
    build_worklist_from_manifest,  # (manifest, index_ids, runner, max_new) -> AdapterResult
    build_scaffold,                # (video, series, item, category, episode) -> dict
    plan_scaffolds,                # (videos, journal, skip_existing=True) -> [ScaffoldPlan]
    write_scaffolds,               # (plans, dry_run=True) -> ScaffoldReport
    build_reconciliation,          # (channel_ids, manifest_ids, index_ids) -> Reconciliation
)
from journal_utilities.ingest.ytdlp import SubprocessYtDlpRunner
from journal_utilities.youtube.channel import load_channel_manifest

manifest = load_channel_manifest("data/output/channel_videos.json")
result = build_worklist_from_manifest(
    manifest, index_ids, SubprocessYtDlpRunner(), max_new=50
)
result.worklist  # Worklist
result.resolved  # videos with a usable full extraction
result.unresolved  # videos left at status "unknown"
```

Tests can inject any object with `video_details(video_id) -> dict | None`
(`DirectoryVideoDetailRunner` replays saved JSON; `None` means "could not
determine").

## Journal-side workflow wiring (for journal-infra)

Dispatch-only weekly GitHub Actions step (ActiveInferenceJournal repo) — no
secrets, no `schedule:` while the workflow is a draft:

```yaml
- name: Weekly ingest (secret-free)
  run: |
    uv run --no-sync python -m journal_utilities.ingest.ytdlp \
      --journal . --output data/output/ingest-worklist.json \
      --channel-output data/output/channel_videos.json --max-new 50 --no-dry-run
    uv run --no-sync python -m journal_utilities.ingest.scaffold \
      --journal . --worklist data/output/ingest-worklist.json   # dry-run preview
```

Notes for the workflow author:

- `ingest.diff` exits **0 only when the channel manifest, the per-video
  manifests and INDEX fully reconcile**. A fresh weekly delta cannot reconcile
  until its new items are ingested, so read it as a diagnosis gate: run it
  after the scaffold/download steps, and treat a nonzero exit as "the listed
  gaps still need work", not as a broken run.
- Both artifacts are written under `data/output/` only with `--no-dry-run`:
  the worklist (`Worklist.to_dict()`; `new_videos[]` entries carry
  `video_id/title/published_at/duration_seconds/privacy_status/upload_status/
  broadcast_status/publication_state/is_scheduled/url`) and the flat channel
  manifest (the artifact `ingest.diff` consumes).
- Keep the scaffold step in dry-run for the PR preview; apply
  (`--no-dry-run`) only on an approved, human-reviewed run.
- Videos whose line in the run log reads `[unknown]` were not resolved (past
  `--max-new`, extraction failure) — look at them before scaffolding.
- `ingest.diff` flags video ids referenced by more than one canonical INDEX
  item and blocks reconciliation; items carrying `duplicate_of` (legitimate
  mirrors, e.g. per-talk uploads also listed under `Other/`) are annotated
  and exempt. `load_manifest_ids` only counts stems shaped like a YouTube id
  (11 chars, `[A-Za-z0-9_-]`), so `channel_videos.json` and other config files
  in `data/output/` are not mistaken for videos.
- Known upstream quirk (pre-existing, not this module):
  `journal_utilities.youtube.categorizer`'s YOUTUBE_TITLE `textbookgroup`
  pattern routes "ActInf Textbook Group ~ Cohort N ~ Session M" titles into
  `ParrPezzuloFriston2022/Cohort_N/Meeting_00M`. Worth fixing upstream in
  the categorizer; flagged here for the journal-infra agent.

## Testing

Unit tests fake the external I/O only (Data API service, full per-video
extractions) — no network, no key, no yt-dlp:

```bash
uv run --no-sync pytest tests/journal_utilities/ingest tests/youtube -q
```
