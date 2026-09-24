"""Minimal vendored YouTube Data API v3 client.

Replaces the sys.path hack importing the private ``instituteos`` YouTubeClient
(Y3/E7/I6). Covers exactly what the metadata sync needs:

- reads:  videos.list, captions.list, playlists.list, playlistItems.list,
          channels.list (uploads playlist)
- writes: videos.update, captions.insert, playlists.insert,
          playlistItems.insert

Design:
- Zero real calls unless a real ``service`` is built; unit tests inject a fake
  service (or a fake client) — nothing here talks to YouTube on its own.
- Google libraries are imported lazily so the module is importable (and
  testable with fakes) without google-api-python-client present.
- OAuth (scope ``youtube.force-ssl``) is required for writes; an API key alone
  only builds a read-only service. OAuth token owner (DAF, 2026-09):
  **admin@activeinference.institute** — the org account
  ``ActiveInferenceInstitute``. The ``ActInfInstitute`` account is
  personal/admin: do NOT authorize writes with it.
- :class:`QuotaLedger` implements the per-call quota accounting mandated by the
  handoff (videos.update=50, captions.insert=400, playlistItems.insert=50,
  list=1) against the 10,000 units/day default budget.

Secrets come from env only; nothing is hardcoded or logged.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Quota cost per Data API call, per the pipeline hard rules (default budget
#: is 10,000 units/day).
QUOTA_COSTS: dict[str, int] = {
    "channels.list": 1,
    "videos.list": 1,
    "videos.update": 50,
    "captions.list": 1,
    "captions.insert": 400,
    "playlists.list": 1,
    "playlists.insert": 50,
    "playlistItems.list": 1,
    "playlistItems.insert": 50,
}


class QuotaBudgetExceededError(RuntimeError):  # noqa: N818
    """Raised when spending an operation would exceed the configured budget."""


@dataclass(frozen=True)
class VideoSnippet:
    """The snippet fields the sync pipeline reads and writes."""

    video_id: str
    title: str = ""
    description: str = ""
    category_id: str = "27"
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> VideoSnippet:
        """Build from a ``videos.list`` item."""
        snippet = item.get("snippet", {})
        return cls(
            video_id=item.get("id", ""),
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            category_id=snippet.get("categoryId", "27"),
            tags=list(snippet.get("tags") or []),
        )

    def to_body(self) -> dict[str, Any]:
        """Build the ``videos.update`` request body."""
        return {
            "id": self.video_id,
            "snippet": {
                "title": self.title,
                "description": self.description,
                "categoryId": self.category_id,
                "tags": self.tags,
            },
        }


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of a ``videos.update`` call."""

    success: bool
    error: str | None = None
    dry_run: bool = False


@dataclass
class QuotaLedger:
    """Per-call quota accounting against a daily budget (in units)."""

    budget: int
    spent: int = 0

    @property
    def remaining(self) -> int:
        return self.budget - self.spent

    def can_spend(self, operation: str) -> bool:
        return QUOTA_COSTS.get(operation, 0) <= self.remaining

    def spend(self, operation: str) -> int:
        """Charge ``operation`` against the budget; returns units remaining.

        Raises :class:`QuotaBudgetExceededError` when the cost would exceed the
        budget — callers stop the batch instead of guessing.
        """
        cost = QUOTA_COSTS[operation]
        if cost > self.remaining:
            raise QuotaBudgetExceededError(
                f"{operation} costs {cost} units but only {self.remaining} remain "
                f"(budget {self.budget}, spent {self.spent})"
            )
        self.spent += cost
        return self.remaining


