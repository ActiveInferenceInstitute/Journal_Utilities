# Scripts

CLI utilities for data processing, transcription, and course scaffolding.

Every script here is a thin CLI orchestrator over `src/journal_utilities/` or the
sibling `ActiveInferenceJournal` checkout. Run any of them as
`uv run python scripts/<name>.py --help` for exact flags.

## Pipeline map (what exists and how it chains)

```text
YouTube ingest            download_channel.py --> data/output/channel_videos.json
                          sync_youtube_metadata.py (enrich titles/tags/chapters from local metadata)
Transcription             transcribe_missing.py / transcribe_worklist.py (mlx-whisper, Mac)
                          transcription_status.py (read-only coverage report)
Caption/subtitle layer    derive_captions_from_json.py (transcript.json -> captions/*.srt)
                          txt_to_segments.py (plain .txt -> pseudo-timed segments)
Speaker attribution       speaker_cues.py -> apply_speaker_names.py (repair + name mapping)
Recovery/repair           repair_split_transcripts.py, recover_whisperx.py,
                          patch_whisperx.py, fix_scheduled_dates.py, fetch_chapters.py
Journal v2 maintenance    enrich_metadata.py -> repair_split_transcripts.py
                          -> generate_journal_indexes.py -> validate_journal.py (read-only gate)
Publication surfaces      build_pages_site.py (journal -> static GitHub Pages bundle)
Translation               translate_subtitles_openrouter.py (docs/translation.md)
Curriculum                scaffold_youtube_courses.py
```

The canonical maintenance chain is documented in `docs/JOURNAL_SCHEMA.md`; the
read-only `validate_journal.py` is the acceptance gate for every step above.

## `download_channel.py`

Primary CLI for enumerate-and-download of YouTube channel content.

### Usage — download_channel

```bash
python scripts/download_channel.py --help

# Download transcripts only (fastest)
python scripts/download_channel.py --transcripts --resume

# Download transcripts + audio + local Whisper fallback
python scripts/download_channel.py --transcripts --audio --resume --transcribe-missing

# Full download with cookies for rate limiting
python scripts/download_channel.py --transcripts --audio --video --cookies-from-browser chrome
```

### Features — download_channel

- Enumerate all videos from a YouTube channel (unions `/videos` + `/streams` + `/shorts`)
- Download transcripts (YouTube captions), audio (m4a/mp3), and video (mp4)
- Resume interrupted downloads
- Fallback to local Whisper transcription when YouTube captions unavailable
- Cookie-based auth to bypass rate limiting

> ⚠ **Cookie safety:** the downloader runs cookie-free by default. Never write
> cookies into a tracked path and never commit `cookies.txt` — see the
> cookie-safety note in `CLAUDE.md`.

## `transcribe_missing.py`

Standalone local transcription for videos missing transcripts.

### Usage — transcribe_missing

```bash
python scripts/transcribe_missing.py --help

# Transcribe all missing (Apple Silicon, mlx-whisper)
python scripts/transcribe_missing.py

# Dry run to preview what would be transcribed
python scripts/transcribe_missing.py --dry-run

# Limit to N files
python scripts/transcribe_missing.py --max-files 5
```

## `transcribe_worklist.py`

GPU WhisperX worklist for the journal — plans and runs transcription + speaker
diarization for items that need it (dry-run plan by default; add `--run`).

### Usage — transcribe_worklist

```bash
uv run python scripts/transcribe_worklist.py            # plan (dry run)
uv run python scripts/transcribe_worklist.py --run      # transcribe + diarize
uv run python scripts/transcribe_worklist.py --run --max-videos 20 \
    --batch-size 48 --compute-type float16              # bounded run

# Options: --journal <path>, --work-dir (default data/output/whisperx),
#          --device (default cuda)
```

Requires `HF_TOKEN` (or `HUGGINGFACE_TOKEN`) in `.env` for diarization models.
Resumable: already-processed videos are skipped on reruns.

## `scaffold_youtube_courses.py`

Generate course directory structures from downloaded transcripts.

### Usage — scaffold_youtube_courses

