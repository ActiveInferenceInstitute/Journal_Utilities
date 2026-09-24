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

### 4. Chapter Generation (`chapter_generator.py`)

Generates timestamped YouTube chapters from transcript segments via a local
Ollama model or OpenRouter, then enforces a hard quality gate
(`validate_chapters`). Only gate-passing — or YouTube-sourced — chapter
lists flow downstream (journal `sessions[]` seeding, description writes).

**Gate rules** (any violation rejects the list; generation retries up to
`max_attempts` and raises `ChapterError` if still failing):

| Rule | Threshold |
| :--- | :--- |
| Chapter count | >= 3 |
| First chapter | starts at exactly 0:00 |
| Gaps | >= 10s between consecutive chapters |
| Coverage | last chapter starts at >= 80% of total duration |
| Titles | 3-8 words, <= 60 characters |
| Filler words | none of `uh`, `um`, `so`, `like` |
| Speaker names | no bare personal-name titles ("Karl Friston") |

**Windowed generation**: the full transcript is rendered as 3-5 minute
time-windowed blocks (never truncated at the head), and the video's total
duration is passed in explicitly — the old 40k-char excerpt truncated long
videos' tails, which is why 240/416 generated lists previously ended before
60% of the video.

```python
from journal_utilities.youtube.chapter_generator import ChapterGenerator

gen = ChapterGenerator(backend="ollama")  # or "openrouter"
chapters = gen.generate_chapters(
    title="Session 042",
    transcript_segments=segments,
    total_duration_seconds=5400.0,  # authoritative, from the manifest
)
```

### 5. Chapter Caches (`data/input/`)

| File | Source | Format |
| :--- | :--- | :--- |
| `video_chapters.json` | YouTube (creator/auto chapters via yt-dlp) | `{video_id: [{start, title}, ...]}` — plain lists are YouTube-sourced by definition |
| `video_chapters_llm.json` | LLM (gemma3:4b, Aug 2026 batch) | `{video_id: {source: "llm", model, generated_at, chapters: [...]}}` — every payload carries `{source, model, generated_at}` provenance |

Rules:

- The 267 YouTube-authored lists (restored from commit `3a33326`) are
  trusted as-is; **never overwrite them with LLM output**. LLM generation
  must write to `video_chapters_llm.json` only
  (`save_generated_chapters()` refuses YouTube-sourced targets).
- `enrich_metadata.py` seeds journal `sessions[]` only from YouTube-sourced
  lists or LLM lists that pass `validate_chapters` with the part's
  duration; unprovenanced cache entries are never seeded.
