# Privacy Policy

_Last updated: 2026-09-24. Applies to Journal Utilities (`github.com/ActiveInferenceInstitute/Journal_Utilities`) and every artifact it produces for the [Active Inference Journal](https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal) — the transcript corpus, the static Pages site, and the YouTube metadata/captions write-back (channel `@ActiveInference`)._

## The short version

Journal Utilities processes **publicly published content of the Active Inference Institute** — its own videos, livestreams, transcripts, and captions. It does **not** collect, profile, track, or advertise to anyone. It runs on Institute infrastructure or contributor machines; it has no multi-user service, no accounts, and no analytics of persons.

## What the pipeline processes

| Data | Source | Where it goes |
| --- | --- | --- |
| Video metadata (title, description, upload date, duration, chapters, tags) | YouTube Data API v3 — the Institute's own channel (`UCbPq2w41ZaJSWtpCq4BE6Dg`) | `data/output/*.json` working files, journal `metadata.json`, YouTube descriptions/playlists on write-back |
| Spoken audio from Institute videos | Institute's own published videos | Machine transcripts (WhisperX diarization) → `transcript.json`, derived caption SRTs |
| Existing YouTube captions | Institute's own videos | `captions/` in the journal item |
| Speaker labels | Diarization + human curation (guests are public presenters of Institute events) | `transcript.json` speaker fields, `metadata.json` `guests` |
| Credentials | Operator-provided (`YOUTUBE_API_KEY`, OAuth token for the Institute admin account) | Environment variables / local untracked files — **never committed, never logged** |

## What we do not do

- No third-party personal data is collected. Everything processed originates from the Institute's own public channel and publications.
- No cookies, advertising identifiers, tracking pixels, or telemetry are embedded in the pipeline, the generated journal site, or YouTube write-back content.
- No data is sold, shared, or transferred to advertisers or data brokers.
- No user comments, DMs, emails, or private messages are ingested by the pipeline.
- No financial data passes through this repo (Institute finances are a separate system).

## Personal data that appears legitimately

Public names of **speakers, guests, and Institute staff** appear in transcripts and metadata because those people presented in the processed public videos (e.g. guest lecture names already shown in the video itself). Corrections or removal requests from a named individual are honored: file an issue on either repo or contact `admin@activeinference.institute`, and the reference is corrected or removed from the journal and queued for YouTube re-sync.

## YouTube Data API usage

- The API key used for enumeration/audit is **restricted to YouTube Data API v3** and used only against the Institute's own channel and videos.
- Quota use is deliberate and small (a weekly enumerate run ≈ 32 units; a description correction ≈ 50 units/video; a caption upload ≈ 400 units).
- **Reads** (enumerate, audit) require only the API key. **Writes** (captions, descriptions, playlists) additionally require an OAuth grant scoped `youtube.force-ssl`, owned by the Institute admin account (`admin@activeinference.institute`). The OAuth token is stored locally on the machine running the write (untracked path), never in the repo.
- The [YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/developer-policies) apply to this usage; this pipeline discloses that it sends video IDs and reads/writes only Institute-owned content metadata.

## Local operator privacy

The repo's `.env` and the cached OAuth token file (`.youtube_token.json`) are
gitignored and excluded from the secret baseline — never committed, never
published. Generated bulk artifacts under `data/output/` are working state and
never published; only curated journal content reaches the public site. The
experimental RAG/chat stack (`rag` extra) binds to `127.0.0.1` and is intended
for local use; it has no public endpoint.

## Data retention

- Journal content (metadata, transcripts, captions, translations) is retained indefinitely as a **CC-BY-4.0** public research corpus, with per-file provenance (`previous_paths`, `{source, model, generated_at}`) recorded in `metadata.json`.
- Machine-local working files (`data/output/*.json`, `yt_backup/`, logs) are
reproducible intermediate state and are never published; they can be deleted at
any time without harming the journal.

## Changes

Material changes to this policy ship in the same PR as the change that causes them, per the repo's commit conventions.
