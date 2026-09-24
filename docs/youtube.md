# YouTube Module

The YouTube module (`src/journal_utilities/youtube/`) handles the discovery and categorization of content from the Active Inference Institute channel.

## Architecture

This module does **not** use the YouTube Data API v3 for enumeration, avoiding quota limits. Instead, it uses `yt-dlp`'s flat-playlist extraction features.

## Components

### 1. Channel Enumeration (`channel.py`)

Enumerates all videos on the channel.

- **Method**: unions the channel's `/videos`, `/streams`, and `/shorts` tabs via
  `yt-dlp --flat-playlist --dump-json` and dedupes by video id. (The older
  "Uploads" playlist form `UU...` truncates at ~100 entries, so it is no longer used.)
- **Output**: `ChannelManifest` containing `VideoInfo` objects.
- **Performance**: Can list 1000+ videos in seconds without downloading media.

```python
from journal_utilities.youtube.channel import enumerate_channel_videos

manifest = enumerate_channel_videos("UCbPq2w41ZaJSWtpCq4BE6Dg")
print(f"Found {manifest.total_videos} videos")
```

### 2. Playlist Enumeration (`playlist.py`)

Enumerates all playlists created by the channel.

- **Method**: Scrapes the `/playlists` tab via `yt-dlp`.
- **Output**: `PlaylistManifest` containing playlist metadata and video lists.

### 3. Categorizer (`categorizer.py`)

Heuristic engine to parse video titles into structured metadata (Category, Series, Episode).

- **Logic**: Regex pattern matching against known show formats.
- **Supported Formats**:
  - Livestreams (`Livestream #001.1`)
  - GuestStreams
  - OrgStreams
  - MathStreams
  - ModelStreams
  - Textbook Groups
  - Symposia

#### Example Parsing

| Input Title | Category | Series | Episode |
| :--- | :--- | :--- | :--- |
| `Active Inference Livestream #042.1` | `Livestream` | `Livestream_042` | `1` |
| `GuestStream #015.1: John Doe` | `GuestStream` | `GuestStream_015` | `1` |
| `OrgStream #003.1` | `OrgStream` | `OrgStream_003` | `1` |
| `MathStream #001.2: Category Theory` | `MathStream` | `MathStream_001` | `2` |
| `Applied Active Inference Symposium 2021 part 1` | `Symposium` | `2021` | `1` |
| `Textbook Group Cohort 3 Meeting 5` | `TextbookGroup` | `Cohort_3` | `Meeting_005` |

## Data Models

### `VideoInfo`

- `id`: YouTube ID (11 chars)
- `title`: Video title
- `upload_date`: YYYYMMDD
- `duration`: Seconds
- `description`: Video description
- `view_count`: Approximate views
- `url`: `https://www.youtube.com/watch?v=<id>` (auto-built from `id`)

### `ChannelManifest`

- `channel_id`: Source channel
- `enumerated_at`: Timestamp
- `videos`: List of `VideoInfo`

## Caption Pipeline (M5)

### 4. SRT Derivation (`captions.py`)

Derives uploadable SRT captions from the journal's WhisperX `transcript.json`
(blocks of `{video_id, segments}`):

- Speaker labels rendered on speaker change, mapped names from
  metadata.json `parts[].speakers`; unmapped `SPEAKER_NN` humanized to
  `Speaker N`.
- Cues wrapped to at most two lines of 42 characters; long segments split
  across sequential cues with proportional timing.
- `_sessNN`-suffixed transcript ids resolve against the base part id.

```python
from journal_utilities.youtube.captions import derive_srt_for_video

srt = derive_srt_for_video(item_dir, video_id)  # None when not derivable
```

### 5. Caption Upload (`scripts/upload_captions.py`)

Dry-run by default; live writes require `--apply` AND OAuth
(`youtube.force-ssl`; token owner **admin@activeinference.institute**).

- `captions.list` gate: videos with an existing non-ASR track (or a track
  named `English (Active Inference Journal)`) are skipped.
- Track name `English (Active Inference Journal)`, language `en`,
  `isDraft=false`; SRT staged under `data/output/captions_upload/` — the
  journal checkout is read-only input.
- Backups before every write (captions.list snapshot + pre-update metadata
  copy) to `data/output/yt_backup/<video_id>/<timestamp>-captions.json`;
  success records `captions_uploaded` with provenance in the item's
  metadata.json.
- Quota accounting: `captions.list`=1, `captions.insert`=400 units against
  `--quota-budget` (default 10,000/day) and `--max-uploads-per-day`
  (default 24; 24 x 401 = 9,624 units fits the default budget).
- Translation wave (V5): opt-in `--upload-translations` with default
  languages `zh-Hans,de` (DAF 2026-09); es/pt/fr/ja deferred.

### 6. Worklist (`scripts/captions_worklist.py`)

Read-only CSV planner ranking videos by handoff priority:
insights > top-by-views > fundamentals-2026 > rest, with per-part SRT
availability (`srt_available` column). Output feeds the upload script's
`--worklist`; the upload script re-verifies every row live.
