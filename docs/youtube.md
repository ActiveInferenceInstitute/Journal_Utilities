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
| `src/journal_utilities/youtube/client.py` | Vendored minimal Data API client (`videos.list/update`, `captions.list/insert`, `playlists.*`, `playlistItems.*`). API key = read-only; OAuth only needed for writes. Unit-tested against fake services. |
| `scripts/sync_youtube_metadata.py` | Description/metadata sync with Rule-1 guard, backups, quota budget, `--dry-run` default. |
| `scripts/audit_live_descriptions.py` | **Read-only** audit listing live videos that carry the dead `/blob/main/transcripts/` link or the `--- RESOURCES & TRANSCRIPT ---` block. |
| `scripts/live_batch.sh` | Batch driver, repo-relative paths, quota-safe defaults. |
| `src/journal_utilities/ingest/` | Weekly channel enumeration / scaffold / reconciliation (M3) — read-only, ~32 quota units per run. |
| `scripts/upload_captions.py` | Caption uploads (M5): skips existing non-ASR tracks, prefers WhisperX-derived SRTs, quota-scheduled (~24/day). First-wave translation targets: `zh-Hans`, `de`. |

## Local checks

```bash
make yt-dryrun                          # dry-run the sync (no VIDEO = full plan)
make yt-dryrun VIDEO=<video_id>         # one video, old-vs-new diff + backup path
uv run pytest tests/youtube tests/scripts -q
```
