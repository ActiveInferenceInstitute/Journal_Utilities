"""
Data loader and search index for the Active Inference Institute interface.

Loads video metadata from download manifests, indexes transcript text
for full-text search, and integrates with the event categorizer.
"""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from journal_utilities.youtube.categorizer import categorize_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class VideoRecord:
    """Unified video record combining manifest + transcript data."""

    id: str
    title: str = ""
    upload_date: str = ""
    duration: float | None = None
    description: str = ""
    view_count: int | None = None
    category: str | None = None
    series: str | None = None
    episode: str | None = None
    transcript_path: str | None = None
    transcript_size: int | None = None
    audio_path: str | None = None
    audio_size: int | None = None
    has_transcript: bool = False
    has_audio: bool = False

    @property
    def youtube_url(self) -> str:
        """YouTube watch URL."""
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def thumbnail_url(self) -> str:
        """YouTube thumbnail URL (medium quality)."""
        return f"https://img.youtube.com/vi/{self.id}/mqdefault.jpg"

    @property
    def thumbnail_hq_url(self) -> str:
        """YouTube thumbnail URL (high quality)."""
        return f"https://img.youtube.com/vi/{self.id}/hqdefault.jpg"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "upload_date": self.upload_date,
            "duration": self.duration,
            "description": self.description,
            "view_count": self.view_count,
            "category": self.category,
            "series": self.series,
            "episode": self.episode,
            "has_transcript": self.has_transcript,
            "has_audio": self.has_audio,
            "transcript_size": self.transcript_size,
            "audio_size": self.audio_size,
            "youtube_url": self.youtube_url,
            "thumbnail_url": self.thumbnail_url,
        }


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A search match with snippet context."""

    video_id: str
    score: float
    snippet: str = ""


class SearchIndex:
    """Simple inverted index for full-text search across transcripts."""

    def __init__(self) -> None:
        self._index: dict[str, set[str]] = defaultdict(set)  # term -> video_ids
        self._transcripts: dict[str, str] = {}  # video_id -> full text
        self._doc_lengths: dict[str, int] = {}

    def add_document(self, video_id: str, text: str) -> None:
        """Index a transcript."""
        self._transcripts[video_id] = text
        tokens = self._tokenize(text)
        self._doc_lengths[video_id] = len(tokens)
        for token in set(tokens):
            self._index[token].add(video_id)

    def search(self, query: str, limit: int | None = 20) -> list[SearchResult]:
        """Search for videos matching a query.

        Args:
            query: Search text.
            limit: Max results, or ``None``/``0`` for all ranked results (used
                to report an accurate total for pagination).
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Score by number of matching terms + term frequency
        scores: dict[str, float] = defaultdict(float)
        for token in query_tokens:
            matching_ids = self._index.get(token, set())
            idf = 1.0 / (1.0 + len(matching_ids))  # inverse document frequency
            for vid in matching_ids:
                scores[vid] += idf

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        if limit:
            ranked = ranked[:limit]

        results = []
        for video_id, score in ranked:
            snippet = self._extract_snippet(video_id, query_tokens)
            results.append(SearchResult(video_id=video_id, score=score, snippet=snippet))

        return results

    def get_transcript(self, video_id: str) -> str | None:
        """Get the full transcript text for a video."""
        return self._transcripts.get(video_id)

    def get_context_chunks(
        self, query: str, top_k: int = 3, chunk_size: int = 2000
    ) -> list[dict[str, Any]]:
        """Get relevant transcript chunks for RAG context."""
        results = self.search(query, limit=top_k)
        chunks = []
        for result in results:
            text = self._transcripts.get(result.video_id, "")
            # Find the best chunk around query terms
            chunk = self._find_best_chunk(text, self._tokenize(query), chunk_size)
            chunks.append({"video_id": result.video_id, "text": chunk, "score": result.score})
        return chunks

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenizer: lowercase, split on non-alphanumeric."""
        # >=2 (not >2) so the /api/search min_length=2 boundary and this
        # tokenizer agree — otherwise 2-char queries (e.g. "AI") return nothing.
        return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 2]

    def _extract_snippet(self, video_id: str, query_tokens: list[str], length: int = 200) -> str:
        """Extract a snippet containing query terms."""
        text = self._transcripts.get(video_id, "")
        if not text:
            return ""
        text_lower = text.lower()

        # Find the first occurrence of any query token
        best_pos = len(text)
        for token in query_tokens:
            pos = text_lower.find(token)
            if 0 <= pos < best_pos:
                best_pos = pos

        if best_pos >= len(text):
            return text[:length] + "..." if len(text) > length else text

        start = max(0, best_pos - 40)
        end = min(len(text), start + length)
        snippet = text[start:end].strip()

        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet

    def _find_best_chunk(self, text: str, query_tokens: list[str], chunk_size: int) -> str:
        """Find the chunk of text most relevant to query tokens."""
        if len(text) <= chunk_size:
            return text

        text_lower = text.lower()
        best_pos = 0
        best_count = 0

        # Sliding window to find densest region. The final window is included
        # so a dense region at the very end of a long transcript isn't missed.
        step = chunk_size // 4
        last_start = max(0, len(text) - chunk_size)
        for pos in range(0, last_start + 1, step):
            window = text_lower[pos : pos + chunk_size]
            count = sum(window.count(t) for t in query_tokens)
            if count > best_count:
                best_count = count
                best_pos = pos

        return text[best_pos : best_pos + chunk_size]


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------


class DataLoader:
    """Loads and indexes all project data for the web interface."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or self._find_data_dir()
        self.project_root = self._find_project_root()
        self.videos: dict[str, VideoRecord] = {}
        self.categories: dict[str, list[str]] = defaultdict(list)  # category -> video_ids
        self.search_index = SearchIndex()
        self._loaded = False

    @staticmethod
    def _find_project_root() -> Path:
        """Locate the project root by searching for pyproject.toml."""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "pyproject.toml").exists():
                return parent
        return Path.cwd()

    def _find_data_dir(self) -> Path:
        """Locate the data directory relative to the project root."""
        # Walk up from this file to find the project root
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent / "data" / "output"
            if candidate.is_dir():
                return candidate
            # Also check for data/ directly
            candidate2 = parent / "data"
            if candidate2.is_dir() and (candidate2 / "output").is_dir():
                return candidate2 / "output"
        # Fallback
        return Path("data/output")

    def load(self) -> None:
        """Load all data: manifest, transcripts, categories."""
        if self._loaded:
            return

        logger.info("Loading data from %s", self.data_dir)

        # Load channel video metadata (titles, durations, etc.)
        channel_videos = self.data_dir / "channel_videos.json"
        if channel_videos.exists():
            self._load_channel_videos(channel_videos)

        # Load download manifest
        download_manifest = self.data_dir / "download_manifest.json"
        if download_manifest.exists():
            self._load_download_manifest(download_manifest)

        # Scan for transcripts not in manifest
        self._scan_transcripts()

        # Categorize all videos
        self._categorize_videos()

        # Build search index
        self._build_search_index()

        self._loaded = True
        logger.info(
            "Loaded %d videos (%d with transcripts, %d with audio, %d categories)",
            len(self.videos),
            sum(1 for v in self.videos.values() if v.has_transcript),
            sum(1 for v in self.videos.values() if v.has_audio),
            len(self.categories),
        )

    def _load_channel_videos(self, path: Path) -> None:
        """Load video metadata from channel_videos.json."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            videos_list = data.get("videos", []) if isinstance(data, dict) else data
            for v in videos_list:
                vid = v.get("id", "")
                if not vid:
                    continue
                self.videos[vid] = VideoRecord(
                    id=vid,
                    title=v.get("title", ""),
                    upload_date=v.get("upload_date", ""),
                    duration=v.get("duration"),
                    description=v.get("description", ""),
                    view_count=v.get("view_count"),
                )
            logger.info("Loaded %d videos from channel_videos.json", len(self.videos))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load channel_videos.json: %s", exc)

    def _load_download_manifest(self, path: Path) -> None:
        """Load asset info from download manifest."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("downloads", []):
                vid = entry.get("video_id", "")
                if not vid:
                    continue

                # Create record if not from channel manifest
                if vid not in self.videos:
                    self.videos[vid] = VideoRecord(id=vid)

                record = self.videos[vid]
                for result in entry.get("results", []):
                    asset_type = result.get("asset_type", "")
                    status = result.get("status", "")
                    rpath = result.get("path")

                    if asset_type == "transcript" and status in ("success", "skipped") and rpath:
                        # Resolve path relative to project root
                        abs_path = self._resolve_path(rpath)
                        if abs_path and abs_path.exists():
                            record.transcript_path = str(abs_path)
                            record.transcript_size = result.get("file_size_bytes")
                            record.has_transcript = True

                    elif asset_type == "audio" and status in ("success", "skipped") and rpath:
                        abs_path = self._resolve_path(rpath)
                        if abs_path and abs_path.exists():
                            record.audio_path = str(abs_path)
                            record.audio_size = result.get("file_size_bytes")
                            record.has_audio = True

            logger.info("Processed download manifest (%d entries)", len(data.get("downloads", [])))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load download manifest: %s", exc)

    def _resolve_path(self, relative_path: str) -> Path | None:
        """Resolve a manifest-relative path to absolute."""
        # Paths in manifest are like "data/output/transcripts/ABC.txt"
        candidate = self.project_root / relative_path
        if candidate.exists():
            return candidate
        # Fallback: try relative to data_dir parent
        candidate = self.data_dir.parent.parent / relative_path
        if candidate.exists():
            return candidate
        return None

    def _scan_transcripts(self) -> None:
        """Scan transcript directory for files not in manifest."""
        transcript_dir = self.data_dir / "transcripts"
        if not transcript_dir.is_dir():
            return

        for txt_file in transcript_dir.glob("*.txt"):
            vid = txt_file.stem
            if vid not in self.videos:
                self.videos[vid] = VideoRecord(id=vid)

            record = self.videos[vid]
            if not record.has_transcript:
                record.transcript_path = str(txt_file)
                record.transcript_size = txt_file.stat().st_size
                record.has_transcript = True

    def _categorize_videos(self) -> None:
        """Categorize all videos using the event categorizer."""
        for vid, record in self.videos.items():
            if record.title:
                cat, series, episode = categorize_name(record.title, is_unique_event_name=False)
                record.category = cat
                record.series = series
                record.episode = episode
                if cat:
                    self.categories[cat].append(vid)

    def _build_search_index(self) -> None:
        """Index all transcripts for search."""
        indexed = 0
        for vid, record in self.videos.items():
            if record.has_transcript and record.transcript_path:
                try:
                    text = Path(record.transcript_path).read_text(encoding="utf-8")
                    # Prepend title for better search relevance
                    full_text = f"{record.title}\n\n{text}" if record.title else text
                    self.search_index.add_document(vid, full_text)
                    indexed += 1
                except OSError as exc:
                    logger.warning("Failed to read transcript %s: %s", record.transcript_path, exc)

        logger.info("Indexed %d transcripts for search", indexed)

    def get_video(self, video_id: str) -> VideoRecord | None:
        """Get a single video record."""
        return self.videos.get(video_id)

    def get_all_videos(
        self,
        category: str | None = None,
        has_transcript: bool | None = None,
        sort_by: str = "upload_date",
        reverse: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[VideoRecord], int]:
        """Get paginated, filtered list of videos."""
        records = list(self.videos.values())

        # Filter
        if category:
            records = [r for r in records if r.category == category]
        if has_transcript is not None:
            records = [r for r in records if r.has_transcript == has_transcript]

        total = len(records)

        # Sort. Only known sort keys are accepted (the client passes an
        # arbitrary attribute name — anything else silently fell back to "").
        sort_fields = {
            "upload_date",
            "title",
            "category",
            "video_id",
            "duration",
            "view_count",
            "transcript_size",
            "audio_size",
        }
        numeric_fields = {"duration", "view_count", "transcript_size", "audio_size"}
        if sort_by not in sort_fields:
            sort_by = "upload_date"

        def sort_key(r: VideoRecord) -> Any:  # noqa: ANN401 - heterogeneous record fields
            val = getattr(r, sort_by, "")
            # Coerce numeric fields to a number so records with missing values
            # never trigger a str-vs-number TypeError during sort; missing
            # numerics are pinned to 0 (last when reverse=True).
            if sort_by in numeric_fields:
                return val if val is not None else 0
            return val if val is not None else ""

        records.sort(key=sort_key, reverse=reverse)

        # Paginate
        records = records[offset : offset + limit]
        return records, total

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics."""
        videos = list(self.videos.values())
        total_transcript_bytes = sum(v.transcript_size or 0 for v in videos)
        total_audio_bytes = sum(v.audio_size or 0 for v in videos)

        # Category counts
        cat_counts = {cat: len(vids) for cat, vids in self.categories.items()}

        return {
            "total_videos": len(videos),
            "with_transcripts": sum(1 for v in videos if v.has_transcript),
            "with_audio": sum(1 for v in videos if v.has_audio),
            "total_transcript_mb": round(total_transcript_bytes / (1024 * 1024), 1),
            "total_audio_gb": round(total_audio_bytes / (1024**3), 1),
            "categories": cat_counts,
            "category_count": len(cat_counts),
        }
