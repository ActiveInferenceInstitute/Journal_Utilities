"""Exercise the YouTube audit and repair boundary with synthetic channel data."""

import hashlib
import json
from argparse import Namespace
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pytest
from scripts import youtube_channel_audit as cli

from journal_utilities.ingest.enumerate import DEFAULT_CHANNEL_ID
from journal_utilities.youtube.channel_audit import (
    CLASSES,
    audit_channel,
    description_changes,
    stable_digest,
)
from journal_utilities.youtube.client import QuotaLedger, VideoSnippet, YouTubeReadError

KNOWN = "AAAAAAAAAAA"
PUBLIC = "BBBBBBBBBBB"
PRIVATE = "CCCCCCCCCCC"
SCHEDULED = "DDDDDDDDDDD"
FOREIGN = "EEEEEEEEEEE"
PLAYLIST_ONLY = "FFFFFFFFFFF"
INDEX = {
    KNOWN: {
        "path": "data/video/activeinferenceinstitute/Insights/001",
        "has_transcript": True,
        "parts": [KNOWN],
    }
}


def video(video_id, *, channel_id=DEFAULT_CHANNEL_ID, privacy="public", broadcast="none"):
    return {
        "id": video_id,
        "snippet": {
            "channelId": channel_id,
            "title": "Insights Session 7 June 23, 2026",
            "description": "Abstract\nWebsite: https://activeinference.org/",
            "categoryId": "27",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en-US",
            "liveBroadcastContent": broadcast,
            "publishedAt": "2026-06-23T18:00:00Z",
        },
        "status": {"privacyStatus": privacy, "uploadStatus": "processed"},
        "contentDetails": {"duration": "PT1H"},
        "liveStreamingDetails": {"actualStartTime": "2026-06-24T04:00:00Z"},
    }


class FakeChannel:
    def get_uploads_playlist_id(self, channel_id, *, strict, ledger):
        assert channel_id == DEFAULT_CHANNEL_ID and strict
        return "uploads"

    def list_playlist_items(self, playlist_id, *, strict, ledger):
        assert strict
        if playlist_id == "uploads":
            return [
                {"contentDetails": {"videoId": vid}}
                for vid in (KNOWN, PUBLIC, PRIVATE, SCHEDULED, FOREIGN)
            ]
        return [
            {"contentDetails": {"videoId": PUBLIC}, "snippet": {"title": "Fundamentals Session 7"}},
            {
                "contentDetails": {"videoId": PLAYLIST_ONLY},
                "snippet": {"title": "Fundamentals Session 6"},
            },
            {"snippet": {"title": "Private video"}},
        ]

    def list_videos(self, video_ids, *, part, strict, ledger):
        assert strict and video_ids == [KNOWN, PUBLIC, PRIVATE, SCHEDULED, FOREIGN, PLAYLIST_ONLY]
        return [
            video(KNOWN),
            video(PUBLIC),
            video(PRIVATE, privacy="private"),
            video(SCHEDULED, broadcast="upcoming"),
            video(FOREIGN, channel_id="UCdifferent"),
            video(PLAYLIST_ONLY),
        ]

    def list_playlists(self, channel_id, *, strict, ledger):
        return [
            {
                "id": "public-playlist",
                "snippet": {"title": "Fundamentals", "channelId": channel_id},
                "status": {"privacyStatus": "public"},
            }
        ]


def test_audit_exports_only_completed_owned_public_backlog():
    worklist, findings, repairs, unavailable = audit_channel(
        FakeChannel(),
        DEFAULT_CHANNEL_ID,
        QuotaLedger(100),
        INDEX,
        CLASSES,
        ZoneInfo("America/Los_Angeles"),
    )
    assert [row.video_id for row in worklist.new_videos] == [PUBLIC, PLAYLIST_ONLY]
    assert worklist.new_videos[0].publication_state == "published"
    assert [row.playlist_titles for row in worklist.new_videos] == [["Fundamentals"]] * 2
    assert {row["video_id"] for row in repairs} == {KNOWN, PUBLIC, PLAYLIST_ONLY}
    assert {row["kind"] for row in findings} >= {
        "missing_from_journal",
        "language_mismatch",
        "playlist_order",
        "unavailable_playlist_entry",
        "legacy",
        "backlink",
    }
    assert "title_date" not in {row["kind"] for row in findings}
    assert unavailable == 0


def test_missing_legacy_mapping_is_reported_while_other_links_and_prose_are_preserved():
    raw = (
        "See (https://twitter.com/InferenceActive), "
        "https://activeinference.org/education/unknown, "
        "https://coda.io/@active-inference-institute/unknown?example=secret, "
        "https://example.org/resource."
    )
    revised, findings = description_changes(raw, None, CLASSES)
    assert revised == raw.replace(
        "https://twitter.com/InferenceActive", "https://x.com/InferenceActive"
    )
    assert sum(row["kind"] == "dead" and row["repairable"] == "no" for row in findings) == 2
    assert "secret" not in json.dumps(findings)


