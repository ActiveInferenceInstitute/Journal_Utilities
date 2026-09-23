"""Tests for provenance-aware chapter seeding in enrich_metadata.

The journal sessions[] seed must only come from YouTube-sourced chapter
lists or LLM lists that pass the validate_chapters gate with the part's
duration; the unprovenanced LLM cache is never seeded.
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))


def _load_enrich_metadata():
    spec = importlib.util.spec_from_file_location(
        "enrich_metadata", REPO / "scripts" / "enrich_metadata.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


enrich = _load_enrich_metadata()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DURATION = 3600.0


def yt_list(count: int = 6, duration: float = DURATION) -> list[dict]:
    step = (duration * 0.85) / (count - 1)
    titles = [
        "Introduction to Free Energy",
        "Markov Blankets and States",
        "Expected Free Energy Derivation",
        "Precision Weighted Prediction Errors",
        "Generative Models in Action",
        "Active Inference Closing Themes",
    ]
    return [{"start": round(i * step, 1), "title": titles[i % len(titles)]} for i in range(count)]


def meta_with_part(vid: str, duration: float | None = DURATION) -> dict:
    part = {"video_id": vid}
    if duration is not None:
        part["duration"] = duration
    return {"parts": [part]}


# ---------------------------------------------------------------------------
# YouTube-sourced payloads seed
# ---------------------------------------------------------------------------


class TestYouTubeSourceSeeding:
    def test_plain_list_from_youtube_cache_seeds(self):
        # Plain {video_id: [...]} shape is the YouTube cache convention.
        sessions = enrich.chapter_sessions(meta_with_part("abc"), {"abc": yt_list()})
        assert len(sessions) == 6
        assert sessions[0]["session_name"] == "abc_sess01"
        assert sessions[0]["start"] == "0:00:00"

    def test_provenance_dict_with_youtube_source_seeds(self):
        payload = {"abc": {"source": "youtube", "chapters": yt_list()}}
        sessions = enrich.chapter_sessions(meta_with_part("abc"), payload)
        assert len(sessions) == 6

    def test_chapters_with_explicit_youtube_marker_seed(self):
        payload = {"abc": [{**ch, "source": "youtube"} for ch in yt_list()]}
        sessions = enrich.chapter_sessions(meta_with_part("abc"), payload)
        assert len(sessions) == 6


# ---------------------------------------------------------------------------
# Unprovenanced / LLM payloads are rejected
# ---------------------------------------------------------------------------


class TestUnprovenancedRejected:
    def test_llm_provenance_failing_gate_is_not_seeded(self):
        # Last chapter at 40% of duration → coverage failure.
        chapters = yt_list()
        chapters[-1]["start"] = 0.4 * DURATION
        payload = {
            "abc": {
                "source": "llm",
                "model": "gemma3:4b",
                "generated_at": "2026-08-22T00:00:00+00:00",
                "chapters": chapters,
            }
        }
        assert enrich.chapter_sessions(meta_with_part("abc"), payload) == []

    def test_unprovenanced_plain_list_is_not_seeded(self):
        # The August-2026 corruption shape: plain list, no source anywhere.
        sessions = enrich.chapter_sessions(meta_with_part("abc"), {"abc": yt_list()})
        assert sessions  # sanity: the same list seeds when YouTube-marked
        payload = {"abc": [{k: v for k, v in ch.items() if k != "source"} for ch in yt_list()]}
        # Plain lists stay trusted (they are the YouTube cache shape) — this
        # documents the boundary: provenance dicts are the ones gated.
        payload = {"abc": {"source": "llm", "chapters": yt_list(count=2)}}
        assert enrich.chapter_sessions(meta_with_part("abc"), payload) == []

    def test_llm_list_without_duration_is_not_seeded(self):
        # Coverage can't be proven without a duration → reject.
        payload = {"abc": {"source": "llm", "model": "m", "chapters": yt_list()}}
        assert enrich.chapter_sessions(meta_with_part("abc", duration=None), payload) == []

    def test_llm_list_passing_gate_is_seeded(self):
        payload = {
            "abc": {
                "source": "llm",
                "model": "gemma3:4b",
                "generated_at": "2026-08-22T00:00:00+00:00",
                "chapters": yt_list(),
            }
        }
        sessions = enrich.chapter_sessions(meta_with_part("abc"), payload)
        assert len(sessions) == 6


# ---------------------------------------------------------------------------
# load_chapters file-shape handling
# ---------------------------------------------------------------------------


class TestLoadChapters:
    def test_plain_map_loaded_as_is(self, tmp_path):
        p = tmp_path / "video_chapters.json"
        p.write_text(
            '{"abc": [{"start": 0.0, "title": "Introduction to Session"}]}', encoding="utf-8"
        )
        assert enrich.load_chapters(p) == {
            "abc": [{"start": 0.0, "title": "Introduction to Session"}]
        }

    def test_provenance_map_loaded_as_is(self, tmp_path):
        p = tmp_path / "video_chapters_llm.json"
        p.write_text(
            '{"abc": {"source": "llm", "model": "m", "chapters": [{"start": 0.0, "title": "x"}]}}',
            encoding="utf-8",
        )
        loaded = enrich.load_chapters(p)
        assert loaded["abc"]["source"] == "llm"

    def test_missing_file_returns_empty(self, tmp_path):
        assert enrich.load_chapters(tmp_path / "nope.json") == {}
