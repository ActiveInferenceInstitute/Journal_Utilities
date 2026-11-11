# journal_utilities.ingest

Weekly **channel ingest** helpers: secret-free enumeration, journal diffing, and
per-item `metadata.json` scaffolds for new videos. Every step is read-only by
default (dry-run is the default; files are written only behind an explicit
opt-in) and the module never writes to YouTube.

| Module | Purpose |
| --- | --- |
| `ytdlp.py` | Secret-free weekly enumeration: flat `yt-dlp` channel manifest → new-video delta → one full per-video extraction (privacy/broadcast evidence). No API key, no quota. |
| `enumerate.py` | Data API alternative to `ytdlp.py` (`playlistItems.list` + `videos.list`); needs `YOUTUBE_API_KEY` and spends quota. Read-only. |
| `scaffold.py` | Emits one scaffold per new item under the journal's `data/video/activeinferenceinstitute/<Series>/<Series_NNN>/` layout; never overwrites an existing `metadata.json`. |
| `diff.py` | Quota-free channel-vs-manifest-vs-`INDEX.json` reconciliation report. |

Workflow, status-evidence rules (including the `unknown` rule) and the journal-side
schedule live in [`../../../docs/m3-ingest.md`](../../../docs/m3-ingest.md).

Part of [Journal-Utilities](../../../README.md). See [`../../../docs/README.md`](../../../docs/README.md).
