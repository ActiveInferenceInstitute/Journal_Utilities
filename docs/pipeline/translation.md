# Subtitle Translation Module

The translation pipeline converts the journal's English caption SRTs
(`captions/*.srt`) into the 11 target languages, writing one SRT per language
per item into `translations/` (see `JOURNAL_SCHEMA.md`).

## Target languages

| Code | Language | Model (default) |
| :--- | :--- | :--- |
| `es` `fr` `de` `pt` `it` `nl` `ru` | Western European/Russian | `openai/gpt-4o-mini` |
| `ja` `ko` `zh-Hans` `zh-Hant` | CJK | `openai/gpt-4o-mini` |

Both engines preserve SRT index, timing lines, and CRLF line endings, and keep
brand/proper nouns verbatim (e.g. `Active Inference Institute`, `pymdp`,
`YouTube`).

## Engines

### Local vs hosted

The local-Ollama engine (`translate_subtitles.py`) was removed on 2026-08-23; the hosted OpenRouter engine is now the only supported translator.

### Hosted (OpenRouter) — sole supported engine — `scripts/translate_subtitles_openrouter.py`

Fast batch translator for large corpora. Two speedups over the local path:
(1) many subtitle cues are translated per HTTP request (batching), and (2)
requests run concurrently against a hosted API instead of a serialized local GPU.

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
python3 scripts/translate_subtitles_openrouter.py --journal ../ActiveInferenceJournal   # all series
python3 scripts/translate_subtitles_openrouter.py --journal ../ActiveInferenceJournal --series GuestStream
python3 scripts/translate_subtitles_openrouter.py --journal ../ActiveInferenceJournal --lang es --lang fr
python3 scripts/translate_subtitles_openrouter.py --journal ../ActiveInferenceJournal --force
```

Tuning flags:

| Flag | Default | Meaning |
| :--- | :--- | :--- |
| `--model` | `openai/gpt-4o-mini` | OpenRouter model id |
| `--batch` | 60 | cues per request |
| `--workers` | 8 | concurrent requests |
| `--force` | off | re-translate languages that already exist |
| `--limit` / `--skip-to` | 0 | cap / resume a run |

Environment: `OPENROUTER_API_KEY` (required — export it, or set it in the
repo's gitignored `.env`), `OPENROUTER_BASE_URL` (default
`https://openrouter.ai/api/v1`).

Robustness: per-request retry with exponential backoff, and a failed/truncated
large batch is recursively split in half down to single cues (so long
multi-line cues translate instead of falling back to English).

Placeholder safety: caption files whose exact bytes appear under several
different item folders (copied placeholders) are detected via a content-md5
scan, skipped, and reported — they are never translated.

## Reproducible / idempotent design

Both engines share the same contract:

- **Deterministic ordering** — caption files are enumerated in sorted path order.
- **Stable filenames** — `translations/<title>.<lang>.srt` derived from the
  source caption name (drops `.en`/`.m4a` suffixes).
- **Skip-existing** — an existing `<lang>.srt` is left untouched unless
  `--force`, and output is written atomically per file.
- **Resumable** — interrupt at any point and re-run the same command; it
  continues from where translation output was missing (optionally `--skip-to`).
- **Preserves source shape** — index + timing + CRLF reproduced verbatim, so the
  journal `JOURNAL_SCHEMA.md` `translations/` requirement is met.

## Filename mapping

The translation filename is derived from the source caption filename:

| Source caption | Translation |
| :--- | :--- |
| `My Video.en.srt` | `My Video.<lang>.srt` |
| `My Video.m4a.srt` | `My Video.<lang>.srt` |
| `My Video.en(ca).srt` | `My Video.en(ca).<lang>.srt` |
