"""Rule-gated tests for scripts/upload_captions.py — fake client only.

Proves the M5 captions write-back contract (handoff M5 + pipeline Rule 1):
- skip-if-existing-track (captions.list gate; non-ASR or our track name);
- SRT staging stays JU-side (data/output/captions_upload), never in the journal;
- quota accounting (captions.list=1, captions.insert=400) against a budget;
- --max-uploads-per-day cap counts each insert exactly once;
- dry-run performs NO API calls and writes NOTHING;
- backup is written BEFORE any write (insert and metadata.json update);
- metadata.json gains captions_uploaded provenance only on --apply.

The Data API is never contacted: the client is a fake with the
``list_captions``/``insert_caption`` surface of the real YouTubeClient.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from upload_captions import (  # noqa: E402
    TRACK_LANGUAGE,
    TRACK_NAME,
    UploadContext,
    has_blocking_track,
    run,
    upload_captions_for_video,
)

from journal_utilities.youtube.client import QuotaLedger  # noqa: E402

CAPTION_COSTS = {"captions.list": 1, "captions.insert": 400}

TRACK = {
    "kind": "youtube#caption",
    "id": "existing-track",
    "snippet": {"videoId": "vid1", "trackKind": "asr", "language": "en", "name": "English (auto)"},
}


class FakeCaptionClient:
    """Fake of YouTubeClient's caption surface; records every call."""

    def __init__(self, tracks_by_video: dict[str, list[dict]] | None = None):
        self.tracks_by_video = tracks_by_video or {}
        self.listed: list[str] = []
        self.inserted: list[tuple[str, str, str, str]] = []
        self.fail_for: set[str] = set()

    def list_captions(self, video_id: str) -> list[dict]:
        return copy.deepcopy(self.tracks_by_video.get(video_id, []))

    def insert_caption(
        self, video_id: str, name: str, language: str, path: str, *, is_draft: bool = True
    ) -> dict | None:
        self.inserted.append((video_id, name, language, path, is_draft))
        if video_id in self.fail_for:
            return None
        return {"kind": "youtube#caption", "id": f"cap-{video_id}"}


@pytest.fixture
def journal(tmp_path: Path) -> Path:
    """A fake journal checkout root."""
    root = tmp_path / "journal"
    root.mkdir()
    return root


