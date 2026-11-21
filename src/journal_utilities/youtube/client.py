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
- OAuth (scope ``youtube.force-ssl``) is required for writes. The Institute
  operator must select the intended channel during consent, and the write
  entry point verifies it with ``channels.list(mine=True)``.
- :class:`QuotaLedger` accounts for each request, including 50 units for
  captions.list and 400 for captions.insert.

Secrets come from env only; nothing is hardcoded or logged.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _error_kind(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    return f"HTTP {status}" if isinstance(status, int) else type(exc).__name__


#: Quota cost per Data API call, per the pipeline hard rules (default budget
#: is 10,000 units/day).
QUOTA_COSTS: dict[str, int] = {
    "channels.list": 1,
    "videos.list": 1,
    "videos.update": 50,
    "captions.list": 50,
    "captions.insert": 400,
    "playlists.list": 1,
    "playlists.insert": 50,
    "playlistItems.list": 1,
    "playlistItems.insert": 50,
}


class QuotaBudgetExceededError(RuntimeError):  # noqa: N818
    """Raised when spending an operation would exceed the configured budget."""


class YouTubeReadError(RuntimeError):
    """Raised when an API read cannot support a definite result."""


@dataclass(frozen=True)
class VideoSnippet:
    """The snippet fields the sync pipeline reads and writes."""

    video_id: str
    title: str = ""
    description: str = ""
    category_id: str = "27"
    tags: list[str] = field(default_factory=list)
    default_language: str | None = None
    channel_id: str = ""

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> VideoSnippet:
        """Build from a ``videos.list`` item."""
        snippet = item.get("snippet", {})
        return cls(
            video_id=item.get("id", ""),
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            category_id=snippet.get("categoryId", ""),
            tags=list(snippet.get("tags") or []),
            default_language=snippet.get("defaultLanguage"),
            channel_id=snippet.get("channelId", ""),
        )

    def to_body(self) -> dict[str, Any]:
        """Build the ``videos.update`` request body."""
        snippet = {
            "title": self.title,
            "description": self.description,
            "categoryId": self.category_id,
            "tags": self.tags,
        }
        if self.default_language is not None:
            snippet["defaultLanguage"] = self.default_language
        return {"id": self.video_id, "snippet": snippet}


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
        return QUOTA_COSTS[operation] <= self.remaining

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
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
        from httplib2 import Http

        http = Http(timeout=30)
        if self._api_key and not (self._client_secrets_path or self._token_path):
            logger.info("Building read-only YouTube service (API key).")
            return build(
                "youtube", "v3", developerKey=self._api_key, http=http, cache_discovery=False
            )

        credentials = self._load_oauth_credentials()
        logger.info("Building YouTube service with OAuth (youtube.force-ssl).")
        return build(
            "youtube", "v3", http=AuthorizedHttp(credentials, http=http), cache_discovery=False
        )

    def _load_oauth_credentials(self) -> Any:  # noqa: ANN401
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds: Credentials | None = None
        if self._token_path and Path(self._token_path).is_file():
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                self._token_path, [self.SCOPE]
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())  # type: ignore[no-untyped-call]
            elif self._client_secrets_path:
                from google_auth_oauthlib.flow import InstalledAppFlow

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
                token = Path(self._token_path)
                fd, temporary = tempfile.mkstemp(prefix=f".{token.name}.", dir=token.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        stream.write(creds.to_json())
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, token)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        return creds

    # ------------------------------------------------------------------ reads

    def _list_response(
        self,
        operation: str,
        params: dict[str, Any],
        *,
        ledger: QuotaLedger | None,
        strict: bool,
    ) -> dict[str, Any] | None:
        if ledger is not None:
            ledger.spend(operation)
        try:
            resource = getattr(self.service, operation.removesuffix(".list"))()
            response = resource.list(**params).execute()
        except Exception as exc:
            # The provider exception can contain a URL with an API key.
            message = f"{operation} failed ({_error_kind(exc)})"
            if strict:
                raise YouTubeReadError(message) from None
            logger.warning("%s", message)
            return None
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("items"), list)
            or any(not isinstance(item, dict) for item in response["items"])
        ):
            message = f"{operation} returned a malformed response"
            if strict:
                raise YouTubeReadError(message)
            logger.warning("%s", message)
            return None
        return dict(response)

    def _list_pages(
        self,
        operation: str,
        params: dict[str, Any],
        *,
        ledger: QuotaLedger | None,
        strict: bool,
    ) -> Iterator[dict[str, Any]]:
        seen = set()
        while True:
            response = self._list_response(operation, params, ledger=ledger, strict=strict)
            if response is None:
                return
            yield from response["items"]
            token = response.get("nextPageToken")
            if token is None or token == "":
                return
            if not isinstance(token, str) or token in seen:
                message = f"{operation} returned an invalid or repeated page token"
                if strict:
                    raise YouTubeReadError(message)
                logger.warning("%s", message)
                return
            seen.add(token)
            params = {**params, "pageToken": token}

    def require_channel(self, channel_id: str, *, ledger: QuotaLedger | None = None) -> None:
        """Verify the OAuth session selects exactly the expected YouTube channel."""
        response = self._list_response(
            "channels.list", {"part": "id", "mine": True}, ledger=ledger, strict=True
        )
        if (
            response is None
            or response.get("nextPageToken")
            or [item.get("id") for item in response["items"]] != [channel_id]
        ):
            raise YouTubeReadError("OAuth does not select the expected YouTube channel")

    def get_video_snippet(self, video_id: str) -> VideoSnippet | None:
        """Fetch the live snippet via the Data API (videos.list, 1 unit).

        Returns ``None`` when the video is not found or the call fails —
        callers MUST treat ``None`` as "no write allowed" (Rule 1); there is no
        manifest/yt-dlp fallback.
        """
        response = self._list_response(
            "videos.list", {"part": "snippet", "id": video_id}, ledger=None, strict=False
        )
        if not response or len(response["items"]) != 1:
            return None
        item = response["items"][0]
        if item.get("id") != video_id or not isinstance(item.get("snippet"), dict):
            return None
        return VideoSnippet.from_api(item)

    def get_video_snippets(
        self, video_ids: list[str], batch_size: int = 50
    ) -> dict[str, VideoSnippet]:
        """Batch ``videos.list`` (1 unit per batch of up to 50 IDs)."""
        snippets: dict[str, VideoSnippet] = {}
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i : i + batch_size]
            response = self._list_response(
                "videos.list", {"part": "snippet", "id": ",".join(batch)}, ledger=None, strict=False
            )
            if response is None:
                continue
            for item in response["items"]:
                snippet = VideoSnippet.from_api(item)
                if snippet.video_id:
                    snippets[snippet.video_id] = snippet
        return snippets

    def get_uploads_playlist_id(
        self, channel_id: str, *, strict: bool = False, ledger: QuotaLedger | None = None
    ) -> str | None:
        """Return the channel's uploads playlist ID (channels.list, 1 unit)."""
        response = self._list_response(
            "channels.list",
            {"part": "contentDetails", "id": channel_id},
            ledger=ledger,
            strict=strict,
        )
        items = response["items"] if response else []
        if len(items) == 1 and items[0].get("id") == channel_id:
            content = items[0].get("contentDetails")
            related = content.get("relatedPlaylists") if isinstance(content, dict) else None
            uploads = related.get("uploads") if isinstance(related, dict) else None
            if isinstance(uploads, str) and uploads:
                return uploads
        if strict:
            raise YouTubeReadError("Could not verify the channel's uploads playlist")
        return None

    def list_playlist_items(
        self, playlist_id: str, *, strict: bool = False, ledger: QuotaLedger | None = None
    ) -> list[dict[str, Any]]:
        """Page through a playlist's items (playlistItems.list, 1 unit/page)."""
        return list(
            self._list_pages(
                "playlistItems.list",
                {
                    "part": "contentDetails,snippet",
                    "playlistId": playlist_id,
                    "maxResults": 50,
                },
                ledger=ledger,
                strict=strict,
            )
        )

    def list_captions(
        self, video_id: str, *, strict: bool = False, ledger: QuotaLedger | None = None
    ) -> list[dict[str, Any]]:
        """List caption tracks using OAuth (50 units)."""
        response = self._list_response(
            "captions.list", {"part": "snippet", "videoId": video_id}, ledger=ledger, strict=strict
        )
        return response["items"] if response else []

    def list_playlists(
        self, channel_id: str, *, strict: bool = False, ledger: QuotaLedger | None = None
    ) -> list[dict[str, Any]]:
        """Page through a channel's playlists (playlists.list, 1 unit/page)."""
        return list(
            self._list_pages(
                "playlists.list",
                {
                    "part": "snippet,contentDetails,status",
                    "channelId": channel_id,
                    "maxResults": 50,
                },
                ledger=ledger,
                strict=strict,
            )
        )

    # ----------------------------------------------------------------- writes

    def update_video_snippet(self, snippet: VideoSnippet, *, dry_run: bool = True) -> UpdateResult:
        """videos.update (50 units). ``dry_run=True`` performs no API call."""
        if dry_run:
            return UpdateResult(success=True, dry_run=True)
        try:
            self.service.videos().update(part="snippet", body=snippet.to_body()).execute()
        except Exception as exc:
            error = _error_kind(exc)
            logger.error("videos.update failed for %s (%s)", snippet.video_id, error)
            return UpdateResult(success=False, error=error)
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
            logger.error("captions.insert failed for %s (%s)", video_id, _error_kind(exc))
            return None
        return dict(response)

    def list_videos(
        self,
        video_ids: list[str],
        part: str = "snippet,statistics",
        *,
        strict: bool = False,
        ledger: QuotaLedger | None = None,
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
            response = self._list_response(
                "videos.list",
                {"part": part, "id": ",".join(chunk)},
                ledger=ledger,
                strict=strict,
            )
            if response is not None:
                items = response["items"]
                if strict:
                    returned = [item.get("id") for item in items]
                    if (
                        any(not isinstance(vid, str) or vid not in chunk for vid in returned)
                        or len(set(returned)) != len(returned)
                        or response.get("nextPageToken")
                    ):
                        raise YouTubeReadError("videos.list did not return the requested IDs")
                out.extend(items)
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