def test_archived_symposium_proceedings_replace_the_verified_dead_link():
    coda = "https://coda.io/@active-inference-institute/2nd-applied-active-inference-symposium"
    revised, findings = description_changes(f"2022 Symposium\n{coda}", None, CLASSES)
    assert revised == "2022 Symposium\nhttps://doi.org/10.5281/zenodo.7402485"
    assert findings == [{"kind": "dead", "link": coda, "repairable": "yes"}]


def test_backlinks_distinguish_the_journal_item_and_transcript_availability():
    root = "https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/tree/main"
    expected = f"{root}/data/video/activeinferenceinstitute/Insights/001"
    revised, findings = description_changes(root, expected, CLASSES, has_transcript=False)
    assert revised.endswith(f"JOURNAL RECORD\n{expected}")
    assert findings == [{"kind": "backlink"}]
    other = f"{root}/data/video/activeinferenceinstitute/Insights/002"
    assert description_changes(other, expected, CLASSES) == (
        other,
        [{"kind": "different_journal_link"}],
    )
    assert description_changes(expected + "#readme", expected, CLASSES) == (
        expected + "#readme",
        [],
    )


def test_aborted_collection_writes_no_partial_report_or_worklist(tmp_path, monkeypatch):
    class Partial(FakeChannel):
        def list_videos(self, *args, **kwargs):
            raise YouTubeReadError("second video batch failed")

    (tmp_path / "INDEX.json").write_text(json.dumps({"items": list(INDEX.values())}))
    monkeypatch.setenv("YOUTUBE_API_KEY", "synthetic")
    monkeypatch.setattr(cli, "YouTubeClient", lambda **_: Partial())
    report, worklist = tmp_path / "report.json", tmp_path / "worklist.json"
    with pytest.raises(SystemExit) as failure:
        cli.main(
            [
                "audit",
                "--journal",
                str(tmp_path),
                "--report",
                str(report),
                "--worklist",
                str(worklist),
            ]
        )
    assert failure.value.code == 2
    assert not report.exists() and not worklist.exists()


@dataclass
class WriteResult:
    success: bool = True


class RepairClient:
    def __init__(self, *, observed_channel=DEFAULT_CHANNEL_ID):
        self.live = video(KNOWN, channel_id=observed_channel)
        self.updates = []

    def require_channel(self, channel_id, *, ledger):
        ledger.spend("channels.list")
        assert channel_id == DEFAULT_CHANNEL_ID

    def list_videos(self, ids, *, part, strict, ledger):
        assert ids == [KNOWN] and strict
        ledger.spend("videos.list")
        return [self.live]

    def update_video_snippet(self, intended, *, dry_run):
        assert not dry_run
        assert intended.default_language == "en"
        self.updates.append(intended)
        self.live["snippet"]["description"] = intended.description
        return WriteResult()


def repair_args(tmp_path):
    index_raw = json.dumps({"items": list(INDEX.values())}).encode()
    (tmp_path / "INDEX.json").write_bytes(index_raw)
    live = VideoSnippet.from_api(video(KNOWN))
    expected = live.description.replace(
        "https://activeinference.org/", "https://www.activeinference.institute/"
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "version": 1,
                "channel_id": DEFAULT_CHANNEL_ID,
                "index_sha256": hashlib.sha256(index_raw).hexdigest(),
                "classes": ["legacy"],
                "repairs": [
                    {
                        "video_id": KNOWN,
                        "before_sha256": stable_digest(live.to_body()),
                        "before": live.description,
                        "after": expected,
                    }
                ],
            }
        )
    )
    return Namespace(
        journal=tmp_path,
        plan=plan,
        plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
        channel_id=DEFAULT_CHANNEL_ID,
        quota_budget=100,
        backup_dir=tmp_path / "backup",
        limit=5,
    )


def test_reviewed_repair_is_backed_up_verified_and_idempotent(tmp_path, monkeypatch):
    args = repair_args(tmp_path)
    client = RepairClient()
    monkeypatch.setattr(cli, "_cached_oauth", lambda: client)
    assert cli._apply(args) == 0
    assert cli._apply(args) == 0
    assert len(client.updates) == 1
    (backup,) = (args.backup_dir / KNOWN).glob("*.json")
    assert json.loads(backup.read_text())["snapshot"]["snippet"]["defaultLanguage"] == "en"


@pytest.mark.parametrize("cause", ["wrong channel", "changed snippet", "quota"])
def test_reviewed_repair_refuses_unsafe_state(tmp_path, monkeypatch, cause):
    args = repair_args(tmp_path)
    client = RepairClient(
        observed_channel="UCother" if cause == "wrong channel" else DEFAULT_CHANNEL_ID
    )
    if cause == "changed snippet":
        client.live["snippet"]["title"] = "Another editor changed this title"
    if cause == "quota":
        args.quota_budget = 52
    monkeypatch.setattr(cli, "_cached_oauth", lambda: client)
    with pytest.raises((ValueError, YouTubeReadError, cli.QuotaBudgetExceededError)):
        cli._apply(args)
    assert client.updates == []
    assert not args.backup_dir.exists()
