# Source package
"""Journal Utilities — Active Inference YouTube processing pipeline."""

from typing import Any

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Lazy submodule imports — avoids pulling heavy deps (pyytdata, yt-dlp, …)
# when only one submodule is needed (e.g. export).
# ---------------------------------------------------------------------------

_SUBMODULE_MAP: dict[str, tuple[str, str]] = {
    "channel": (".youtube", "channel"),
    "playlist": (".youtube", "playlist"),
    "youtube": (".youtube", "youtube"),
    "downloader": (".download", "downloader"),
    "transcriber": (".transcribe", "transcriber"),
    "renderer": (".render", "renderer"),
    "database": (".data", "database"),
    "importer": (".data", "importer"),
    "exporter": (".export", "exporter"),
}

__all__ = [
    "channel",
    "playlist",
    "youtube",
    "downloader",
    "transcriber",
    "renderer",
    "database",
    "importer",
    "exporter",
]


def __getattr__(name: str) -> Any:  # noqa: ANN401 - dynamic module resolution is inherently Any
    if name in _SUBMODULE_MAP:
        pkg, mod = _SUBMODULE_MAP[name]
        import importlib

        parent = importlib.import_module(pkg, __name__)
        return getattr(parent, mod)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
