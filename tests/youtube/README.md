# tests/youtube

Tests for the YouTube Data API + captions surface under
[`journal_utilities/youtube/`](../../src/journal_utilities/youtube/) (and the
`youtube/client.py` helper package).

| File | Covers |
| --- | --- |
| `test_client.py` | Data API client, request bounding/timeouts, quota costs. |
| `test_captions.py` | Caption listing / transcript retrieval paths. |
| `test_upload_captions.py` | Caption upload path and its guards. |
| `test_url_resolution.py` | YouTube URL → video-id resolution. |

API calls are mocked or gated behind credentials; no live network is required. Run:

```bash
uv run pytest tests/youtube/ -q
```

Part of the suite described in [`../README.md`](../README.md).
