# tests/journal_utilities/ingest

Tests for [`journal_utilities.ingest`](../../../src/journal_utilities/ingest/).

| File | Covers |
| --- | --- |
| `test_ytdlp.py` | Secret-free enumeration: flat manifest → worklist delta + evidence. |
| `test_enumerate.py` | Data API enumeration path. |
| `test_scaffold_diff.py` | Per-item scaffold emission and channel-vs-manifest-vs-INDEX diffing. |
| `fake_service.py` | In-memory fake of the enumeration/API service used by the tests. |

No API key or network is required. Run:

```bash
uv run pytest tests/journal_utilities/ingest/ -q
```

Part of the suite described in [`../../README.md`](../../README.md).
