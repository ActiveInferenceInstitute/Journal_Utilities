#!/usr/bin/env python3
"""
Transcribe missing journal items with WhisperX + speaker diarization —
journal-driven, no database.

The worklist is derived from the journal repo exactly like
transcription_status.py: an item needs transcription when it lacks
transcript.txt (future-dated/scheduled items are skipped). For each part
video: download a WAV (cookie-free yt-dlp), transcribe + diarize with the
existing TranscriptionService, then write speaker-labeled transcript.txt
(and transcript.json) into the journal item — "## <video_id>" sections for
multi-part items. Speaker labels are SPEAKER_NN; mapping them to names
remains the human step (edit the journal file directly — it is canonical).

Resumable: WAVs and per-video WhisperX outputs are cached in --work-dir and
skipped on re-run; items whose parts are all cached just get journal writes.

Usage:
    python scripts/transcribe_worklist.py                 # dry run: show plan
    python scripts/transcribe_worklist.py --run           # transcribe everything
    python scripts/transcribe_worklist.py --run --max-videos 2
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from dotenv import load_dotenv  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("transcribe_worklist")

SRC_PREFIX = "data/video/activeinferenceinstitute"


def load_private_ids(journal: Path) -> set[str]:
    """Video ids registered as private/unlisted — excluded from transcription."""
    path = journal / SRC_PREFIX / "private_videos.json"
    if not path.exists():
        return set()
    videos = json.loads(path.read_text(encoding="utf-8")).get("videos", [])
    return {v["video_id"] for v in videos if v.get("video_id")}


def build_worklist(journal: Path, excluded: list = None) -> list[dict]:
    """Items lacking transcript.txt (excluding duplicates and future streams).

    Private/unlisted content is never transcribed: video ids registered in
    private_videos.json are dropped, and items left with no public video are
    appended to ``excluded``.
    """
    from transcription_status import item_status

    excluded = excluded if excluded is not None else []
    private_ids = load_private_ids(journal)
    today = date.today().isoformat()
    work = []
    for meta_path in sorted((journal / SRC_PREFIX).rglob("metadata.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("duplicate_of"):
            continue
        if item_status(meta_path.parent) != "missing":
            continue
        dates = [meta.get("date", "")] + [p.get("date", "") for p in meta.get("parts", [])]
        if max(filter(None, dates), default="") > today:
            continue  # scheduled — nothing to transcribe yet
        rel = str(meta_path.parent.relative_to(journal / SRC_PREFIX))
        vids = [
            p["video_id"]
            for p in meta.get("parts", [])
            if p.get("video_id") and p["video_id"] not in private_ids
        ]
        if vids:
            work.append({"rel": rel, "dir": meta_path.parent, "vids": vids})
        else:
            excluded.append(rel)
    return work


def download_wav(vid: str, wav_dir: Path) -> Path:
    wav = wav_dir / f"{vid}.wav"
    if wav.exists():
        logger.info("wav cached: %s", wav.name)
        return wav
    logger.info("downloading audio: %s", vid)
    subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format",
            "wav",
            "-o",
            str(wav_dir / f"{vid}.%(ext)s"),
            "--",
            f"https://www.youtube.com/watch?v={vid}",
        ],
        check=True,
    )
    if not wav.exists():
        raise FileNotFoundError(f"yt-dlp did not produce {wav}")
    return wav


def write_journal_transcript(item_dir: Path, vids: list[str], out_dir: Path) -> None:
    """Assemble journal transcript.txt/.json from cached per-video outputs."""
    sections, seg_blocks = [], []
    for vid in vids:
        txt = (out_dir / f"{vid}.simple.txt").read_text(encoding="utf-8").strip()
        sections.append(txt if len(vids) == 1 else f"## {vid}\n\n{txt}")
        segments = json.loads((out_dir / f"{vid}.simple.json").read_text(encoding="utf-8"))
        seg_blocks.append({"video_id": vid, "segments": segments})
    (item_dir / "transcript.txt").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    (item_dir / "transcript.json").write_text(
        json.dumps(seg_blocks, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--journal", type=Path, default=REPO.parent / "ActiveInferenceJournal")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=REPO / "data/output/whisperx",
        help="cache for WAVs and per-video WhisperX outputs",
    )
    parser.add_argument("--run", action="store_true", help="transcribe (default: dry-run plan)")
    parser.add_argument("--max-videos", type=int, default=0, help="bound this run")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument(
        "--compute-type", default="float16", help="float16, or int8 if low on GPU memory"
    )
    args = parser.parse_args()

    load_dotenv(REPO / ".env")
    import os

    excluded: list = []
    worklist = build_worklist(args.journal, excluded)
    total_vids = sum(len(w["vids"]) for w in worklist)
    print(f"worklist: {len(worklist)} items / {total_vids} videos")
    for w in worklist:
        cached = sum(1 for v in w["vids"] if (args.work_dir / f"{v}.simple.txt").exists())
        print(f"  {w['rel']}  ({len(w['vids'])} video(s), {cached} cached)")
    if excluded:
        print(f"excluded ({len(excluded)} items — private/unlisted, no transcription by policy):")
        for rel in excluded:
            print(f"  {rel}")
    if not args.run:
        print("\ndry run — pass --run to transcribe")
        return 0
    if not worklist:
        return 0

    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not hf_token:
        logger.error("HF_TOKEN/HUGGINGFACE_TOKEN missing from .env — required for diarization")
        return 1

    args.work_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = args.work_dir / "wav"
    wav_dir.mkdir(exist_ok=True)

    # ctranslate2 dlopens cuDNN by soname; pip-installed nvidia wheels are not
    # on the loader path, so preload them (RTLD_GLOBAL) or the whisper encoder
    # aborts with "Unable to load libcudnn_cnn.so.9".
    import ctypes
    import site

    for sp in site.getsitepackages():
        for pattern in ("nvidia/cublas/lib/libcublas*.so*", "nvidia/cudnn/lib/libcudnn*.so.9"):
            for lib in sorted(Path(sp).glob(pattern)):
                try:
                    ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass

    # Heavy import deferred so dry runs work without GPU deps loaded.
    from journal_utilities.transcribe.transcribe import TranscriptionService

    service = None  # lazy: skip model load when everything needed is cached
    done = 0
    for item in worklist:
        try:
            for vid in item["vids"]:
                if (args.work_dir / f"{vid}.simple.txt").exists():
                    logger.info("transcript cached: %s", vid)
                    continue
                if args.max_videos and done >= args.max_videos:
                    print(f"\nreached --max-videos={args.max_videos}; run again to continue")
                    return 0
                wav = download_wav(vid, wav_dir)
                if service is None:
                    logger.info("loading WhisperX models (%s, %s)", args.device, args.compute_type)
                    service = TranscriptionService(
                        hf_token, args.device, args.batch_size, args.compute_type
                    )
                logger.info("transcribing %s (%s)", vid, item["rel"])
                service.transcribe(str(args.work_dir), str(wav))
                done += 1
            if all((args.work_dir / f"{v}.simple.txt").exists() for v in item["vids"]):
                write_journal_transcript(item["dir"], item["vids"], args.work_dir)
                logger.info("journal transcript written: %s", item["rel"])
        except subprocess.CalledProcessError as exc:
            logger.error("audio download failed for %s: %s — skipping item", item["rel"], exc)
        except (OSError, RuntimeError) as exc:
            logger.error("transcription failed for %s: %s — skipping item", item["rel"], exc)

    print("\ndone — review the journal diff, then commit. Remember:")
    print("  1. speaker labels are SPEAKER_NN; map to names by editing the journal files")
    print("  2. regenerate indexes + validate before committing (see SCHEMA.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
