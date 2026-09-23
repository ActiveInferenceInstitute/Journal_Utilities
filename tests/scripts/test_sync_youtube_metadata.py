"""Rule-1 guarantees for the YouTube metadata sync script.

All tests use fakes; the Data API is never contacted (Rule: unit tests prove
behavior against injected clients).
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from scripts.sync_youtube_metadata import (
    SyncContext,
    backup_snippet,
    build_target_description,
    load_journal_index,
    sync_videos,
)


class FakeLedger:
    def __init__(self, budget: int = 10_000):
        self.budget = budget
        self.spent = 0
        self._costs = {"videos.list": 1, "videos.update": 50}

    def can_spend(self, op: str) -> bool:
        return self._costs[op] <= self.budget - self.spent

    def spend(self, op: str) -> int:
        self.spent += self._costs[op]
        return self.budget - self.spent


@dataclass
class FakeSnippet:
    video_id: str
    title: str = "Live Title"
    description: str = "Live description with abstract and credits."
    category_id: str = "27"
    tags: list[str] = field(default_factory=list)


class FakeClient:
    """Fake of journal_utilities.youtube.client.YouthTubeClient surface used here."""

    def __init__(self, snippets: dict[str, FakeSnippet], fail_ids: set[str] | None = None):
        self.snippets = snippets
        self.fail_ids = fail_ids or set()
        self.updates: list[tuple[str, str]] = []
        self.update_calls = 0

    def get_video_snippet(self, video_id: str):
        if video_id in self.fail_ids:
            return None  # fetch failed / video absent — no fallback exists
        return self.snippets.get(video_id)

    def update_video_snippet(self, snippet, *, dry_run: bool):
        assert dry_run is False
        self.update_calls += 1
        self.updates.append((snippet.video_id, snippet.description))
        return type("R", (), {"success": True, "error": None, "dry_run": False})()


def make_context(tmp_path: Path, client: FakeClient, index_items: list[dict], apply: bool):
    index_path = tmp_path / "INDEX.json"
    index_path.write_text(json.dumps({"items": index_items}), encoding="utf-8")
    return SyncContext(
        client=client,
        ledger=FakeLedger(),
        item_index=load_journal_index(tmp_path),
        chapters_map={},
        apply=apply,
        verify=False,
        backup_dir=tmp_path / "backup",
    )


INDEX_ITEMS = [
    {
        "path": "data/video/activeinferenceinstitute/Series/Series_001",
        "series": "Series",
        "item": "Series_001",
        "has_transcript": True,
        "parts": ["vid_known"],
    },
    {
        "path": "data/video/activeinferenceinstitute/Series/Series_002",
        "series": "Series",
        "item": "Series_002",
        "has_transcript": True,
        "parts": ["vid_backup"],
    },
]


def test_no_write_when_snippet_fetch_fails(tmp_path, caplog):
    """Rule 1: no Data API snippet -> no write, even with --apply."""
    client = FakeClient(snippets={}, fail_ids={"vid_ghost"})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=True)
    targets = [{"id": "vid_ghost", "title": "Manifest title", "description": ""}]
    with caplog.at_level(logging.ERROR):
        updated = sync_videos(ctx, targets)
    assert updated == 0
    assert client.update_calls == 0
    assert "refusing to write" in caplog.text


def test_no_write_without_api_fetched_snippet(tmp_path):
    """The api_fetched set gates writes: unknown video never enters it."""
    client = FakeClient(snippets={})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=True)
    targets = [{"id": "vid_unknown"}]
    sync_videos(ctx, targets)
    assert "vid_unknown" not in ctx.api_fetched
    assert client.update_calls == 0
    assert not (tmp_path / "backup" / "vid_unknown").exists()


def test_apply_writes_only_after_api_fetch_and_backup(tmp_path):
    client = FakeClient(snippets={"vid_known": FakeSnippet("vid_known")})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=True)
    updated = sync_videos(ctx, [{"id": "vid_known"}])
    assert updated == 1
    assert client.update_calls == 1
    backups = list((tmp_path / "backup" / "vid_known").glob("*.json"))
    assert len(backups) == 1
    payload = json.loads(backups[0].read_text(encoding="utf-8"))
    assert payload["video_id"] == "vid_known"
    assert payload["snippet"]["description"] == "Live description with abstract and credits."


def test_dry_run_default_never_writes(tmp_path):
    client = FakeClient(snippets={"vid_known": FakeSnippet("vid_known")})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=False)
    updated = sync_videos(ctx, [{"id": "vid_known"}])
    assert updated == 0
    assert client.update_calls == 0


def test_apply_resolves_transcript_link_via_index(tmp_path):
    client = FakeClient(snippets={"vid_known": FakeSnippet("vid_known")})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=True)
    sync_videos(ctx, [{"id": "vid_known"}])
    description = client.updates[0][1]
    assert "tree/main/data/video/activeinferenceinstitute/Series/Series_001" in description
    assert "blob/main/transcripts" not in description


def test_unmapped_video_writes_without_guessed_link(tmp_path):
    client = FakeClient(snippets={"vid_lost": FakeSnippet("vid_lost")})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=True)
    sync_videos(ctx, [{"id": "vid_lost"}])
    description = client.updates[0][1]
    assert "Full Transcript" not in description


def test_quota_exhaustion_stops_batch(tmp_path):
    client = FakeClient(snippets={f"vid{i}": FakeSnippet(f"vid{i}") for i in range(5)})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=True)
    ctx.ledger = FakeLedger(budget=102)  # two full (1 read + 50 update) cycles
    updated = sync_videos(ctx, [{"id": f"vid{i}"} for i in range(5)])
    assert updated == 2
    assert ctx.ledger.spent == 102


def test_build_target_description_uses_index(tmp_path):
    client = FakeClient({})
    ctx = make_context(tmp_path, client, INDEX_ITEMS, apply=False)
    desc = build_target_description("vid_known", "base", ctx)
    assert "Series_001" in desc
    lost = build_target_description("vid_unknown", "base", ctx)
    assert "Full Transcript" not in lost


def test_backup_snippet_writes_timestamped_json(tmp_path):
    snippet = FakeSnippet("v1")
    path = backup_snippet("v1", snippet, backup_dir=tmp_path / "b")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["snippet"]["title"] == "Live Title"
    assert path.parent == tmp_path / "b" / "v1"
    assert path.suffix == ".json"


def test_load_journal_index_requires_file(tmp_path):
    with pytest.raises(SystemExit):
        load_journal_index(tmp_path)
