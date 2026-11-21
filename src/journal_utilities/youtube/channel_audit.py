"""Collect channel evidence and plan narrowly scoped description repairs."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, unquote, urlsplit
from zoneinfo import ZoneInfo

from journal_utilities.ingest.enumerate import (
    ChannelVideo,
    Worklist,
    parse_iso8601_duration,
)
from journal_utilities.youtube.client import (
    QuotaLedger,
    VideoSnippet,
    YouTubeClient,
    YouTubeReadError,
)
from journal_utilities.youtube.metadata_formatter import (
    build_video_item_index,
    resolve_video_journal_url,
)

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
URL = re.compile(r"""https?://[^\s<>"']+[^\s<>"'.,;:!?)\]]""", re.IGNORECASE)
SEQUENCE = re.compile(r"\b(?:Session|Meeting)\s+#?(\d+)\b", re.IGNORECASE)
PARR_COHORT = re.compile(r"\bParr\b.*\bCohort\s+(\d+)\b", re.IGNORECASE)
TITLE_DATE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
JOURNAL_REPOSITORY = "/activeinferenceinstitute/activeinferencejournal"
CLASSES = frozenset({"dead", "legacy", "backlink"})
INSTITUTE_HOSTS = frozenset(
    {
        "activeinference.institute",
        "www.activeinference.institute",
        "activities.activeinference.institute",
        "discord.activeinference.institute",
        "donate.activeinference.institute",
        "video.activeinference.institute",
        "activeinference.org",
        "www.activeinference.org",
    }
)
EXACT_LEGACY = {
    ("activeinference.org", ""): "https://www.activeinference.institute/",
    ("www.activeinference.org", ""): "https://www.activeinference.institute/",
    ("twitter.com", "/inferenceactive"): "https://x.com/InferenceActive",
    ("www.twitter.com", "/inferenceactive"): "https://x.com/InferenceActive",
    ("discord.gg", "/8VNKNp4jtx"): "https://discord.activeinference.institute/",
    ("youtube.com", "/c/activeinference"): "https://www.youtube.com/@ActiveInference",
    ("www.youtube.com", "/c/activeinference"): "https://www.youtube.com/@ActiveInference",
}


