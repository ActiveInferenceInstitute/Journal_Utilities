"""Offline coverage of reviewed English caption publication."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from captions_worklist import build_worklist
from upload_captions import (
    DEFAULT_MAX_UPLOADS,
    TRACK_LANGUAGE,
    TRACK_NAME,
    UploadContext,
    has_blocking_track,
    main,
    run,
    upload_captions_for_video,
)

from journal_utilities.ingest.enumerate import DEFAULT_CHANNEL_ID
from journal_utilities.youtube.client import QuotaLedger, YouTubeReadError

VIDEO = "aaaaaaa0001"
ASR = {"snippet": {"trackKind": "ASR", "language": "en", "name": "English (auto)"}}
HUMAN = {"snippet": {"trackKind": "standard", "language": "en-US", "isDraft": True}}


class FakeCaptionClient:
    """Require strict reads and account for the same operations as the live client."""

    def __init__(self, tracks=None):
        self.tracks = tracks or []
        self.listed = []
        self.inserted = []
        self.fail_list = False
        self.fail_insert = False
        self.audio = "en"
        self.metadata = "en"
        self.channel = DEFAULT_CHANNEL_ID
        self.visibility = "public"

    def list_videos(self, ids, part, *, strict, ledger):
        assert strict and part == "snippet,status"
        ledger.spend("videos.list")
        return [
            {
                "id": ids[0],
                "snippet": {
                    "channelId": self.channel,
                    "defaultAudioLanguage": self.audio,
                    "defaultLanguage": self.metadata,
                },
                "status": {"privacyStatus": self.visibility},
            }
        ]

    def list_captions(self, video_id, *, strict, ledger):
        assert strict
        self.listed.append(video_id)
        ledger.spend("captions.list")
        if self.fail_list:
            raise YouTubeReadError("could not verify caption tracks")
        return copy.deepcopy(self.tracks)

    def insert_caption(self, video_id, name, language, path, *, is_draft):
        assert not is_draft
        self.inserted.append((video_id, name, language, Path(path)))
        return None if self.fail_insert else {"id": f"cap-{video_id}"}


def make_row(journal, video_id=VIDEO, name="Insights_001", series="Insights"):
    item = journal / "data/video/activeinferenceinstitute" / series / name
    item.mkdir(parents=True, exist_ok=True)
    (item / "transcript.json").write_text(
        json.dumps(
            [
                {
                    "video_id": video_id,
                    "segments": [
                        {"start": 0.0, "end": 2.0, "text": "Hello there.", "speaker": "SPEAKER_00"},
                        {
                            "start": 2.0,
                            "end": 4.0,
                            "text": "And we're away.",
                            "speaker": "SPEAKER_00",
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    (item / "metadata.json").write_text(
        json.dumps({"item": name, "parts": [{"video_id": video_id, "speakers": {}}]}),
        encoding="utf-8",
    )
    return {
        "series": series,
        "item": name,
        "video_id": video_id,
        "existing_srt": "true",
        "item_path": str(item.relative_to(journal)),
    }


def make_ctx(tmp_path, client, *, budget=10_000, max_uploads=DEFAULT_MAX_UPLOADS, apply=True):
    return UploadContext(
        client=client,
        ledger=QuotaLedger(budget=budget),
        journal_dir=tmp_path / "journal",
        apply=apply,
        backup_dir=tmp_path / "yt_backup",
        staging_dir=tmp_path / "staging",
        receipts_path=tmp_path / "captions_uploaded.jsonl",
        max_uploads=max_uploads,
    )


def test_track_protection_matches_the_official_asr_enum():
    assert not has_blocking_track([ASR])
    assert not has_blocking_track([{"snippet": {"trackKind": "standard", "language": "fr"}}])
    assert has_blocking_track([HUMAN])
    assert has_blocking_track([{"snippet": {"trackKind": "ASR", "name": TRACK_NAME}}])
    assert has_blocking_track([{"snippet": {"trackKind": "standard"}}])
    assert has_blocking_track([{"snippet": None}])


@pytest.mark.parametrize(
    ("changes", "expected", "spent"),
    [
        ({"visibility": "private"}, "public", 1),
        ({"channel": "other-channel"}, "owned by", 1),
        ({"audio": "en-US"}, "same English", 1),
        ({"audio": ""}, "same English", 1),
        ({"audio": "fr", "metadata": "fr"}, "same English", 1),
        ({"tracks": [HUMAN]}, "non-ASR", 51),
        ({"fail_list": True}, "could not verify", 51),
    ],
)
def test_apply_fails_closed_on_live_preflight(tmp_path, changes, expected, spent):
    client = FakeCaptionClient()
    for key, value in changes.items():
        setattr(client, key, value)
    ctx = make_ctx(tmp_path, client)
    row = make_row(ctx.journal_dir)
    result = upload_captions_for_video(ctx, row)
    assert result["action"] == "skipped"
    assert expected in result["reason"]
    assert not client.inserted and not ctx.receipts_path.exists()
    assert ctx.ledger.spent == spent


def test_upload_writes_backup_receipt_and_matching_metadata(tmp_path, monkeypatch):
    client = FakeCaptionClient([ASR])
    ctx = make_ctx(tmp_path, client)
    row = make_row(ctx.journal_dir)
    metadata = ctx.journal_dir / row["item_path"] / "metadata.json"
    original = metadata.read_text()
    insert = client.insert_caption

    def inspect_backup(*args, **kwargs):
        backup = json.loads(next(ctx.backup_dir.rglob("*-captions.json")).read_text())
        assert backup["metadata_json"] == original and backup["captions_list"] == [ASR]
        assert not ctx.receipts_path.exists()
        return insert(*args, **kwargs)

    monkeypatch.setattr(client, "insert_caption", inspect_backup)
    result = upload_captions_for_video(ctx, row)
    assert result["action"] == "uploaded"
    assert ctx.ledger.spent == 451
    vid, name, language, staged = client.inserted[0]
    receipt = json.loads(ctx.receipts_path.read_text())
    record = json.loads(metadata.read_text())["captions_uploaded"][VIDEO]
    assert (vid, name, language) == (VIDEO, TRACK_NAME, TRACK_LANGUAGE)
    assert staged == ctx.staging_dir / f"{VIDEO}.{receipt['srt_sha256']}.en.srt"
    assert ">> Speaker 0: Hello there." in staged.read_text()
    assert not list(ctx.journal_dir.rglob("*.srt"))
    assert receipt == {"video_id": VIDEO, **record}

    # A retry after Journal metadata restoration still honors the local receipt.
    metadata.write_text(original, encoding="utf-8")
    assert upload_captions_for_video(ctx, row)["action"] == "skipped"
    assert len(client.inserted) == 1
    assert ctx.ledger.spent == 451


def test_invalid_local_selections_do_not_spend_quota(tmp_path):
    ctx = make_ctx(tmp_path, FakeCaptionClient())
    row = make_row(ctx.journal_dir)
    assert "outside" in upload_captions_for_video(ctx, {**row, "item_path": "../outside"})["reason"]
    assert "digest" in upload_captions_for_video(ctx, {**row, "srt_sha256": "0" * 64})["reason"]
    assert ctx.ledger.spent == 0


def test_quota_and_attempt_cap_stop_ineligible_batch_rows(tmp_path):
    ctx = make_ctx(tmp_path, FakeCaptionClient(), budget=451)
    rows = [make_row(ctx.journal_dir, f"aaaaaaa{i:04d}", f"Item_{i}") for i in range(3)]
    assert run(ctx, rows) == {"uploaded": 1, "planned": 0, "skipped": 2}
    assert ctx.ledger.spent == 451
    ctx = make_ctx(tmp_path, FakeCaptionClient(), max_uploads=1)
    ctx.client.fail_insert = True
    assert run(ctx, rows[1:]) == {"uploaded": 0, "planned": 0, "skipped": 2}
    assert ctx.upload_attempts == 1
    assert ctx.ledger.spent == 451
    assert "cap reached" in ctx.results[-1]["reason"]


def test_dry_run_default_reads_transcript_even_when_downloaded_caption_exists(tmp_path):
    client = FakeCaptionClient()
    ctx = make_ctx(tmp_path, client, apply=False)
    row = make_row(ctx.journal_dir)
    before = sorted(ctx.journal_dir.rglob("*"))
    result = upload_captions_for_video(ctx, row)
    assert result["action"] == "planned" and result["cue_count"] == 2
    assert not client.listed and not client.inserted and ctx.ledger.spent == 0
    assert sorted(ctx.journal_dir.rglob("*")) == before
    assert not ctx.backup_dir.exists() and not ctx.receipts_path.exists()


def test_worklist_ranks_insights_modelstream_and_matching_high_views(tmp_path):
    root = tmp_path / "journal"
    rows = [
        make_row(root, "aaaaaaa0001", "Guest_001", "GuestStream"),
        make_row(root, "aaaaaaa0002", "ModelStream_001", "ModelStream"),
        make_row(root, "aaaaaaa0003", "Insights_001"),
    ]
    first = rows[0]
    item_dir = root / first["item_path"]
    (item_dir / "captions").mkdir()
    (item_dir / "captions/downloaded.srt").touch()
    index = [{**row, "path": row["item_path"], "parts": [row["video_id"]]} for row in rows]
    index[0]["parts"].append("aaaaaaa0004")  # a different part has no transcript
    (root / "INDEX.json").write_text(json.dumps({"items": index}), encoding="utf-8")
    worklist = build_worklist(root, {"aaaaaaa0001": 50, "aaaaaaa0004": 100})
    assert [row["video_id"] for row in worklist] == [
        "aaaaaaa0003",
        "aaaaaaa0002",
        "aaaaaaa0001",
        "aaaaaaa0004",
    ]
    assert worklist[2]["existing_srt"] == worklist[2]["srt_available"] == "true"
    assert worklist[3]["srt_available"] == "false"
    before = sorted(root.rglob("*"))
    assert main(["--journal", str(root), "--limit", "1"]) == 0
    assert sorted(root.rglob("*")) == before
    with pytest.raises(SystemExit, match="2"):
        main(["--journal", str(root), "--apply"])
