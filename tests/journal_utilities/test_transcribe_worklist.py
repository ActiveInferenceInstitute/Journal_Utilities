"""Tests for scripts/transcribe_worklist.py (no GPU, no network)."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from transcribe_worklist import SRC_PREFIX, build_worklist, write_journal_transcript


def _make_item(
    root: Path, rel: str, vids: list[str], transcript: bool = False, date: str = "", dup: str = ""
) -> None:
    item = root / SRC_PREFIX / rel
    item.mkdir(parents=True)
    meta = {
        "series": rel.split("/")[0],
        "item": rel.split("/")[-1],
        "parts": [{"video_id": v} for v in vids],
    }
    if date:
        meta["date"] = date
    if dup:
        meta["duplicate_of"] = dup
    (item / "metadata.json").write_text(json.dumps(meta))
    if transcript:
        (item / "transcript.txt").write_text("existing")


class TestBuildWorklist:
    def test_selects_only_missing_past_items(self, tmp_path):
        _make_item(tmp_path, "A/needs_it", ["vid00000001"])
        _make_item(tmp_path, "A/has_transcript", ["vid00000002"], transcript=True)
        _make_item(tmp_path, "A/future", ["vid00000003"], date="2199-01-01")
        _make_item(tmp_path, "Other/dup", ["vid00000001"], dup="A/needs_it")
        work = build_worklist(tmp_path)
        assert [w["rel"] for w in work] == ["A/needs_it"]
        assert work[0]["vids"] == ["vid00000001"]

    def test_private_unlisted_never_transcribed(self, tmp_path):
        _make_item(tmp_path, "A/empty_parts", [])
        _make_item(tmp_path, "A/all_private", ["vidprivate1"])
        _make_item(tmp_path, "A/mixed", ["vidprivate1", "vid00000001"])
        (tmp_path / SRC_PREFIX / "private_videos.json").write_text(
            json.dumps({"videos": [{"video_id": "vidprivate1"}]})
        )
        excluded = []
        work = build_worklist(tmp_path, excluded)
        assert [w["rel"] for w in work] == ["A/mixed"]
        assert work[0]["vids"] == ["vid00000001"]
        assert excluded == ["A/all_private", "A/empty_parts"]


class TestWriteJournalTranscript:
    def _cache(self, out_dir: Path, vid: str, text: str) -> None:
        (out_dir / f"{vid}.simple.txt").write_text(text)
        (out_dir / f"{vid}.simple.json").write_text(
            json.dumps([{"speaker": "SPEAKER_00", "text": text}])
        )

    def test_single_part_plain(self, tmp_path):
        item, out = tmp_path / "item", tmp_path / "out"
        item.mkdir(), out.mkdir()
        self._cache(out, "vid00000001", "SPEAKER_00:\nhello")
        write_journal_transcript(item, ["vid00000001"], out)
        assert (item / "transcript.txt").read_text() == "SPEAKER_00:\nhello\n"
        assert json.loads((item / "transcript.json").read_text())[0]["video_id"] == "vid00000001"

    def test_multi_part_sections(self, tmp_path):
        item, out = tmp_path / "item", tmp_path / "out"
        item.mkdir(), out.mkdir()
        self._cache(out, "vidaaaaaaaa", "part one")
        self._cache(out, "vidbbbbbbbb", "part two")
        write_journal_transcript(item, ["vidaaaaaaaa", "vidbbbbbbbb"], out)
        text = (item / "transcript.txt").read_text()
        assert "## vidaaaaaaaa" in text and "## vidbbbbbbbb" in text
        assert len(json.loads((item / "transcript.json").read_text())) == 2
