# Transcription Module

The Transcription module (`src/journal_utilities/transcribe/`) provides two distinct engines for converting audio to text, optimized for different hardware architectures.

## Architecture

| Engine | File | Hardware | Features |
| :--- | :--- | :--- | :--- |
| **MLX-Whisper** | `transcriber.py` | Apple Silicon (M1/M2/M3) | Fast, local, low-memory, timestamps |
| **WhisperX** | `transcribe.py` | NVIDIA GPU (CUDA) | Speaker diarization, word-level alignment, batching |

## 1. Local Transcription (MLX-Whisper)

Designed for local development on macOS. It serves as a fallback when YouTube captions are unavailable.

### Usage (Local)

```bash
# Transcribe all missing audio files
uv run python scripts/transcribe_missing.py

# Transcribe specific files
uv run python scripts/transcribe_missing.py --max-files 5 --model mlx-community/whisper-large-v3-turbo
```

### Implementation Details (`transcriber.py`)

- **Model**: Defaults to `mlx-community/whisper-large-v3-turbo`.
- **Logic**:
    1. Enumerates audio files in `data/output/audio/`.
    2. Checks if a corresponding `.txt` exists in `data/output/transcripts/`.
    3. Transcribes missing files using `mlx_whisper.transcribe()`.
    4. Saves result as plaintext.

## 2. GPU Transcription (WhisperX)

Designed for production-grade transcription with speaker identification (diarization)
and word-level alignment. Journal transcripts produced here follow the raw-vs-derived
design — `transcript.json` keeps machine `SPEAKER_NN` labels forever; human names live
only in `metadata.json` `parts[].speakers` (see [`JOURNAL_SCHEMA.md`](../reference/JOURNAL_SCHEMA.md)).

### Requirements

- NVIDIA GPU with CUDA 12+
- HuggingFace Token (for `pyannote/speaker-diarization-3.1`)

### Usage (GPU)

The journal workflow is driven by `scripts/transcribe_worklist.py` (GPU, resumable,
dry-run plan by default; add `--run` to transcribe):

```bash
# Plan which items still need WhisperX + diarization (dry run)
uv run python scripts/transcribe_worklist.py

# Run WhisperX transcription + diarization for items missing transcripts
uv run python scripts/transcribe_worklist.py --run
```

(`make transcribe` runs the **local** `mlx-whisper` pipeline instead —
`scripts/transcribe_missing.py` — see "Local Transcription" above.)

### Architecture (`transcribe.py`)

The `TranscriptionService` class orchestrates a complex pipeline:

1. **Transcription**: `whisperx.load_model("large-v3")` converts audio to text.
2. **Alignment**: Aligns inaccurate Whisper timestamps using a wav2vec2 model.
3. **Diarization**: Uses `pyannote.audio` to identify "Speaker A", "Speaker B", etc.
4. **Assignment**: Assigns speakers to word segments.
5. **Output**:
    - `.json`: Full Word-level data with timestamps and speakers.
    - `.simple.json`: Simplified segment list.
    - `.txt`: Human-readable transcript with speaker labels.

### Configuration

Environment variables controls behavior:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `HF_TOKEN` | HuggingFace Access Token | Required |
| `BATCH_SIZE` | GPU inference batch size | `48` |
| `COMPUTE_TYPE` | Precision (`float16`, `int8`) | `float16` |
