# YouTube integration

The YouTube surface is **read-mostly with an explicitly guarded write path**.
Everything here enforces the pipeline handoff rules (see the repo root
`AGENTS.md` and `docs/m3-ingest.md`):

- **Rule 1 — no write without a live snippet.** `scripts/sync_youtube_metadata.py`
  refuses to update a video unless the live snippet was fetched through the
  Data API **in the same run**. The yt-dlp/manifest fallbacks are read-only
  inputs; they can never feed a write (all 735 manifest descriptions are
  empty strings — a fallback write would erase abstracts and credits).
- **Backups before every write.** Pre-update state is saved to
  `data/output/yt_backup/<video_id>/<timestamp>.json`.
- **Dry-run by default.** Every YouTube command prints an old-vs-new diff;
  live writes require the explicit `--apply` flag.
- **Quota-aware.** Default 10,000 units per day. Caption lookup costs 50
  units and insertion costs 400. A video lookup costs 1 unit and a
  description update costs 50. Use `--quota-budget` for accounting. The
  metadata batch driver defaults to
  a quota-safe `MAX_VIDEOS=150`.

## OAuth ownership

Authorize writes via the Institute's designated Google account and select
the **Active Inference Institute** YouTube channel in the consent flow.
Write tools verify the selected channel with `channels.list(mine=true)`.
Provide public inventory keys through `YOUTUBE_API_KEY` and local OAuth
token paths through `YOUTUBE_TOKEN_PATH`. Keep credentials, reports, and
pre-update snapshots outside tracked files.

## Surfaces

| Surface | Purpose |
| --- | --- |
| `src/journal_utilities/youtube/client.py` | Data API client with strict reads for reviewed workflows. Public video and playlist reads can use an API key. Caption listing and all writes use OAuth. |
| `scripts/youtube_channel_audit.py` | Read-only link, language, series ordering, and Journal coverage audit. Produces a public-only ingest worklist and an optional reviewed description repair plan. |
| `scripts/sync_youtube_metadata.py` | Description/metadata sync with Rule-1 guard, backups, quota budget, `--dry-run` default. Replaces the dead `/blob/main/transcripts/` link with the resolving `tree/main/data/video/.../<item>` journal URL while preserving abstract, chapters, and tags. Idempotency guard: when the live snippet already equals the planned state it skips the 50-unit `videos.update` (1 list unit instead; regression test `test_idempotent_run_skips_write`). |
| `scripts/live_batch.sh` | Batch driver, repo-relative paths, quota-safe defaults. |
| `src/journal_utilities/ingest/` | Weekly channel enumeration / scaffold / reconciliation (M3) — read-only. The weekly workflow is **secret-free** (`yt-dlp` flat pass + delta full extractions; no key, no quota); the Data API path (~32 units/run) remains the manual alternative. |
| `scripts/upload_captions.py` | Reviewed English captions from WhisperX word timings. See [Caption preparation and uploads](youtube-captions.md). |

## Channel QA and public backlog

```bash
uv run --extra youtube python scripts/youtube_channel_audit.py audit \
  --journal /path/to/ActiveInferenceJournal \
  --report /private/scratch/youtube-qa.json \
  --worklist /private/scratch/public-backlog.json \
  --fail-on-findings
```

The worklist contains completed public videos owned by the selected channel
and absent from the current Journal index. A malformed index or failed API
page aborts collection before publishing the report or worklist. The report
counts unavailable upload details without publishing their IDs. The optional
`--check-http` tests links to known Institute hosts and reports definitive
404 or 410 responses. It omits link query strings and skips redirects.

Use the worklist with the Journal's public ingest review before scaffolding.
Run this check from the Institute's local operator environment on the chosen
weekly cadence. Use `--owner` for read-only collection with a cached,
channel-bound OAuth grant. The audit needs neither media downloads nor a
write to YouTube.

## Reviewed description repairs

Add `--plan /private/scratch/youtube-plan.json --classes dead,legacy,backlink`
to the audit to prepare a JSON review. Compare each old and proposed
description and keep the printed plan digest. Unknown destination mappings
for obsolete links remain review findings.

```bash
uv run --extra youtube python scripts/youtube_channel_audit.py apply \
  --journal /path/to/ActiveInferenceJournal \
  --plan /private/scratch/youtube-plan.json \
  --plan-sha256 <reviewed-sha256> \
  --backup-dir /private/scratch/youtube-backups \
  --limit 10
```

Apply requires the reviewed Journal index, the selected OAuth channel, and
an unchanged live snippet for each proposed write. It preserves the title,
tags, category, and metadata language. A private snapshot is written before
each update and the live result is read back. Reruns skip descriptions
already at the reviewed state. Store API snapshots locally and refresh or
purge them when their operator retention window expires. See the
[YouTube API Developer Policies](https://developers.google.com/youtube/terms/developer-policies).

## Local checks

```bash
make yt-dryrun                          # dry-run the sync (no VIDEO = full plan)
make yt-dryrun VIDEO=<video_id>         # one video, old-vs-new diff + backup path
uv run pytest tests/youtube tests/scripts -q
```

## Dead-link description repair (closed 2026-09-25)

The 2026-09-24 channel audit found 284 videos whose descriptions embedded a
dead
`github.com/ActiveInferenceInstitute/ActiveInferenceJournal/blob/main/transcripts/<video_id>.md`
link (the transcripts moved into the journal data tree). The sync script now
rewrites those to the resolving
`tree/main/data/video/<category>/<series>/<item>` journal URL. All 284 are
live-fixed and verified (110 write-verified in the final run, 3 confirmed
no-change by the idempotency guard — one of them because its earlier write
had in fact completed server-side despite a transport hang).

Runbook for any future repair wave:

```bash
cd /path/to/Journal_Utilities && set -a && source .env && set +a \
  && export YOUTUBE_CLIENT_SECRETS=<secrets.json> \
  && export YOUTUBE_TOKEN_PATH=<token.json> \
  && uv run --extra youtube python scripts/sync_youtube_metadata.py \
       --journal <journal-checkout> --apply --quota-budget 10000 --verify
```

Before `--apply`: fetch the live manifest (`data/output/channel_videos.json`),
review the dry-run diff, and confirm the pre-update backups are appearing
under `data/output/yt_backup/`. The run skips videos whose live description
already matches the plan (`no change, skipping write`), so re-runs after an
interrupted batch are safe and cheap.