```bash
python scripts/scaffold_youtube_courses.py --help

# Scaffold courses from all playlists
python scripts/scaffold_youtube_courses.py
```

### Features — scaffold_youtube_courses

- Creates numbered module directories per video
- Generates `module.md` files with metadata and transcript content
- Filesystem-safe slugification of titles

## `patch_whisperx.py`

Patches WhisperX for compatibility with pyannote.audio 4.0+.

### Usage — patch_whisperx

Run after installing WhisperX:

```bash
python scripts/patch_whisperx.py
```

### When to Run

- After initial `uv sync` installation
- After upgrading WhisperX or pyannote.audio
- If speaker diarization fails with API errors

## `fix_scheduled_dates.py`

One-time database migration utility that fixes `scheduled_date` fields stored as strings instead of proper datetime objects in SurrealDB.

### Usage — fix_scheduled_dates

```bash
python scripts/fix_scheduled_dates.py
```

> **Note**: Requires a running SurrealDB instance and valid credentials in `.env`.

## `fetch_chapters.py`

Fetch YouTube chapter lists (timestamped video descriptions) for every channel
video and cache them to `data/input/video_chapters.json`. Chapters are the
upstream source of truth for the journal's `sessions[]` seed data (see
`enrich_metadata.py`). Incremental — already-fetched ids are skipped.

### Usage — fetch_chapters

```bash
python scripts/fetch_chapters.py              # fetch all missing
python scripts/fetch_chapters.py --limit 20   # bounded run
```

## Journal v2 metadata and indexes

```bash
python scripts/enrich_metadata.py --journal ../ActiveInferenceJournal --snapshot-only --apply
python scripts/generate_journal_indexes.py --journal ../ActiveInferenceJournal
python scripts/generate_journal_indexes.py --journal ../ActiveInferenceJournal --check
```

`enrich_metadata.py` is dry-run by default and preserves journal-owned
`sessions[]`. `generate_journal_indexes.py` derives `INDEX.json` and `INDEX.md`
from canonical metadata, including duplicate and unique-video counts.

Use the combined read-only integrity gate before committing or publishing a
journal update:

```bash
python scripts/validate_journal.py \
  --journal ../ActiveInferenceJournal \
  --manifest data/output/channel_videos.json
```

The gate checks metadata/path consistency, URL-only enrichment fields, derived
indexes, duplicate targets and canonical ID uniqueness, transcript JSON shape,
manifest coverage, and the no-audio/no-credentials rule for the journal's
`main` branch. `--strict-manifest` also rejects canonical IDs that are absent
from the supplied manifest; the default warning is useful when the manifest is
older than the journal and should be re-enumerated first.

For split-file items whose merged transcript sections need rebuilding:

```bash
python scripts/repair_split_transcripts.py --journal ../ActiveInferenceJournal --utilities .
python scripts/repair_split_transcripts.py --journal ../ActiveInferenceJournal --utilities . --check
```

The repair is idempotent and writes only when complete `<video_id>_sessNN`
source pairs are available.

## Journal v2 — transcription status, speaker mapping, recovery

These tools operate on the sibling journal repo (`--journal`, default
`../ActiveInferenceJournal`) and follow the raw-vs-derived transcript design in
[`docs/JOURNAL_SCHEMA.md`](../docs/JOURNAL_SCHEMA.md): `transcript.json` keeps
machine `SPEAKER_NN` labels forever; human names live only in `metadata.json`
`parts[].speakers`.

### `transcription_status.py`

Derive the transcription worklist from the journal repo (no database). Status is
computed, never stored; private/unlisted items are excluded by policy.

```bash
python scripts/transcription_status.py                        # summary + worklist
python scripts/transcription_status.py --report worklist.json # write full JSON worklist
```

### `speaker_cues.py`

Print identification cues for unmapped speakers in an item — first appearance,
longest utterance, total talk time, and clickable YouTube links (`&t=Ns`). Record
the names in `metadata.json` `parts[].speakers`, then run `apply_speaker_names.py`.

```bash
python scripts/speaker_cues.py                                # items still needing mapping
python scripts/speaker_cues.py --item TextbookGroup/Namjoshi2026/Cohort_1/Session_024
```

