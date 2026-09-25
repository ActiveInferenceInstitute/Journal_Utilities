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
- **Quota-aware.** Default 10,000 units/day. Per-call costs:
  `videos.update` 50, `captions.insert` 400, `playlistItems.insert` 50,
  `list` 1. Use `--quota-budget` for accounting; `live_batch.sh` defaults to
  a quota-safe `MAX_VIDEOS=150`.

## OAuth ownership

The `youtube.force-ssl` OAuth grant belongs to the **Institute admin account**
(`admin@activeinference.institute`; org `ActiveInferenceInstitute`). The
`ActInfInstitute` account is the personal/admin identity — do not issue write
credentials from it. Secrets come from env (`YOUTUBE_API_KEY`,
`YOUTUBE_OAUTH_*`) or GitHub secrets; never commit cookies or tokens.

## Surfaces

| Surface | Purpose |
| --- | --- |
| `src/journal_utilities/youtube/client.py` | Vendored minimal Data API client (`videos.list/update`, `captions.list/insert`, `playlists.*`, `playlistItems.*`). API key = read-only; OAuth only needed for writes. Unit-tested against fake services. All requests bounded by a 120 s socket timeout (set in `_build_service()`), so a dead connection can no longer stall a `videos.update` indefinitely. |
| `scripts/sync_youtube_metadata.py` | Description/metadata sync with Rule-1 guard, backups, quota budget, `--dry-run` default. Replaces the dead `/blob/main/transcripts/` link with the resolving `tree/main/data/video/.../<item>` journal URL while preserving abstract, chapters, and tags. Idempotency guard: when the live snippet already equals the planned state it skips the 50-unit `videos.update` (1 list unit instead; regression test `test_idempotent_run_skips_write`). |
| `scripts/live_batch.sh` | Batch driver, repo-relative paths, quota-safe defaults. |
| `src/journal_utilities/ingest/` | Weekly channel enumeration / scaffold / reconciliation (M3) — read-only, ~32 quota units per run. |
| `scripts/upload_captions.py` | Caption uploads (M5): skips existing non-ASR tracks, prefers WhisperX-derived SRTs, quota-scheduled (~24/day). First-wave translation targets: `zh-Hans`, `de`. |

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
  && uv run --no-sync python scripts/sync_youtube_metadata.py \
       --journal <journal-checkout> --apply --quota-budget 10000 --verify
```

Before `--apply`: fetch the live manifest (`data/output/channel_videos.json`),
review the dry-run diff, and confirm the pre-update backups are appearing
under `data/output/yt_backup/`. The run skips videos whose live description
already matches the plan (`no change, skipping write`), so re-runs after an
interrupted batch are safe and cheap.
