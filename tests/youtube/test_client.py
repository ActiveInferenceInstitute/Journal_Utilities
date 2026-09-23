"""Unit tests for the vendored YouTube Data API client — fake service only.

These tests make ZERO real API calls: every test injects a fake chainable
service, mirroring the googleapiclient ``service.resource().method().execute()``
shape. The real ``_build_service`` path is never exercised here (it performs
network I/O for discovery).
"""

from journal_utilities.youtube.client import (
    QUOTA_COSTS,
    QuotaBudgetExceededError,
    QuotaLedger,
    UpdateResult,
    VideoSnippet,
    YouTubeClient,
)


class FakeRequest:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeService:
    """Chainable fake of the googleapiclient YouTube resource surface."""

    def __init__(self, videos_by_id=None, channel_uploads="", playlist_pages=None):
        self.videos_by_id = videos_by_id or {}
        self.channel_uploads = channel_uploads
        self.playlist_pages = playlist_pages or []
        self.video_updates: list[dict] = []
        self.videos_listed: list[str] = []
        self.update_called = False

    @property
    def videos(self):
        service = self

        class Videos:
            @staticmethod
            def list(*, part, id=None, **_):  # noqa: A002 — mirrors Data API param name
                service.videos_listed.append(id or "")
                ids = (id or "").split(",")
                items = [
                    {"id": v, "snippet": dict(service.videos_by_id[v])}
                    for v in ids
                    if v in service.videos_by_id
                ]
                return FakeRequest({"items": items})

            @staticmethod
            def update(*, part, body, **_):
                service.update_called = True
                service.video_updates.append(body)
                return FakeRequest({"id": body["id"], "snippet": body["snippet"]})

        return Videos

    @property
    def channels(self):
        service = self

        class Channels:
            @staticmethod
            def list(*, part, id, **_):  # noqa: A002 — mirrors Data API param name
                if service.channel_uploads:
                    item = {
                        "id": id,
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": service.channel_uploads}
                        },
                    }
                    return FakeRequest({"items": [item]})
                return FakeRequest({"items": []})

        return Channels

    @property
    def playlistItems(self):  # noqa: N802 — mirrors googleapiclient resource name
        service = self

        class PlaylistItems:
            @staticmethod
            def list(**params):
                page = service.playlist_pages.pop(0) if service.playlist_pages else {"items": []}
                if params.get("pageToken") and "next" in page:
                    return FakeRequest({"items": page.get("next", []), "nextPageToken": ""})
                return FakeRequest(page)

            @staticmethod
            def insert(*, part, body, **_):
                return FakeRequest(body)

        return PlaylistItems

    @property
    def captions(self):
        class Captions:
            @staticmethod
            def list(*, part, videoId, **_):  # noqa: N803 — mirrors Data API param name
                return FakeRequest({"items": [{"id": "cap1", "snippet": {"videoId": videoId}}]})

        return Captions

    @property
    def playlists(self):
        class Playlists:
            @staticmethod
            def list(**_):
                return FakeRequest({"items": [{"id": "pl1", "snippet": {"title": "P"}}]})

            @staticmethod
            def insert(*, part, body, **_):
                return FakeRequest({"id": "new_pl", **body})

        return Playlists


def _snippet_item(title="T", description="D", tags=None):
    return {"title": title, "description": description, "categoryId": "27", "tags": tags or ["a"]}


def test_get_video_snippet_maps_api_fields():
    client = YouTubeClient(service=FakeService(videos_by_id={"vid1": _snippet_item()}))
    snippet = client.get_video_snippet("vid1")
    assert snippet == VideoSnippet(
        video_id="vid1", title="T", description="D", category_id="27", tags=["a"]
    )


def test_get_video_snippet_missing_video_returns_none():
    client = YouTubeClient(service=FakeService())
    assert client.get_video_snippet("ghost") is None


def test_update_dry_run_makes_no_api_call():
    """Rule-1 mechanics: dry-run must not touch the API at all."""
    service = FakeService()
    client = YouTubeClient(service=service)
    result = client.update_video_snippet(
        VideoSnippet(video_id="vid1", title="t", description="d"), dry_run=True
    )
    assert result.success and result.dry_run
    assert service.update_called is False
    assert service.videos_listed == []


def test_update_live_writes_snippet_body():
    service = FakeService()
    client = YouTubeClient(service=service)
    result = client.update_video_snippet(
        VideoSnippet(video_id="vid1", title="t", description="d", tags=["x"]),
        dry_run=False,
    )
    assert result.success and not result.dry_run
    assert service.video_updates == [
        {
            "id": "vid1",
            "snippet": {"title": "t", "description": "d", "categoryId": "27", "tags": ["x"]},
        }
    ]


def test_update_failure_reports_error():
    class FailingService(FakeService):
        @property
        def videos(self):
            class Videos:
                @staticmethod
                def list(*_, **__):
                    return FakeRequest({"items": []})

                @staticmethod
                def update(*_, **__):
                    raise RuntimeError("400: invalidDescription")

            return Videos

    result = YouTubeClient(service=FailingService()).update_video_snippet(
        VideoSnippet(video_id="v", title="t", description="d"), dry_run=False
    )
    assert result.success is False
    assert "invalidDescription" in (result.error or "")
    assert isinstance(result, UpdateResult)


def test_get_video_snippets_batches_ids():
    service = FakeService(videos_by_id={f"v{i}": _snippet_item(title=f"t{i}") for i in range(4)})
    client = YouTubeClient(service=service)
    snippets = client.get_video_snippets(["v0", "v1", "v2", "v3"])
    assert set(snippets) == {"v0", "v1", "v2", "v3"}
    assert snippets["v2"].title == "t2"


def test_get_uploads_playlist_id():
    client = YouTubeClient(service=FakeService(channel_uploads="UUuploads"))
    assert client.get_uploads_playlist_id("UCxyz") == "UUuploads"
    assert YouTubeClient(service=FakeService()).get_uploads_playlist_id("UCxyz") is None


def test_list_playlist_items_paginates():
    service = FakeService(
        playlist_pages=[
            {"items": [{"id": "i1"}], "nextPageToken": "next"},
            {"items": [], "next": [{"id": "i2"}]},
        ]
    )
    items = YouTubeClient(service=service).list_playlist_items("PLx")
    assert [i["id"] for i in items] == ["i1", "i2"]


def test_list_captions_and_playlists():
    client = YouTubeClient(service=FakeService())
    assert client.list_captions("vid1")[0]["id"] == "cap1"
    assert client.list_playlists("UCxyz")[0]["id"] == "pl1"


def test_quota_costs_match_handoff_budget():
    assert QUOTA_COSTS["videos.update"] == 50
    assert QUOTA_COSTS["captions.insert"] == 400
    assert QUOTA_COSTS["playlistItems.insert"] == 50
    assert QUOTA_COSTS["videos.list"] == 1


def test_quota_ledger_accounts_and_blocks_over_budget():
    ledger = QuotaLedger(budget=101)
    assert ledger.spend("videos.list") == 100  # 1 unit
    assert ledger.spend("videos.update") == 50  # 50 units
    assert ledger.can_spend("videos.update")  # exactly 50 remaining
    assert not ledger.can_spend("captions.insert")  # 400 > 50 remaining
    try:
        ledger.spend("captions.insert")
    except QuotaBudgetExceededError:
        pass
    else:
        raise AssertionError("expected QuotaBudgetExceededError")
    assert ledger.spent == 51
    ledger.spend("videos.update")  # final 50 units fit exactly
    assert ledger.remaining == 0
