"""Tests for scripts/apply_speaker_names.py (regenerate txt from raw json)."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from apply_speaker_names import (
    SALVAGE_NAME,
    has_speaker_structure,
    load_blocks,
    process_item,
    render_txt,
)


def _blocks(vid="vid00000001", speakers=("SPEAKER_00", "SPEAKER_01")):
    return [
        {
            "video_id": vid,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello there", "speaker": speakers[0]},
                {"start": 1.0, "end": 2.0, "text": "hi back", "speaker": speakers[1]},
                {"start": 2.0, "end": 3.0, "text": "more from me", "speaker": speakers[1]},
            ],
        }
    ]


def _meta(vid="vid00000001", speakers=None):
    return {"parts": [{"video_id": vid, "speakers": speakers}]}


class TestRenderTxt:
    def test_unmapped_keeps_labels(self):
        txt, unmapped = render_txt(_blocks(), _meta())
        assert txt.startswith("SPEAKER_00:\nhello there\n")
        assert unmapped == {"SPEAKER_00", "SPEAKER_01"}

    def test_mapping_applied_and_reported(self):
        txt, unmapped = render_txt(_blocks(), _meta(speakers={"SPEAKER_00": "Ada"}))
        assert txt.startswith("Ada:\nhello there\n")
        assert unmapped == {"SPEAKER_01"}

    def test_same_name_labels_merge(self):
        txt, _ = render_txt(_blocks(), _meta(speakers={"SPEAKER_00": "Ada", "SPEAKER_01": "Ada"}))
        assert txt.count("Ada:") == 1

    def test_multi_block_headers(self):
        blocks = _blocks("vidaaaaaaaa") + _blocks("vidbbbbbbbb")
        meta = {"parts": [{"video_id": "vidaaaaaaaa"}, {"video_id": "vidbbbbbbbb"}]}
        txt, _ = render_txt(blocks, meta)
        assert "## vidaaaaaaaa" in txt and "## vidbbbbbbbb" in txt

    def test_sess_split_uses_base_video_mapping(self):
        blocks = [{"video_id": "vid00000001_sess01", "segments": _blocks()[0]["segments"]}]
        txt, _ = render_txt(blocks, _meta(speakers={"SPEAKER_00": "Ada"}))
        assert "Ada:" in txt


class TestLoadBlocks:
    def test_rejects_assemblyai_shape(self, tmp_path):
        tj = tmp_path / "transcript.json"
        tj.write_text(json.dumps([{"video_id": "", "segments": {"id": "x"}}]))
        assert load_blocks(tj) is None

    def test_rejects_undiarized(self, tmp_path):
        tj = tmp_path / "transcript.json"
        tj.write_text(json.dumps([{"video_id": "v", "segments": [{"text": "hi"}]}]))
        assert load_blocks(tj) is None

    def test_accepts_whisperx_blocks(self, tmp_path):
        tj = tmp_path / "transcript.json"
        tj.write_text(json.dumps(_blocks()))
        assert load_blocks(tj) is not None


class TestHasSpeakerStructure:
    def test_speaker_label(self):
        assert has_speaker_structure("SPEAKER_00:\nhello\n")

    def test_mapped_name(self):
        assert has_speaker_structure("Fraser Paterson:\nhello\n")

    def test_header_then_name(self):
        assert has_speaker_structure("## vid00000001\n\nAda Lovelace:\nhello\n")

    def test_captions_prose(self):
        assert not has_speaker_structure("hello and welcome to the stream today\nwe will\n")


class TestProcessItem:
    def _item(self, tmp_path, old_txt=None):
        (tmp_path / "transcript.json").write_text(json.dumps(_blocks()))
        if old_txt is not None:
            (tmp_path / "transcript.txt").write_text(old_txt)
        return tmp_path

    def test_upgrade_salvages_captions(self, tmp_path):
        item = self._item(tmp_path, "caption prose without speakers\n")
        result = process_item(item, _meta(), apply=True)
        assert result["action"] == "upgrade+salvage"
        assert (item / "captions" / SALVAGE_NAME).read_text() == "caption prose without speakers\n"
        assert (item / "transcript.txt").read_text().startswith("SPEAKER_00:")

    def test_idempotent_second_run(self, tmp_path):
        item = self._item(tmp_path, "caption prose without speakers\n")
        process_item(item, _meta(), apply=True)
        assert process_item(item, _meta(), apply=True)["action"] == "unchanged"

    def test_dry_run_writes_nothing(self, tmp_path):
        item = self._item(tmp_path, "caption prose without speakers\n")
        result = process_item(item, _meta(), apply=False)
        assert result["action"] == "upgrade+salvage"
        assert (item / "transcript.txt").read_text() == "caption prose without speakers\n"
        assert not (item / "captions").exists()

    def test_json_never_touched(self, tmp_path):
        item = self._item(tmp_path, "caption prose\n")
        before = (item / "transcript.json").read_text()
        process_item(item, _meta(speakers={"SPEAKER_00": "Ada"}), apply=True)
        assert (item / "transcript.json").read_text() == before
        assert (item / "transcript.txt").read_text().startswith("Ada:")
