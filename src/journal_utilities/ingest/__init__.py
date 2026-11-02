"""Weekly ingest: secret-free enumeration, journal diffing, metadata scaffolds.

Three composable steps, all read-only by default (dry-run is the default for
every CLI; files are only written behind ``--no-dry-run``):

1. :mod:`journal_utilities.ingest.ytdlp` — the **secret-free** weekly
   enumeration: yt-dlp flat channel manifest -> new-video delta -> one full
   per-video extraction per new video (privacy/broadcast evidence; anything
   undeterminable is recorded as ``"unknown"``). No API key, no quota.
   :mod:`journal_utilities.ingest.enumerate` is the Data API alternative and
   needs ``YOUTUBE_API_KEY``.
2. :mod:`journal_utilities.ingest.scaffold` — per-item ``metadata.json``
   scaffolds for worklist entries (``transcript_kind: "youtube"``,
   ``status`` = ``scheduled`` for premieres / ``published`` / ``unknown``).
3. :mod:`journal_utilities.ingest.diff` — channel-vs-manifest-vs-INDEX
   reconciliation report (quota-free; consumes a saved channel manifest).

All public names resolve lazily via ``__getattr__`` (PEP 562) so that
``python -m journal_utilities.ingest.<module>`` does not eagerly import the
package's submodules first (avoids the runpy double-import warning).
"""

from typing import Any

__all__ = [
    "AdapterResult",
    "ChannelVideo",
    "DirectoryVideoDetailRunner",
    "ScaffoldPlan",
    "SubprocessYtDlpRunner",
    "UNKNOWN",
    "apply_full_details",
    "build_reconciliation",
    "build_scaffold",
    "build_worklist",
    "build_worklist_from_manifest",
    "diff_against_index",
    "diff_main",
    "enumerate_channel_videos",
    "enumerate_main",
    "load_index_video_ids",
    "parse_iso8601_duration",
    "plan_scaffolds",
    "scaffold_main",
    "video_from_manifest_entry",
    "ytdlp_main",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AdapterResult": ("journal_utilities.ingest.ytdlp", "AdapterResult"),
    "ChannelVideo": ("journal_utilities.ingest.enumerate", "ChannelVideo"),
    "DirectoryVideoDetailRunner": (
        "journal_utilities.ingest.ytdlp",
        "DirectoryVideoDetailRunner",
    ),
    "ScaffoldPlan": ("journal_utilities.ingest.scaffold", "ScaffoldPlan"),
    "SubprocessYtDlpRunner": ("journal_utilities.ingest.ytdlp", "SubprocessYtDlpRunner"),
    "UNKNOWN": ("journal_utilities.ingest.enumerate", "UNKNOWN"),
    "apply_full_details": ("journal_utilities.ingest.ytdlp", "apply_full_details"),
    "build_reconciliation": ("journal_utilities.ingest.diff", "build_reconciliation"),
    "build_scaffold": ("journal_utilities.ingest.scaffold", "build_scaffold"),
    "build_worklist": ("journal_utilities.ingest.enumerate", "build_worklist"),
    "build_worklist_from_manifest": (
        "journal_utilities.ingest.ytdlp",
        "build_worklist_from_manifest",
    ),
    "diff_against_index": ("journal_utilities.ingest.enumerate", "diff_against_index"),
    "diff_main": ("journal_utilities.ingest.diff", "main"),
    "enumerate_channel_videos": ("journal_utilities.ingest.enumerate", "enumerate_channel_videos"),
    "enumerate_main": ("journal_utilities.ingest.enumerate", "main"),
    "load_index_video_ids": ("journal_utilities.ingest.enumerate", "load_index_video_ids"),
    "parse_iso8601_duration": ("journal_utilities.ingest.enumerate", "parse_iso8601_duration"),
    "plan_scaffolds": ("journal_utilities.ingest.scaffold", "plan_scaffolds"),
    "scaffold_main": ("journal_utilities.ingest.scaffold", "main"),
    "video_from_manifest_entry": ("journal_utilities.ingest.ytdlp", "video_from_manifest_entry"),
    "ytdlp_main": ("journal_utilities.ingest.ytdlp", "main"),
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 — PEP 562 lazy export
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    import importlib

    return getattr(importlib.import_module(module_name), attr)
