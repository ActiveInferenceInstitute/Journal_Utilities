"""Fake Data API service for ingest tests (no network, no API key).

Mirrors the ``FakeService`` pattern from ``tests/youtube/test_client.py``,
shaped for the ingest module's calls: uploads-playlist resolution, paginated
playlist items with contentDetails, and batched videos.list with
snippet/contentDetails/status parts.
"""

from __future__ import annotations

from typing import Any


class FakeRequest:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def execute(self) -> dict[str, Any]:
        return self._result


def playlist_item(video_id: str, published_at: str = "2026-09-20T10:00:00Z") -> dict[str, Any]:
    """playlistItems.list payload for one upload."""
    return {
        "id": f"plitem-{video_id}",
        "snippet": {
            "title": f"title-for-{video_id}",
            "resourceId": {"videoId": video_id},
            "publishedAt": published_at,
        },
        "contentDetails": {"videoId": video_id, "videoPublishedAt": published_at},
    }


def video_item(
    video_id: str,
    title: str,
    published_at: str = "2026-09-20T10:00:00Z",
    duration: str = "PT1H",
    live_broadcast: str = "none",
    privacy: str = "public",
    upload_status: str = "processed",
) -> dict[str, Any]:
    """videos.list payload for one video (part=snippet,contentDetails,status)."""
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "publishedAt": published_at,
            "liveBroadcastContent": live_broadcast,
            "description": f"description for {video_id}",
        },
        "contentDetails": {"duration": duration},
        "status": {"privacyStatus": privacy, "uploadStatus": upload_status},
    }


class FakeService:
    """Chainable fake of the googleapiclient YouTube resource surface.

    Serves ``self.playlist_items`` 50-at-a-time with a second page for any
    remainder (exercises pagination), and answers videos.list strictly from
    ``self.videos_by_id``.
    """

    def __init__(
        self,
        channel_uploads: str = "UUfake",
        playlist_items: list[dict[str, Any]] | None = None,
        videos_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.channel_uploads = channel_uploads
        self.playlist_items = playlist_items or []
        self.videos_by_id = videos_by_id or {}
        self.playlist_pages_served = 0
        self.videos_listed: list[str] = []

    @property
    def channels(self) -> Any:  # noqa: ANN401 — mirrors untyped googleapiclient
        service = self

        class Channels:
            @staticmethod
            def list(*, part: str, id: str, **_: Any) -> FakeRequest:  # noqa: A002
                if service.channel_uploads:
                    return FakeRequest(
                        {
                            "items": [
                                {
                                    "id": id,
                                    "contentDetails": {
                                        "relatedPlaylists": {"uploads": service.channel_uploads}
                                    },
                                }
                            ]
                        }
                    )
                return FakeRequest({"items": []})

        return Channels

    @property
    def playlistItems(self) -> Any:  # noqa: ANN401, N802 — mirrors googleapiclient
        service = self

        class PlaylistItems:
            @staticmethod
            def list(**params: Any) -> FakeRequest:
                service.playlist_pages_served += 1
                items = service.playlist_items
                if params.get("pageToken") == "page-2":
                    return FakeRequest({"items": items[50:]})
                if len(items) > 50:
                    return FakeRequest({"items": items[:50], "nextPageToken": "page-2"})
                return FakeRequest({"items": items})

        return PlaylistItems

    @property
    def videos(self) -> Any:  # noqa: ANN401
        service = self

        class Videos:
            @staticmethod
            def list(*, part: str, id: str | None = None, **_: Any) -> FakeRequest:  # noqa: A002
                service.videos_listed.append(id or "")
                ids = (id or "").split(",")
                items = [service.videos_by_id[v] for v in ids if v in service.videos_by_id]
                return FakeRequest({"items": items})

        return Videos
