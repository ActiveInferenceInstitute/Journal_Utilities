# M3 — Weekly Ingest (Data API enumeration, diff, scaffolds)

> [!NOTE]
> For the **journal-infra** agent: this module lives in Journal-Utilities
> (`src/journal_utilities/ingest/`); the weekly schedule/workflow itself belongs
> in ActiveInferenceJournal. Everything below is what the journal-side workflow
> needs to call.

## What it does

Three read-only steps (dry-run is the **default** for every CLI; files are only
written behind `--no-dry-run`):

1. **Enumerate** — YouTube Data API `playlistItems.list` over the uploads
   playlist of `UCbPq2w41ZaJSWtpCq4BE6Dg` (@ActiveInference), plus batched
   `videos.list` (`part=snippet,contentDetails,status`) for title/date/duration/
   premiere status. Diffed against the journal's `INDEX.json`
   (`items[].parts[]` video ids) to emit the **new-video worklist**.
2. **Scaffold** — per-item `metadata.json` scaffolds for worklist entries:
   `transcript_kind: "youtube"` placeholders, `status: "scheduled"` for
   premieres (liveBroadcastContent=upcoming or uploadStatus=unpublished),
   series/item naming via the shared categorizer so folders match INDEX rows.
3. **Diff** — channel-vs-manifest-vs-INDEX reconciliation report
   (quota-free; consumes a saved channel manifest or worklist JSON).

Quota per weekly run: `channels.list` (1) + `playlistItems.list` (~16 pages of
50) + `videos.list` (~15 batches of 50) ≈ **32 units** against the 10,000/day
budget. No YouTube writes anywhere in this module (handoff Rules 1/2).

## CLI entry points

```bash
# 1. Weekly enumeration + worklist (writes only with --no-dry-run)
uv run --no-sync python -m journal_utilities.ingest.enumerate \
  --journal /path/to/ActiveInferenceJournal \
  --output worklist.json --no-dry-run

# 2. Scaffolds from the worklist (default dry-run; prints planned paths)
uv run --no-sync python -m journal_utilities.ingest.scaffold \
  --journal /path/to/ActiveInferenceJournal \
  --worklist worklist.json --no-dry-run

# 3. Reconciliation report (never writes YouTube state; quota-free)
uv run --no-sync python -m journal_utilities.ingest.diff \
  --journal /path/to/ActiveInferenceJournal \
  --channel-manifest worklist.json --output recon-report.json
```

`--api-key` defaults to `$YOUTUBE_API_KEY` on the enumerate step; without it the
CLI exits nonzero with guidance (diff/scaffold need no API access at all).

## Programmatic API

```python
from journal_utilities.ingest import (
    build_worklist,        # (client, index_path, channel_id) -> Worklist
    plan_scaffolds,        # (videos, journal, skip_existing=True) -> [ScaffoldPlan]
    write_scaffolds,       # (plans, dry_run=True) -> ScaffoldReport
    build_reconciliation,  # (channel_ids, manifest_ids, index_ids) -> Reconciliation
)
from journal_utilities.youtube.client import YouTubeClient

client = YouTubeClient(api_key="...")          # or inject service= for tests
worklist = build_worklist(client, Path("INDEX.json"))
plans = plan_scaffolds(worklist.new_videos, Path(journal_root))
report = write_scaffolds(plans, dry_run=False)
```

## Journal-side workflow wiring (for journal-infra)

Suggested weekly GitHub Actions step (ActiveInferenceJournal repo):

```yaml
- name: Weekly ingest check
  env:
    YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
  run: |
    uv run --no-sync python -m journal_utilities.ingest.enumerate \
      --journal . --output data/output/ingest-worklist.json --no-dry-run
    uv run --no-sync python -m journal_utilities.ingest.scaffold \
      --journal . --worklist data/output/ingest-worklist.json   # dry-run preview
```

Notes for the workflow author:

- `ingest.diff` exits **0 only when channel/manifest/INDEX fully reconcile**;
  wire its exit code as a CI gate (strict by default, per handoff).
- Keep the scaffold step in dry-run for the PR preview; apply
  (`--no-dry-run`) only on an approved, human-reviewed run.
- The worklist JSON (`Worklist.to_dict()`) is the artifact contract between
  steps 1 and 2; `new_videos[]` entries carry
  `video_id/title/published_at/duration_seconds/…/is_scheduled`.
- The vendored client (`journal_utilities.youtube.client`) enforces
  per-call quota accounting; this module adds ~32 units/run. Schedule away
  from other Data API jobs on the same key.

## Testing

Unit tests inject a fake Data API service (same pattern as
`tests/youtube/test_client.py`) — no network, no key:

```bash
uv run --no-sync pytest tests/ingest -q
```
