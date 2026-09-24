"""Weekly ingest: Data API enumeration, journal diffing, metadata scaffolds.

Three composable steps, all read-only by default (dry-run is the default for
every CLI; files are only written behind ``--no-dry-run``):

1. :mod:`journal_utilities.ingest.enumerate` — weekly channel enumeration via
   the YouTube Data API (playlistItems.list + videos.list), diffed against the
   journal's ``INDEX.json`` to emit a new-video worklist.
2. :mod:`journal_utilities.ingest.scaffold` — per-item ``metadata.json``
   scaffolds for worklist entries (``transcript_kind: "youtube"``,
   ``status: scheduled`` for premieres).
3. :mod:`journal_utilities.ingest.diff` — channel-vs-manifest-vs-INDEX
   reconciliation report (quota-free; consumes a saved channel manifest).

All public names resolve lazily via ``__getattr__`` (PEP 562) so that
``python -m journal_utilities.ingest.<module>`` does not eagerly import the
package's submodules first (avoids the runpy double-import warning).
"""

from typing import Any

__all__ = [
    "ChannelVideo",
    "ScaffoldPlan",
    "build_reconciliation",
    "build_scaffold",
    "build_worklist",
    "diff_against_index",
    "diff_main",
    "enumerate_channel_videos",
    "enumerate_main",
    "load_index_video_ids",
    "parse_iso8601_duration",
    "plan_scaffolds",
    "scaffold_main",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ChannelVideo": ("journal_utilities.ingest.enumerate", "ChannelVideo"),
    "ScaffoldPlan": ("journal_utilities.ingest.scaffold", "ScaffoldPlan"),
    "build_reconciliation": ("journal_utilities.ingest.diff", "build_reconciliation"),
    "build_scaffold": ("journal_utilities.ingest.scaffold", "build_scaffold"),
    "build_worklist": ("journal_utilities.ingest.enumerate", "build_worklist"),
    "diff_against_index": ("journal_utilities.ingest.enumerate", "diff_against_index"),
    "diff_main": ("journal_utilities.ingest.diff", "main"),
    "enumerate_channel_videos": ("journal_utilities.ingest.enumerate", "enumerate_channel_videos"),
    "enumerate_main": ("journal_utilities.ingest.enumerate", "main"),
    "load_index_video_ids": ("journal_utilities.ingest.enumerate", "load_index_video_ids"),
    "parse_iso8601_duration": ("journal_utilities.ingest.enumerate", "parse_iso8601_duration"),
    "plan_scaffolds": ("journal_utilities.ingest.scaffold", "plan_scaffolds"),
    "scaffold_main": ("journal_utilities.ingest.scaffold", "main"),
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 — PEP 562 lazy export
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    import importlib

    return getattr(importlib.import_module(module_name), attr)
