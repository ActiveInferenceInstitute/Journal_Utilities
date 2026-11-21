# English YouTube captions

Generate and review an English SubRip file from the Journal video's WhisperX
`transcript.json`. The renderer uses word timings where they align with the
transcript and falls back to segment timing when alignment is incomplete. It
breaks cues at sentence and speaker boundaries, adds `>> Name:` at speaker
changes, and wraps to at most two lines of 42 characters. Use the reviewed
names in `metadata.json` under `parts[].speakers` for diarization labels and
repeat `--fix "OLD=NEW"` for explicit names spoken in the transcript. The
built-in spelling corrections cover Karl Friston, Iain McGilchrist, and
Darius Parvizi-Wayne.

```sh
uv run python scripts/whisperx_to_srt.py /path/to/Journal-item \
  --video-id VIDEO_ID --out /path/to/review/VIDEO_ID.en.srt
```

Select the exact YouTube video for multi-part items. The preview prints the
new file's SHA-256 and leaves the item untouched. Review the cue text, speaker
changes, timing, and name spelling. Use the same name corrections for preview
and upload. English captions give YouTube the source for automatic
translations.

Generate a candidate worklist in the order **Insights → ModelStream 001 →
top 100 remaining by known views with a matching transcript → remaining
items**. A downloaded SRT is informational. Live English track inventory
determines whether a video already has reviewed captions.
When locally saved view counts are missing, add `--fetch-views` and run
`uv run --extra youtube` with an authorized Data API key to fill the read-only cache.

```sh
uv run python scripts/captions_worklist.py --journal /path/to/ActiveInferenceJournal \
  --out /path/to/review/candidates.csv
uv run --extra youtube python scripts/upload_captions.py --journal /path/to/ActiveInferenceJournal \
  --worklist /path/to/review/approved.csv
```

Copy only approved candidates to `approved.csv`. An optional `srt_sha256`
column pins each row to the exact reviewed bytes. The upload command previews
only by default. Add `--apply` after review to authorize English inserts from
that CSV. The writer checks the OAuth channel, current video ownership and
public visibility, and matching English audio and description language tags.
An existing human English track, including a draft, requires owner review.
The workflow uses the API's video and caption fields. [Video resource](https://developers.google.com/youtube/data/reference/rest/v3/videos) [Caption resource](https://developers.google.com/youtube/data/reference/rest/v3/captions)

A candidate consumes 1 quota unit for video metadata and 50 for track
inventory. Each insert attempt costs 400 more. With the channel identity check,
22 attempts fit within the default 10,000-unit budget if every candidate is
eligible. Track checks for skipped candidates also spend quota. The local
budget applies per invocation and must be coordinated with other work using
the same cloud project. [Quota costs](https://developers.google.com/youtube/v3/determine_quota_cost)

The writer backs up the current track list and Journal metadata before upload.
Successful inserts are recorded by video ID and SRT digest in the gitignored
`data/output/captions_uploaded.jsonl`, with the API track ID and backup path.
The Journal item also receives the `captions_uploaded` provenance record.
Reuse the same local receipts file for retries and check the receipt before
reconciling any metadata conflict. Keep credentials in the configured local
OAuth store. [YouTube authentication and operations](youtube.md)