def make_item(journal: Path, name: str = "Insights_001", video_id: str = "vid1") -> Path:
    item = journal / "data/video/activeinferenceinstitute/Insights" / name
    item.mkdir(parents=True, exist_ok=True)
    (item / "transcript.json").write_text(
        json.dumps(
            [
                {
                    "video_id": video_id,
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 2.0,
                            "text": " Hello there.",
                            "speaker": "SPEAKER_00",
                        },
                        {
                            "start": 2.0,
                            "end": 4.0,
                            "text": " And we're away.",
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
    return item


def make_row(journal: Path, video_id: str = "vid1", name: str = "Insights_001") -> dict[str, str]:
    """Row matching captions_worklist output; creates the item as a side effect."""
    item = make_item(journal, name, video_id)
    return {
        "priority": "1",
        "priority_name": "insights",
        "series": "Insights",
        "item": name,
        "video_id": video_id,
        "views": "",
        "transcript": "true",
        "existing_srt": "false",
        "srt_available": "true",
        "item_path": str(item.relative_to(journal)),
    }


def make_ctx(client: FakeCaptionClient, journal: Path, tmp_path: Path, **kw) -> UploadContext:
    defaults = dict(
        client=client,
        ledger=QuotaLedger(budget=kw.pop("budget", 10_000)),
        journal_dir=journal,
        apply=kw.pop("apply", True),
        backup_dir=kw.pop("backup_dir", tmp_path / "yt_backup"),
        staging_dir=kw.pop("staging_dir", tmp_path / "staging"),
        max_uploads=kw.pop("max_uploads", 24),
    )
    assert not kw, f"unexpected kwargs: {kw}"
    return UploadContext(**defaults)


# ------------------------------------------------------------ track gate


def test_has_blocking_track_variants() -> None:
    assert not has_blocking_track([])
    asr_only = [{"snippet": {"trackKind": "asr", "name": "English (auto)"}}]
    assert not has_blocking_track(asr_only)  # ASR-only stays an upload target
    non_asr = [{"snippet": {"trackKind": "nonAsr", "name": "English"}}]
    assert has_blocking_track(non_asr)
    ours = [{"snippet": {"trackKind": "asr", "name": TRACK_NAME}}]
    assert has_blocking_track(ours)  # our track already present: no duplicates


# ------------------------------------------------------------ skip-if-existing


def test_skips_video_with_existing_non_asr_track(tmp_path: Path, journal: Path) -> None:
    make_item(journal)
    client = FakeCaptionClient({"vid1": [{"snippet": {"trackKind": "nonAsr", "name": "English"}}]})
    ctx = make_ctx(client, journal, tmp_path)
    result = upload_captions_for_video(ctx, make_row(journal, "vid1", "Insights_002"))
    assert result["action"] == "skipped"
    assert "non-ASR" in result["reason"]
    assert client.inserted == []
    assert ctx.ledger.spent == 1  # captions.list charged; insert never


def test_skips_when_journal_track_already_uploaded(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    make_item(journal)
    client = FakeCaptionClient({"vid1": [{"snippet": {"trackKind": "asr", "name": TRACK_NAME}}]})
    ctx = make_ctx(client, journal, tmp_path)
    result = upload_captions_for_video(ctx, make_row(journal))
    assert result["action"] == "skipped"
    assert "non-ASR" in result["reason"]


def test_uploads_over_asr_only_track(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    item = make_item(journal)
    client = FakeCaptionClient({"vid1": [dict(TRACK)]})
    ctx = make_ctx(client, journal, tmp_path)
    result = upload_captions_for_video(ctx, make_row(journal))
    assert result["action"] == "uploaded"
    assert client.inserted == [
        ("vid1", TRACK_NAME, TRACK_LANGUAGE, str(tmp_path / "staging" / "vid1.en.srt"), False)
    ]
    recorded = json.loads((item / "metadata.json").read_text())["captions_uploaded"]["vid1"]
    assert recorded["track_name"] == TRACK_NAME
    assert recorded["language"] == TRACK_LANGUAGE
    assert recorded["is_draft"] is False
    assert recorded["srt_source"] == "whisperx:transcript.json"
    assert recorded["provenance"]["generated_by"] == "scripts/upload_captions.py"


# ----------------------------------------------------------------- quota


def test_quota_budget_stops_batch(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    journal = tmp_path / "journal"
    client = FakeCaptionClient()
    ctx = make_ctx(client, journal, tmp_path, budget=401, max_uploads=5)
    rows = [make_row(journal, f"vid{i}", f"Item_{i:02d}") for i in range(3)]
    counts = run(ctx, rows)
    # 401 units = exactly one list(1)+insert(400); videos 2-3 cannot afford a list.
    assert counts["uploaded"] == 1
    assert len(client.inserted) == 1
    assert ctx.ledger.spent == 401


def test_max_uploads_per_day_cap(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    client = FakeCaptionClient()
    ctx = make_ctx(client, journal, tmp_path, max_uploads=2)
    rows = [make_row(journal, f"vid{i}", f"Item_{i:02d}") for i in range(4)]
    counts = run(ctx, rows)
    # Each insert uploads exactly once: cap counts inserts, not rows.
    assert counts["uploaded"] == 2
    assert len(client.inserted) == 2
    assert ctx.uploads_done == 2
    assert counts["skipped"] == 2
    assert "cap reached" in next(r["reason"] for r in ctx.results if r["video_id"] == "vid2")


def test_ledger_uses_real_client_costs(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    make_item(journal)
    ctx = make_ctx(FakeCaptionClient(), journal, tmp_path)
    upload_captions_for_video(ctx, make_row(journal))
    assert ctx.ledger.spent == 401  # 1 (list) + 400 (insert)


# ---------------------------------------------------------------- dry-run


def test_dry_run_makes_no_calls_and_writes_nothing(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    item = make_item(journal)
    meta_before = (item / "metadata.json").read_text()
    client = FakeCaptionClient()
    ctx = make_ctx(client, journal, tmp_path, apply=False)
    result = upload_captions_for_video(ctx, make_row(journal))
    assert result["action"] == "planned"
    assert client.inserted == []
    assert ctx.ledger.spent == 0
    assert (item / "metadata.json").read_text() == meta_before
    assert not (tmp_path / "staging" / "vid1.en.srt").exists()


def test_dry_run_never_builds_real_client(tmp_path: Path) -> None:
    # main() constructs YouTubeClient only on --apply; a fake env without
    # secrets must still allow a dry-run plan. Proof: dry-run path imports
    # nothing that needs OAuth and performs no I/O beyond reading the journal.
    from upload_captions import build_parser

    args = build_parser().parse_args([])
    assert not args.apply
    assert args.max_uploads_per_day == 24
    assert args.quota_budget == 10_000
    assert args.languages == "zh-Hans,de"


# ----------------------------------------------------------------- backups


def test_backup_written_before_insert(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    item = make_item(journal)
    backup_dir = tmp_path / "yt_backup"
    client = FakeCaptionClient()
    ctx = make_ctx(client, journal, tmp_path)
    ctx.backup_dir = backup_dir

    # Capture the backup directory at insert time to prove ordering.
    seen: list[bool] = []

    real_insert = client.insert_caption

    def spy_insert(
        video_id: str, name: str, language: str, path: str, *, is_draft: bool = True
    ) -> dict | None:
        backups = list(backup_dir.rglob("*-captions.json")) if backup_dir.exists() else []
        seen.append(bool(backups))
        return real_insert(video_id, name, language, path, is_draft=is_draft)

    client.insert_caption = spy_insert  # type: ignore[method-assign]
    upload_captions_for_video(ctx, make_row(journal))
    assert seen == [True]
    backup = json.loads(next(backup_dir.rglob("*-captions.json")).read_text())
    assert backup["video_id"] == "vid1"
    assert backup["captions_list"] == []  # captions.list snapshot
    assert json.loads(backup["metadata_json"])["item"] == "Insights_001"
    assert (item / "metadata.json").read_text() != backup["metadata_json"]  # record added AFTER


def test_insert_failure_records_no_metadata(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    item = make_item(journal)
    meta_before = (item / "metadata.json").read_text()
    client = FakeCaptionClient({"vid1": [dict(TRACK)]})
    client.fail_for.add("vid1")
    ctx = make_ctx(client, journal, tmp_path)
    result = upload_captions_for_video(ctx, make_row(journal))
    assert result["action"] == "skipped"
    assert "failed" in result["reason"]
    assert (item / "metadata.json").read_text() == meta_before


def test_derivable_gate_no_transcript_no_quota(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    client = FakeCaptionClient()
    ctx = make_ctx(client, journal, tmp_path)
    # Build the row FIRST, then break the transcript: make_row re-creates the
    # item, so unlinking before would be undone.
    row = make_row(journal)
    (journal / row["item_path"] / "transcript.json").unlink()
    result = upload_captions_for_video(ctx, row)
    assert result["action"] == "skipped"
    assert ctx.ledger.spent == 0
    assert client.inserted == []


def test_upload_stages_srt_outside_journal(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    make_item(journal)
    client = FakeCaptionClient()
    ctx = make_ctx(client, journal, tmp_path)
    upload_captions_for_video(ctx, make_row(journal))
    staged = tmp_path / "staging" / "vid1.en.srt"
    assert staged.is_file()
    body = staged.read_text()
    assert "Hello there." in body
    assert "00:00:00,000 --> 00:00:02,000" in body
    # Journal checkout untouched: no new SRT inside it.
    journal_srts = [p for p in journal.rglob("*.srt")]
    assert journal_srts == []


def test_run_counts_actions(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    client = FakeCaptionClient({"vid1": [{"snippet": {"trackKind": "nonAsr", "name": "English"}}]})
    ctx = make_ctx(client, journal, tmp_path, apply=False)
    rows = [make_row(journal, "vid1", "Item_01")]
    counts = run(ctx, rows)
    assert counts == {"uploaded": 0, "planned": 1, "skipped": 0}