def stable_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_index(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    """Require readable index evidence before computing coverage or backlinks."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    items = payload.get("items") if isinstance(payload, dict) else None
    if (
        not isinstance(items, list)
        or not items
        or any(
            not isinstance(item, dict) or not isinstance(item.get("parts"), list) for item in items
        )
    ):
        raise ValueError("Journal INDEX.json lacks a valid items/parts catalog")
    index = build_video_item_index(items)
    if not index or any(not VIDEO_ID.fullmatch(key) for key in index):
        raise ValueError("Journal INDEX.json lacks a valid video ID catalog")
    return index, hashlib.sha256(raw).hexdigest()


def split_url(value: str) -> SplitResult | None:
    try:
        parts = urlsplit(value)
        if parts.hostname and not parts.username and not parts.password and parts.port is None:
            return parts
    except ValueError:
        pass
    return None


def classify_link(value: str) -> tuple[str, str | None] | None:
    """Classify known patterns and propose only unambiguous replacements."""
    parts = split_url(value)
    if parts is None:
        return None
    host, path = parts.hostname or "", parts.path.rstrip("/")
    if host == "coda.io" and (
        path == "/@active-inference-institute" or path.startswith("/@active-inference-institute/")
    ):
        return "dead", None
    if host in {"activeinference.org", "www.activeinference.org"} and (
        path == "/education" or path.startswith("/education/")
    ):
        return "dead", None
    replacement = EXACT_LEGACY.get((host, path)) or EXACT_LEGACY.get((host, path.lower()))
    if replacement is not None and not (parts.query or parts.fragment):
        return "legacy", replacement
    if host in INSTITUTE_HOSTS and host.endswith(".institute") and parts.scheme == "http":
        return "legacy", parts._replace(scheme="https").geturl()
    return None


def _journal_item_paths(links: list[str]) -> set[tuple[str, str]]:
    item_paths = set()
    for link in links:
        parts = split_url(link)
        if parts is None:
            continue
        path = unquote(parts.path).rstrip("/")
        if parts.hostname == "github.com" and path.lower().startswith(
            JOURNAL_REPOSITORY + "/tree/main/data/video/"
        ):
            item_paths.add(("github.com", path.split("/tree/main/", 1)[-1]))
        if parts.hostname == "activeinferenceinstitute.github.io" and path.lower().startswith(
            "/activeinferencejournal/items/"
        ):
            item_paths.add(("activeinferenceinstitute.github.io", path))
    return item_paths


def journal_backlink(video_id: str, index: dict[str, dict[str, Any]]) -> tuple[str | None, bool]:
    """Resolve the canonical item separately from transcript availability."""
    return (
        resolve_video_journal_url(video_id, index, has_transcript=True),
        bool(index.get(video_id, {}).get("has_transcript")),
    )


def description_changes(
    description: str,
    journal_url: str | None,
    classes: frozenset[str],
    *,
    has_transcript: bool = True,
) -> tuple[str, list[dict[str, str]]]:
    """Detect dead/old links and add an indexed backlink without reformatting prose."""
    findings: list[dict[str, str]] = []
    links = URL.findall(description)
    if any(repeats > 1 for repeats in Counter(links).values()):
        findings.append({"kind": "duplicate_link"})

    def replace(match: re.Match[str]) -> str:
        link = match.group()
        info = classify_link(link)
        if info is None:
            return link
        kind, replacement = info
        # Avoid retaining URL query data in findings.
        parts = split_url(link)
        evidence = parts._replace(query="", fragment="").geturl() if parts else ""
        findings.append(
            {
                "kind": kind,
                "link": evidence,
                "repairable": "yes" if replacement is not None else "no",
            }
        )
        return replacement if kind in classes and replacement else link

    proposed = URL.sub(replace, description)
    if journal_url is not None:
        existing = _journal_item_paths(links)
        expected = _journal_item_paths([journal_url])
        if not (existing & expected):
            if existing:
                findings.append({"kind": "different_journal_link"})
            else:
                findings.append({"kind": "backlink"})
                if "backlink" in classes:
                    heading = "RESOURCES & TRANSCRIPT" if has_transcript else "JOURNAL RECORD"
                    proposed = (proposed.rstrip() + f"\n\n{heading}\n{journal_url}").lstrip("\n")
    return proposed, findings


def is_completed_public(item: dict[str, Any], channel_id: str) -> bool:
    snippet, status = item.get("snippet"), item.get("status")
    return (
        isinstance(snippet, dict)
        and isinstance(status, dict)
        and snippet.get("channelId") == channel_id
        and snippet.get("liveBroadcastContent") == "none"
        and isinstance(snippet.get("title"), str)
        and bool(snippet["title"])
        and isinstance(snippet.get("description"), str)
        and isinstance(snippet.get("categoryId"), str)
        and bool(snippet["categoryId"])
        and status.get("privacyStatus") == "public"
        and status.get("uploadStatus") == "processed"
    )


def _playlist_video_ids(items: list[dict[str, Any]]) -> list[str]:
    ids = []
    for item in items:
        content = item.get("contentDetails")
        video_id = content.get("videoId") if isinstance(content, dict) else None
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            raise YouTubeReadError("A playlist item lacks a valid video ID")
        ids.append(video_id)
    return ids


def _title_date_mismatch(title: str, actual_start: object, timezone: ZoneInfo) -> bool:
    match = TITLE_DATE.search(title)
    if not match or not isinstance(actual_start, str):
        return False
    try:
        start = datetime.fromisoformat(actual_start)
        if start.tzinfo is None:
            return False
        text = match.group()
        titled = (
            datetime.fromisoformat(text)
            if text[0].isdigit()
            else datetime.strptime(text.replace(",", ""), "%B %d %Y")
        )
    except ValueError:
        return False
    return titled.date() != start.astimezone(timezone).date()


def _playlist_findings(
    client: YouTubeClient,
    channel_id: str,
    ledger: QuotaLedger,
) -> list[dict[str, str]]:
    findings = []
    for playlist in client.list_playlists(channel_id, strict=True, ledger=ledger):
        snippet, status = playlist.get("snippet"), playlist.get("status")
        if not isinstance(snippet, dict) or not isinstance(status, dict):
            raise YouTubeReadError("A playlist lacks visibility or channel evidence")
        if snippet.get("channelId") != channel_id or status.get("privacyStatus") != "public":
            continue
        playlist_id = playlist.get("id")
        title = snippet.get("title")
        if not isinstance(playlist_id, str) or not playlist_id or not isinstance(title, str):
            raise YouTubeReadError("A public playlist lacks an ID or title")
        cohort = PARR_COHORT.search(title)
        if (
            cohort
            and title != f"Active Inference Textbook Group ~ Parr et al. 2022 ~ Cohort {cohort[1]}"
        ):
            findings.append({"kind": "cohort_title", "playlist_id": playlist_id})
        entries = client.list_playlist_items(playlist_id, strict=True, ledger=ledger)
        titles = [str((entry.get("snippet") or {}).get("title") or "") for entry in entries]
        if any(
            title.casefold() in {"private video", "deleted video", "[private video]"}
            for title in titles
        ):
            findings.append({"kind": "unavailable_playlist_entry", "playlist_id": playlist_id})
        if cohort or "fundamentals" in title.casefold():
            numbers = [int(match[1]) for title in titles if (match := SEQUENCE.search(title))]
            if any(before > after for before, after in zip(numbers, numbers[1:], strict=False)):
                findings.append({"kind": "playlist_order", "playlist_id": playlist_id})
    return findings


def audit_channel(
    client: YouTubeClient,
    channel_id: str,
    ledger: QuotaLedger,
    index: dict[str, dict[str, Any]],
    classes: frozenset[str],
    timezone: ZoneInfo,
    *,
    link_status: Callable[[str], int | None] | None = None,
) -> tuple[Worklist, list[dict[str, str]], list[dict[str, str]], int]:
    """Require complete API calls before exporting a public backlog or repair plan."""
    uploads = client.get_uploads_playlist_id(channel_id, strict=True, ledger=ledger)
    if uploads is None:
        raise YouTubeReadError("Could not verify the uploads playlist")
    ids = list(
        dict.fromkeys(
            _playlist_video_ids(client.list_playlist_items(uploads, strict=True, ledger=ledger))
        )
    )
    details = client.list_videos(
        ids, part="snippet,status,contentDetails,liveStreamingDetails", strict=True, ledger=ledger
    )
    worklist = Worklist(channel_id, index_video_count=len(index), channel_video_count=len(ids))
    findings = _playlist_findings(client, channel_id, ledger)
    repairs = []
    link_checks: dict[str, int | None] = {}
    for item in details:
        if not is_completed_public(item, channel_id):
            continue
        vid = item["id"]
        live = VideoSnippet.from_api(item)
        if vid not in index:
            snippet = item["snippet"]
            worklist.new_videos.append(
                ChannelVideo(
                    video_id=vid,
                    title=live.title,
                    published_at=snippet.get("publishedAt", ""),
                    duration_seconds=parse_iso8601_duration(
                        (item.get("contentDetails") or {}).get("duration", "")
                    ),
                    privacy_status="public",
                    upload_status="processed",
                    broadcast_status="none",
                    description=live.description,
                )
            )
            findings.append({"kind": "missing_from_journal", "video_id": vid})
        journal_url, has_transcript = journal_backlink(vid, index)
        proposed, issues = description_changes(
            live.description, journal_url, classes, has_transcript=has_transcript
        )
        findings.extend({**issue, "video_id": vid} for issue in issues)
        if link_status is not None:
            for link in dict.fromkeys(URL.findall(live.description)):
                parts = split_url(link)
                if parts is None or parts.hostname not in INSTITUTE_HOSTS:
                    continue
                public_url = parts._replace(query="", fragment="").geturl()
                if public_url not in link_checks:
                    link_checks[public_url] = link_status(public_url)
                if link_checks[public_url] in {404, 410}:
                    findings.append({"kind": "http_dead", "video_id": vid, "link": public_url})
        if proposed != live.description and len(proposed.encode()) <= 5000:
            repairs.append(
                {
                    "video_id": vid,
                    "before_sha256": stable_digest(live.to_body()),
                    "before": live.description,
                    "after": proposed,
                }
            )
        elif proposed != live.description:
            findings.append({"kind": "description_limit", "video_id": vid})
        snippet = item["snippet"]
        audio, metadata = snippet.get("defaultAudioLanguage"), snippet.get("defaultLanguage")
        if (
            isinstance(audio, str)
            and isinstance(metadata, str)
            and audio.casefold() != metadata.casefold()
        ):
            findings.append({"kind": "language_mismatch", "video_id": vid})
        start = (item.get("liveStreamingDetails") or {}).get("actualStartTime")
        if _title_date_mismatch(live.title, start, timezone):
            findings.append({"kind": "title_date", "video_id": vid})
    return worklist, findings, repairs, len(ids) - len(details)
