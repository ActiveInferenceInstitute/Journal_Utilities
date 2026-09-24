"""
Per-video download engine for Journal Utilities.

This module provides functionality to download transcripts, audio, and video
for individual YouTube videos using yt-dlp and youtube-transcript-api.
"""

import json
import logging
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class DownloadStatus(str, Enum):
    """Status of an individual download operation."""
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class DownloadResult:
    """Result of a single download operation."""
    video_id: str
    asset_type: str  # "transcript", "audio", "video"
    status: DownloadStatus
    path: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    file_size_bytes: int | None = None

    @property
    def file_size_str(self) -> str:
        """Return human-readable file size."""
        if self.file_size_bytes is None:
            return ""
        size = float(self.file_size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def _get_file_size(path: Path) -> int:
    """Get file size in bytes."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


@dataclass
class VideoDownloadSummary:
    """Summary of all downloads for a single video."""
    video_id: str
    results: list[DownloadResult] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# yt-dlp command builder
# ---------------------------------------------------------------------------


def _ytdlp_base_cmd(
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> list[str]:
    """Build the base yt-dlp command with optional cookies.

    Constructs the common yt-dlp prefix used by transcript, audio,
    and video download helpers.
    """
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--fragment-retries", "3",
        "--retry-sleep", "fragment:exp=1:10",
        # A modern browser User-Agent is required on every yt-dlp call to
        # avoid YouTube 403s (see AGENTS.md) — not just on the audio path.
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    if cookies_file:
        cmd.extend(["--cookies", str(cookies_file)])
    return cmd


# ---------------------------------------------------------------------------
# Transcript download
# ---------------------------------------------------------------------------

def download_transcript(
    video_id: str,
    output_dir: Path,
    languages: list[str] | None = None,
    skip_existing: bool = True,
    cookies_from_browser: str | None = None,
) -> DownloadResult:
    """
    Download video transcript (subtitles).

    Tries strategies in order:
    1. yt-dlp (write-auto-subs)
    2. youtube_transcript_api (fallback)

    Args:
        video_id: YouTube video ID.
        output_dir: Directory to save transcripts.
        languages: List of language codes (default: ["en"]).
        skip_existing: Skip if transcript files already exist.
        cookies_from_browser: Browser to extract cookies from (e.g. "chrome").

    Returns:
        A :class:`DownloadResult` with status and file path.
    """
    output_dir = Path(output_dir)
    transcript_dir = output_dir / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)

    # Check for cookies.txt in the parent dir, then the output dir.
    cookies_file: Path | None = None
    for candidate in (output_dir.parent / "cookies.txt", output_dir / "cookies.txt"):
        if candidate.exists():
            cookies_file = candidate
            break

    if languages is None:
        languages = ["en"]

    # Check existing (simple check for .txt or .json)
    # The clean text function saves as .txt
    txt_path = transcript_dir / f"{video_id}.txt"
    if skip_existing and txt_path.exists():
        size = _get_file_size(txt_path)
        res = DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.SKIPPED,
            path=str(txt_path),
            file_size_bytes=size,
        )
        logger.info("Transcript already exists: %s (%s)", txt_path.name, res.file_size_str)
        return res

    start = time.monotonic()

    # Strategy 1: yt-dlp subtitles
    res = _download_transcript_ytdlp(
        video_id, transcript_dir, languages, cookies_from_browser, cookies_file
    )
    if res.status == DownloadStatus.SUCCESS:
        res.duration_seconds = time.monotonic() - start
        if res.path:
            res.file_size_bytes = _get_file_size(Path(res.path))
            logger.info("Downloaded transcript (yt-dlp): %s (%s)", Path(res.path).name, res.file_size_str)
        return res

    # Strategy 2: youtube-transcript-api fallback
    logger.info("yt-dlp subtitles unavailable for %s, trying youtube_transcript_api", video_id)
    result = _download_transcript_api(video_id, transcript_dir, languages)
    result.duration_seconds = time.monotonic() - start
    return result


def _download_transcript_ytdlp(
    video_id: str,
    transcript_dir: Path,
    languages: list[str],
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> DownloadResult:
    """Download transcript via yt-dlp."""
    url = f"https://www.youtube.com/watch?v={video_id}"

    # yt-dlp's --sub-lang expects comma-separated
    lang_str = ",".join(languages)

    # We use --skip-download because we only want subs
    # --write-sub: write subtitle file
    # --write-auto-sub: write automatically generated subtitle file (YouTube)
    cmd = _ytdlp_base_cmd(cookies_from_browser, cookies_file)
    cmd.extend([
        "--write-sub",
        "--write-auto-sub",
        "--sub-lang", lang_str,
        "--sub-format", "vtt",  # prefer vtt
        "--skip-download",
        "-o", str(transcript_dir / "%(id)s.%(ext)s"),
        url,
    ])

    logger.debug("yt-dlp transcript cmd: %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.FAILED,
            error="yt-dlp subtitle download timed out",
        )

    # yt-dlp doesn't exit with error if no subs found, so we check for file
    # Pattern: video_id.lang.vtt
    found = list(transcript_dir.glob(f"{video_id}.*.vtt"))
    if not found:
        return DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.FAILED,
            error=f"No subtitle files produced. stderr: {proc.stderr[:300]}",
        )

    # Convert the strongest match to text. Prefer a manual subtitle over an
    # auto-generated one so the pick is deterministic (glob order is
    # filesystem-dependent).
    best_file = _pick_transcript_vtt(found)

    try:
        final_path = transcript_dir / f"{video_id}.txt"
        # _convert_vtt_to_text writes the converted text to final_path itself.
        _convert_vtt_to_text(best_file, final_path)
        return DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.SUCCESS,
            path=str(final_path),
        )
    except Exception as e:
        return DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.FAILED,
            error=f"VTT conversion failed: {e}",
        )


def _download_transcript_api(
    video_id: str,
    transcript_dir: Path,
    languages: list[str],
) -> DownloadResult:
    """Download transcript via youtube-transcript-api (fallback).

    Uses the v1.x API: ``YouTubeTranscriptApi()`` instance with
    ``.fetch()`` and ``.list()`` methods.
    """
    try:
        import http.cookiejar

        import requests
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.FAILED,
            error="youtube-transcript-api (or requests) not installed",
        )

    try:
        # Check for cookies.txt in the parent of transcript_dir (i.e. data/output/cookies.txt)
        session = None
        cookies_path = transcript_dir.parent / "cookies.txt"
        if cookies_path.exists():
            try:
                session = requests.Session()
                cj = http.cookiejar.MozillaCookieJar(cookies_path)
                cj.load(ignore_discard=True, ignore_expires=True)
                # MozillaCookieJar is a CookieJar, not a RequestsCookieJar;
                # requests accepts it at runtime, but the types differ.
                session.cookies = cj
                logger.debug("Loaded cookies for transcript API from %s", cookies_path)
            except Exception as e:
                logger.warning("Failed to load cookies from %s: %s", cookies_path, e)
                session = None

        ytt = YouTubeTranscriptApi(http_client=session)
        fetched = ytt.fetch(video_id, languages=languages)

        # Extract text from transcript snippets
        lines = []
        structured = []
        for snippet in fetched:
            text = snippet.text if hasattr(snippet, 'text') else str(snippet)
            if text:
                lines.append(text)
                structured.append({
                    "text": text,
                    "start": getattr(snippet, 'start', 0),
                    "duration": getattr(snippet, 'duration', 0),
                })

        text = "\n".join(lines)

        txt_path = transcript_dir / f"{video_id}.txt"
        txt_path.write_text(text, encoding="utf-8")

        # Also save structured JSON
        json_path = transcript_dir / f"{video_id}.json"
        json_path.write_text(
            json.dumps(structured, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        size = _get_file_size(txt_path)
        res = DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.SUCCESS,
            path=str(txt_path),
            file_size_bytes=size,
        )
        logger.info("Downloaded transcript (API): %s (%s)", txt_path.name, res.file_size_str)
        return res

    except Exception as exc:
        logger.error("youtube-transcript-api failed for %s: %s", video_id, exc)
        return DownloadResult(
            video_id=video_id,
            asset_type="transcript",
            status=DownloadStatus.FAILED,
            error=str(exc),
        )


def _pick_transcript_vtt(files: list[Path]) -> Path:
    """Return the best (deterministic) VTT to convert.

    Prefers a manual subtitle over an auto-generated one (`.auto.`/`.orig.`),
    otherwise falls back to a name-sorted pick so the choice never depends on
    filesystem glob order.
    """
    manual = [p for p in files if ".auto." not in p.name and ".orig." not in p.name]
    pool = manual or files
    return sorted(pool, key=lambda p: p.name)[0]


def _convert_vtt_to_text(vtt_path: Path, txt_path: Path) -> None:
    """Convert a VTT subtitle file to plain text, stripping timestamps and formatting."""
    lines: list[str] = []
    seen: set[str] = set()

    for raw_line in vtt_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        # Skip VTT headers, timestamps, and empty lines
        if (
            not line
            or line.startswith("WEBVTT")
            or line.startswith("Kind:")
            or line.startswith("Language:")
            or line.startswith("NOTE")
            or "-->" in line
            or line.isdigit()
        ):
            continue

        # Remove HTML-like tags (e.g. <c>, </c>, <00:00:01.234>)
        clean = re.sub(r"<[^>]+>", "", line)
        clean = clean.strip()

        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)

    txt_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Audio download
# ---------------------------------------------------------------------------

def download_audio(
    video_id: str,
    output_dir: Path,
    audio_format: str = "mp3",
    skip_existing: bool = True,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> DownloadResult:
    """
    Download audio from a YouTube video.

    Args:
        video_id: YouTube video ID.
        output_dir: Directory to save audio files.
        audio_format: Output format — ``mp3``, ``wav``, or ``m4a``.
        skip_existing: Skip if audio file already exists.
        cookies_from_browser: Browser to extract cookies from.
        cookies_file: Path to a Netscape-format cookies file.

    Returns:
        A :class:`DownloadResult` with status and file path.
    """
    output_dir = Path(output_dir)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Check for cookies.txt
    if cookies_file is None:
        potential_cookies_file = output_dir.parent / "cookies.txt"
        if potential_cookies_file.exists():
            cookies_file = potential_cookies_file
        else:
            potential_cookies_file = output_dir / "cookies.txt"
            if potential_cookies_file.exists():
                cookies_file = potential_cookies_file

    audio_path = audio_dir / f"{video_id}.{audio_format}"

    if skip_existing and audio_path.exists():
        size = _get_file_size(audio_path)
        res = DownloadResult(
            video_id=video_id,
            asset_type="audio",
            status=DownloadStatus.SKIPPED,
            path=str(audio_path),
            file_size_bytes=size,
        )
        logger.info("Audio already exists: %s (%s)", audio_path.name, res.file_size_str)
        return res

    url = f"https://www.youtube.com/watch?v={video_id}"
    start = time.monotonic()

    cmd = _ytdlp_base_cmd(cookies_from_browser, cookies_file)
    cmd.extend([
        "-x",
        "--audio-format", audio_format,
        "--audio-quality", "0",
        "-o", str(audio_dir / "%(id)s.%(ext)s"),
        url,
    ])

    cmd_base = list(cmd)

    try:
        # Attempt 1: Try 'web' player client first (Progressive HTTP preferred)
        cmd_web = list(cmd_base)
        cmd_web.extend(["--extractor-args", "youtube:player_client=web"])
        logger.debug("Attempt 1 (web client): %s", " ".join(cmd_web))

        proc = subprocess.run(cmd_web, check=False, timeout=600)

        if proc.returncode != 0:
            logger.warning("Web client download failed (exit code %d). Falling back to ios client.", proc.returncode)

            # Attempt 2: Fallback to ios client
            cmd_ios = list(cmd_base)
            cmd_ios.extend(["--extractor-args", "youtube:player_client=ios"])
            logger.debug("Attempt 2 (ios client): %s", " ".join(cmd_ios))

            proc = subprocess.run(cmd_ios, check=False, timeout=600)

            if proc.returncode != 0:
                logger.warning("iOS client download failed (exit code %d). Falling back to default client.", proc.returncode)

                # Attempt 3: Fallback to default client (HLS) with abort-on-unavailable
                cmd_default = list(cmd_base)
                cmd_default.append("--abort-on-unavailable-fragments")
                logger.debug("Attempt 3 (default client): %s", " ".join(cmd_default))

                proc = subprocess.run(cmd_default, check=False, timeout=600)

    except subprocess.TimeoutExpired:
        return DownloadResult(
            video_id=video_id,
            asset_type="audio",
            status=DownloadStatus.FAILED,
            error="Audio download timed out",
            duration_seconds=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start

    if proc.returncode != 0:
        logger.error("Audio download failed for %s (exit code %d)", video_id, proc.returncode)
        return DownloadResult(
            video_id=video_id,
            asset_type="audio",
            status=DownloadStatus.FAILED,
            error=f"yt-dlp exited with code {proc.returncode}",
            duration_seconds=elapsed,
        )


    # yt-dlp may write with different extension before conversion
    found = list(audio_dir.glob(f"{video_id}.*"))
    actual_path = str(audio_path) if audio_path.exists() else (str(found[0]) if found else None)

    # A non-zero exit is caught above, but yt-dlp can also exit 0 without
    # producing a file (e.g. output elsewhere, .part only). Never report
    # SUCCESS for a missing/empty artifact.
    size = _get_file_size(Path(actual_path)) if actual_path else 0
    if not actual_path or size <= 0:
        logger.error("Audio download produced no file for %s", video_id)
        return DownloadResult(
            video_id=video_id,
            asset_type="audio",
            status=DownloadStatus.FAILED,
            error="yt-dlp exited 0 but produced no audio file",
            duration_seconds=elapsed,
        )

    logger.info("Downloaded audio: %s in %.1fs", Path(actual_path).name, elapsed)
    res = DownloadResult(
        video_id=video_id,
        asset_type="audio",
        status=DownloadStatus.SUCCESS,
        path=actual_path,
        duration_seconds=elapsed,
        file_size_bytes=size,
    )
    logger.info("  -> %s (%s)", Path(actual_path).name, res.file_size_str)
    return res


# ---------------------------------------------------------------------------
# Video download
# ---------------------------------------------------------------------------

_QUALITY_FORMATS = {
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "720p": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
    "480p": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
    "360p": "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best",
}


def download_video(
    video_id: str,
    output_dir: Path,
    quality: str = "best",
    skip_existing: bool = True,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> DownloadResult:
    """
    Download video from YouTube.

    Args:
        video_id: YouTube video ID.
        output_dir: Directory to save video files.
        quality: Quality preset — ``best``, ``720p``, ``480p``, ``360p``.
        skip_existing: Skip if video file already exists.
        cookies_from_browser: Browser to extract cookies from.
        cookies_file: Path to a Netscape-format cookies file.

    Returns:
        A :class:`DownloadResult` with status and file path.
    """
    output_dir = Path(output_dir)
    video_dir = output_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    # Check for cookies.txt
    if cookies_file is None:
        potential_cookies_file = output_dir.parent / "cookies.txt"
        if potential_cookies_file.exists():
            cookies_file = potential_cookies_file
        else:
            potential_cookies_file = output_dir / "cookies.txt"
            if potential_cookies_file.exists():
                cookies_file = potential_cookies_file

    video_path = video_dir / f"{video_id}.mp4"

    if skip_existing and video_path.exists():
        size = _get_file_size(video_path)
        res = DownloadResult(
            video_id=video_id,
            asset_type="video",
            status=DownloadStatus.SKIPPED,
            path=str(video_path),
            file_size_bytes=size,
        )
        logger.info("Video already exists: %s (%s)", video_path.name, res.file_size_str)
        return res

    url = f"https://www.youtube.com/watch?v={video_id}"
    fmt = _QUALITY_FORMATS.get(quality, _QUALITY_FORMATS["best"])
    start = time.monotonic()

    cmd = _ytdlp_base_cmd(cookies_from_browser, cookies_file)
    cmd.extend([
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", str(video_dir / "%(id)s.%(ext)s"),
        url,
    ])

    logger.debug("yt-dlp video cmd: %s", " ".join(cmd))

    try:
        # Stream output to terminal for user visibility
        proc = subprocess.run(cmd, check=False, timeout=900)
    except subprocess.TimeoutExpired:
        return DownloadResult(
            video_id=video_id,
            asset_type="video",
            status=DownloadStatus.FAILED,
            error="Video download timed out",
            duration_seconds=time.monotonic() - start,
        )

    elapsed = time.monotonic() - start

    if proc.returncode != 0:
        logger.error("Video download failed for %s (exit code %d)", video_id, proc.returncode)
        return DownloadResult(
            video_id=video_id,
            asset_type="video",
            status=DownloadStatus.FAILED,
            error=f"yt-dlp exited with code {proc.returncode}",
            duration_seconds=elapsed,
        )

    found = list(video_dir.glob(f"{video_id}.*"))
    actual_path = str(video_path) if video_path.exists() else (str(found[0]) if found else None)

    size = _get_file_size(Path(actual_path)) if actual_path else 0
    if not actual_path or size <= 0:
        logger.error("Video download produced no file for %s", video_id)
        return DownloadResult(
            video_id=video_id,
            asset_type="video",
            status=DownloadStatus.FAILED,
            error="yt-dlp exited 0 but produced no video file",
            duration_seconds=elapsed,
        )

    logger.info("Downloaded video: %s in %.1fs", Path(actual_path).name, elapsed)
    res = DownloadResult(
        video_id=video_id,
        asset_type="video",
        status=DownloadStatus.SUCCESS,
        path=actual_path,
        duration_seconds=elapsed,
        file_size_bytes=size,
    )
    logger.info("  -> %s (%s)", Path(actual_path).name, res.file_size_str)
    return res


# ---------------------------------------------------------------------------
# Combined download
# ---------------------------------------------------------------------------

def download_all(
    video_id: str,
    output_dir: Path,
    transcripts: bool = True,
    audio: bool = True,
    video: bool = True,
    audio_format: str = "mp3",
    video_quality: str = "best",
    transcript_languages: list[str] | None = None,
    skip_existing: bool = True,
    cookies_from_browser: str | None = None,
) -> VideoDownloadSummary:
    """
    Download transcript, audio, and/or video for a single YouTube video.

    Args:
        video_id: YouTube video ID.
        output_dir: Base output directory.
        transcripts: Whether to download transcripts.
        audio: Whether to download audio.
        video: Whether to download video.
        audio_format: Audio format (``mp3``, ``wav``, ``m4a``).
        video_quality: Video quality preset.
        transcript_languages: Preferred transcript languages.
        skip_existing: Skip files that already exist.

    Returns:
        A :class:`VideoDownloadSummary` with results for each asset type.
    """
    summary = VideoDownloadSummary(video_id=video_id)

    if transcripts:
        result = download_transcript(
            video_id, output_dir,
            languages=transcript_languages,
            skip_existing=skip_existing,
            cookies_from_browser=cookies_from_browser,
        )
        summary.results.append(result)
        logger.info(
            "Transcript for %s: %s%s",
            video_id, result.status.value,
            f" ({result.error})" if result.error else "",
        )

    if audio:
        result = download_audio(
            video_id, output_dir,
            audio_format=audio_format,
            skip_existing=skip_existing,
            cookies_from_browser=cookies_from_browser,
        )
        summary.results.append(result)
        logger.info(
            "Audio for %s: %s%s",
            video_id, result.status.value,
            f" ({result.error})" if result.error else "",
        )

    if video:
        result = download_video(
            video_id, output_dir,
            quality=video_quality,
            skip_existing=skip_existing,
            cookies_from_browser=cookies_from_browser,
        )
        summary.results.append(result)
        logger.info(
            "Video for %s: %s%s",
            video_id, result.status.value,
            f" ({result.error})" if result.error else "",
        )

    return summary


# ---------------------------------------------------------------------------
# Download manifest persistence
# ---------------------------------------------------------------------------

def save_download_manifest(
    summaries: list[VideoDownloadSummary],
    path: Path,
) -> None:
    """Save download summaries to a JSON manifest file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_videos": len(summaries),
        "downloads": [
            {
                "video_id": s.video_id,
                "timestamp": s.timestamp,
                "results": [asdict(r) for r in s.results],
            }
            for s in summaries
        ],
    }

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved download manifest to %s (%d videos)", path, len(summaries))


def load_download_manifest(path: Path) -> list[VideoDownloadSummary]:
    """Load download summaries from a JSON manifest file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    summaries: list[VideoDownloadSummary] = []
    for entry in data.get("downloads", []):
        results = [
            DownloadResult(
                video_id=r["video_id"],
                asset_type=r["asset_type"],
                status=DownloadStatus(r["status"]),
                path=r.get("path"),
                error=r.get("error"),
                duration_seconds=r.get("duration_seconds", 0.0),
            )
            for r in entry.get("results", [])
        ]
        summaries.append(
            VideoDownloadSummary(
                video_id=entry["video_id"],
                results=results,
                timestamp=entry.get("timestamp", ""),
            )
        )

    logger.info("Loaded download manifest from %s (%d videos)", path, len(summaries))
    return summaries