class YouTubeClient:
    """Thin Data API wrapper. ``service`` is injectable for fake-driven tests."""

    SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client_secrets_path: str | None = None,
        token_path: str | None = None,
        service: Any | None = None,  # noqa: ANN401
    ) -> None:
        self._api_key = api_key
        self._client_secrets_path = client_secrets_path
        self._token_path = token_path
        self._service = service

    # ------------------------------------------------------------------ setup

    @property
    def service(self) -> Any:  # noqa: ANN401
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self) -> Any:  # noqa: ANN401
        """Build a googleapiclient service (lazily; never at import time).

        With only an ``api_key`` the service is read-only (API keys cannot
        authorize writes). Writes require OAuth via ``client_secrets_path``
        (+ ``token_path`` to cache credentials) — scope ``youtube.force-ssl``.
        """
        # httplib2 (googleapiclient's transport) has no per-request timeout; a
        # dead connection otherwise stalls a batch run forever (observed on
        # videos.update 2026-09-24). The global socket timeout bounds every
        # request; reads and writes complete well inside it.
        socket.setdefaulttimeout(120)

        from googleapiclient.discovery import build

        if self._api_key and not (self._client_secrets_path or self._token_path):
            logger.info("Building read-only YouTube service (API key).")
            return build(
                "youtube",
                "v3",
                developerKey=self._api_key,
                static_discovery=False,
            )

        credentials = self._load_oauth_credentials()
        logger.info("Building YouTube service with OAuth (youtube.force-ssl).")
        return build("youtube", "v3", credentials=credentials, static_discovery=False)

    def _load_oauth_credentials(self) -> Any:  # noqa: ANN401
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        # google_auth_oauthlib ships no stubs and is an optional runtime dep
        # (write mode only); import-not-found is suppressed for that reason.
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds: Credentials | None = None
        if self._token_path and Path(self._token_path).is_file():
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                self._token_path, [self.SCOPE]
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())  # type: ignore[no-untyped-call]
            elif self._client_secrets_path:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._client_secrets_path, [self.SCOPE]
                )
                creds = flow.run_local_server(port=0)
            else:
                raise RuntimeError(
                    "YouTube writes need OAuth: set YOUTUBE_CLIENT_SECRETS (and "
                    "YOUTUBE_TOKEN_PATH to cache the token); an API key alone "
                    "cannot authorize videos.update / captions.insert."
                )
            if self._token_path:
                Path(self._token_path).write_text(creds.to_json(), encoding="utf-8")
        return creds

    # ------------------------------------------------------------------ reads

    def get_video_snippet(self, video_id: str) -> VideoSnippet | None:
        """Fetch the live snippet via the Data API (videos.list, 1 unit).

        Returns ``None`` when the video is not found or the call fails —
        callers MUST treat ``None`` as "no write allowed" (Rule 1); there is no
        manifest/yt-dlp fallback.
        """
        try:
            response = self.service.videos().list(part="snippet", id=video_id).execute()
        except Exception as exc:  # googleapiclient raises HttpError family
            logger.warning("videos.list failed for %s: %s", video_id, exc)
            return None
        items = response.get("items", [])
        if not items:
            return None
        return VideoSnippet.from_api(items[0])

    def get_video_snippets(
        self, video_ids: list[str], batch_size: int = 50
    ) -> dict[str, VideoSnippet]:
        """Batch ``videos.list`` (1 unit per batch of up to 50 IDs)."""
        snippets: dict[str, VideoSnippet] = {}
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i : i + batch_size]
            try:
                response = self.service.videos().list(part="snippet", id=",".join(batch)).execute()
            except Exception as exc:
                logger.warning("videos.list batch failed: %s", exc)
                continue
            for item in response.get("items", []):
                snippet = VideoSnippet.from_api(item)
                if snippet.video_id:
                    snippets[snippet.video_id] = snippet
        return snippets

    def get_uploads_playlist_id(self, channel_id: str) -> str | None:
        """Return the channel's uploads playlist ID (channels.list, 1 unit)."""
        try:
            response = self.service.channels().list(part="contentDetails", id=channel_id).execute()
        except Exception as exc:
            logger.warning("channels.list failed for %s: %s", channel_id, exc)
            return None
        items = response.get("items", [])
        if not items:
            return None
        # uploads playlist id; API shape is nested gets typed Any
        uploads = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        return str(uploads) if uploads else None

    def list_playlist_items(self, playlist_id: str) -> list[dict[str, Any]]:
        """Page through a playlist's items (playlistItems.list, 1 unit/page)."""
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "part": "contentDetails,snippet",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                response = self.service.playlistItems().list(**params).execute()
            except Exception as exc:
                logger.warning("playlistItems.list failed: %s", exc)
                break
            items.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return items

    def list_captions(self, video_id: str) -> list[dict[str, Any]]:
        """List caption tracks (captions.list, 1 unit). Read-only with API key."""
        try:
            response = self.service.captions().list(part="snippet", videoId=video_id).execute()
        except Exception as exc:
            logger.warning("captions.list failed for %s: %s", video_id, exc)
            return []
        return list(response.get("items", []))

    def list_playlists(self, channel_id: str) -> list[dict[str, Any]]:
        """Page through a channel's playlists (playlists.list, 1 unit/page)."""
        playlists: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "channelId": channel_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                response = self.service.playlists().list(**params).execute()
            except Exception as exc:
                logger.warning("playlists.list failed: %s", exc)
                break
            playlists.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return playlists

    # ----------------------------------------------------------------- writes

    def update_video_snippet(self, snippet: VideoSnippet, *, dry_run: bool = True) -> UpdateResult:
        """videos.update (50 units). ``dry_run=True`` performs no API call."""
        if dry_run:
            return UpdateResult(success=True, dry_run=True)
        try:
            self.service.videos().update(part="snippet", body=snippet.to_body()).execute()
        except Exception as exc:
            logger.error("videos.update failed for %s: %s", snippet.video_id, exc)
            return UpdateResult(success=False, error=str(exc))
        return UpdateResult(success=True)

    def insert_caption(
        self, video_id: str, name: str, language: str, path: str, *, is_draft: bool = False
    ) -> dict[str, Any] | None:
        """Upload a caption track (captions.insert, 400 units). Requires OAuth.

        ``is_draft`` maps to the snippet ``isDraft`` field; journal uploads
        always pass ``is_draft=False`` (a draft track would need a second
        media upload to publish).
        """
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(path, mimetype="application/octet-stream", resumable=False)
        try:
            response = (
                self.service.captions()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "name": name,
                            "language": language,
                            "videoId": video_id,
                            "isDraft": is_draft,
                        }
                    },
                    media_body=media,
                )
                .execute()
            )
        except Exception as exc:
            logger.error("captions.insert failed for %s: %s", video_id, exc)
            return None
        return dict(response)

    def list_videos(
        self, video_ids: list[str], part: str = "snippet,statistics"
    ) -> list[dict[str, Any]]:
        """videos.list (1 unit per call; up to 50 comma-separated ids each).

        Read-only: works with an API-key service. Used by the captions
        worklist to fetch view counts without yt-dlp (handoff rule 10).
        """
        out: list[dict[str, Any]] = []
        for i in range(0, len(video_ids), 50):
            chunk = [vid for vid in video_ids[i : i + 50] if vid]
            if not chunk:
                continue
            try:
                response = (
                    self.service.videos()
                    .list(part=part, id=",".join(chunk), maxResults=50)
                    .execute()
                )
            except Exception as exc:
                logger.error("videos.list failed for batch %d: %s", i // 50, exc)
                continue
            out.extend(response.get("items", []))
        return out

    def insert_playlist(
        self, title: str, description: str = "", privacy_status: str = "public"
    ) -> dict[str, Any] | None:
        """Create a playlist (playlists.insert, 50 units). Requires OAuth."""
        body = {
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy_status},
        }
        try:
            response = self.service.playlists().insert(part="snippet,status", body=body).execute()
        except Exception as exc:
            logger.error("playlists.insert failed for %r: %s", title, exc)
            return None
        return dict(response)

    def insert_playlist_item(self, playlist_id: str, video_id: str) -> dict[str, Any] | None:
        """Add a video to a playlist (playlistItems.insert, 50 units). Requires OAuth."""
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        try:
            response = self.service.playlistItems().insert(part="snippet", body=body).execute()
        except Exception as exc:
            logger.error("playlistItems.insert failed for %s: %s", video_id, exc)
            return None
        return dict(response)
