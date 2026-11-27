# YouTube Channel Download

Download **transcripts**, **audio**, and **video** from all videos on the [Active Inference YouTube channel](https://www.youtube.com/channel/UCbPq2w41ZaJSWtpCq4BE6Dg).

## Enhancements (2025-2026)

- **Cookie Support**: Use browser cookies (`--cookies-from-browser chrome`) to bypassing YouTube's strict rate limiting and sign-in walls.
- **User-Agent Simulation**: Automates User-Agent rotation to mimic real browsers, reducing 403 Forbidden errors.
- **Robust Fallback**: Download strategy: `web` -> `ios` -> `android` -> `default` clients to ensure success even if one client is blocked.

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Enumerate all channel videos
uv run python scripts/download_channel.py --enumerate-only

# Download transcripts with resume
# (Recommended: Use --cookies-from-browser to avoid 403s)
uv run python scripts/download_channel.py --transcripts --audio --resume --cookies-from-browser chrome
```

## Troubleshooting: 403 Forbidden Errors

If you encounter `HTTP Error 403: Forbidden`, YouTube is blocking your IP or client.

**Solutions:**

1. **Use Cookies**: Ensure you are logged into YouTube in Chrome (or Firefox/Safari) and run with `--cookies-from-browser chrome`.
2. **Update yt-dlp**: Run `uv pip install -U yt-dlp` to get the latest extractors.
3. **Slow Down**: Use `--delay 5` or `--delay 10` to reduce request rate.
4. **Wait**: YouTube temp-bans usually expire in 1-24 hours.

## Architecture

```text
src/journal_utilities/
├── youtube/
│   └── channel.py        # Channel video enumeration via yt-dlp (flat playlist)
├── download/
│   └── downloader.py     # Per-video download engine with fallback logic
└── youtube/
    └── youtube.py        # YouTube URL handling
```

### `downloader.py` Strategy

1. **Transcript**:
    - Attempt `yt-dlp` (subtitles).
    - Fallback to `youtube_transcript_api` (unofficial API).
2. **Audio**:
    - Attempt download with `hls`, `dash`, and `http` protocols.
    - Rotate clients: `web` -> `ios` -> `android`.
    - **User-Agent**: Spoofs a modern browser (e.g., Windows 10 Chrome) to avoid bot detection.

## CLI Usage

| Flag | Description | Recommendation |
| :--- | :--- | :--- |
| `--cookies-from-browser` | Browser to extract cookies from | `chrome` or `firefox` |
| `--transcripts` | Download subtitles | Always use |
| `--audio` | Download audio (mp3/m4a) | Optional, for podcast/ASR |
| `--resume` | Skip existing files | Always enable for large channels |
| `--delay` | Seconds between requests | `2.0` - `5.0` |

```bash
# Full download command
uv run python scripts/download_channel.py \
    --transcripts \
    --audio \
    --resume \
    --cookies-from-browser chrome \
    --delay 2
```