### `apply_speaker_names.py`

Regenerate `transcript.txt` from `transcript.json` + `parts[].speakers`. Labels
with a name mapping are replaced; unmapped ones stay `SPEAKER_NN` and are
reported. Idempotent — fixing a wrong name is editing `metadata.json` and
re-running. Caption-only transcripts are salvaged to
`captions/youtube_captions.txt` before replacement.

```bash
python scripts/apply_speaker_names.py       # dry run
python scripts/apply_speaker_names.py --apply
```

### `recover_whisperx.py`

Recover pre-reorg WhisperX transcripts from journal git history (they survive in
git commits even though the June 2026 reorg dropped them from the working tree)
and write them per the raw/derived design. Only caption-only items fully covered
by whole-video outputs are written; partial/duplicate items are reported and
skipped.

```bash
python scripts/recover_whisperx.py                  # dry run: show plan
python scripts/recover_whisperx.py --apply          # write into the journal
python scripts/recover_whisperx.py --item "GuestStream/GuestStream_040"
```

### `refactor_journal.py`

Refactor the journal into the v2 schema (see `docs/JOURNAL_SCHEMA.md`). Dry-run
by default: classifies every file and audits zero data loss before applying.
Applying is done out-of-place with `--build <dir>` (staging copy), then validated
with `validate_journal.py` before swapping in. `--apply` is intentionally refused
with guidance rather than doing a silent in-place move.

```bash
python scripts/refactor_journal.py --journal ../ActiveInferenceJournal            # audit
python scripts/refactor_journal.py --journal ../ActiveInferenceJournal --build /tmp/v2
```

## Subtitle Translation (`translate_subtitles_openrouter.py`)

Translate per-item caption SRTs (`captions/*.srt`) in `ActiveInferenceJournal` into 11 target languages (es/fr/de/pt/it/nl/ru/ja/ko/zh-Hans/zh-Hant). See full guide in [`docs/translation.md`](../docs/translation.md).

### Hosted OpenRouter Translation (`translate_subtitles_openrouter.py`)

Uses OpenRouter API (requires `OPENROUTER_API_KEY` in `.env` or environment):

```bash
# Run hosted translation for a series
python scripts/translate_subtitles_openrouter.py --journal ../ActiveInferenceJournal --series "Livestream"
```

Resumable and idempotent: languages whose output already exists — under either
`translations/` spelling — are skipped without an API call unless `--force`.


## `build_pages_site.py`

Compile the sibling `ActiveInferenceJournal` checkout into a static GitHub Pages
bundle (HTML pages + index) under the journal's own output directory. Pass
`--help` for the journal-path and output flags; read-only with respect to this repo.

Modes (M4):

- default — dry run: builds into a temp dir and reports counts, writes nothing.
- `--apply` — write the bundle to `--output` (SPA + per-item pages + `sitemap.xml`
  + `robots.txt`, per the ActiveInferenceJournal `docs/m4-site-spec.md`).
- `--check` — CI freshness gate: build to a temp dir and compare against an
  existing `--output`; exit 1 with a per-file drift report on any difference.

The bundle's per-item language lists are derived from every `translations/`
spelling (`translations/` and legacy `Translations/`), any `.srt` extension
case, and annotated tags like `.chi(translated)` (key: `chi`).


## `derive_captions_from_json.py`

Derive base English `captions/*.srt` files from each item's diarized
`transcript.json` for journal items that currently lack caption SRTs. Dry-run by
default; add `--apply` to write the `.srt` files to disk.

## `sync_youtube_metadata.py`

Closed-loop metadata synchronizer: merges locally cached channel data
(`data/output/channel_videos.json`, `data/input/video_chapters.json`) and the
InstituteOS source tree to derive video tags and refresh transcript-adjacent
metadata. Uses repo-relative paths automatically.

## `txt_to_segments.py`

Convert a timestamp-free plain-text transcript
(`data/output/transcripts/<id>.txt`) into pseudo-timed ~30-second segments
(~80 words each) so downstream diarization/segment tooling has a uniform input.
