#!/usr/bin/env python3
"""Check tracked Markdown: relative links resolve and docs/ stays indexed.

Two rules, both derived from files in the tree:

1. Every relative link/image target in a tracked ``*.md`` file exists. Absolute
   URLs, ``mailto:`` targets and same-page anchors are out of scope. Fenced code
   blocks and inline code spans are ignored, so command examples cannot create
   false failures.
2. Every tracked ``docs/*.md`` file is linked from ``docs/documentation-index.md``,
   and every top-level ``docs/*.md`` guide is linked from ``docs/README.md``.

Exits 1 and prints ``path:line: message`` for each violation.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

SKIP_DIRECTORIES = frozenset({".git", ".venv", "node_modules", "__pycache__", "site-packages"})
# Vendored third-party agent skills; their examples link outside this repository.
SKIP_PREFIXES = (Path(".claude") / "skills",)
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")


def tracked_markdown(root: Path) -> list[Path]:
    """Every tracked Markdown file, or every on-disk one when git is unavailable."""
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path
            for path in root.rglob("*.md")
            if not SKIP_DIRECTORIES.intersection(path.relative_to(root).parts)
        )
    names = [name for name in listed.decode("utf-8", "surrogateescape").split("\0") if name]
    return sorted(root / name for name in names)


def _skipped(relative: Path) -> bool:
    return any(relative == prefix or prefix in relative.parents for prefix in SKIP_PREFIXES)


def scannable_lines(text: str) -> list[tuple[int, str]]:
    """Lines with fenced blocks and inline code blanked out, keeping line numbers."""
    lines: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            lines.append((number, ""))
            continue
        lines.append((number, "" if in_fence else INLINE_CODE.sub("", line)))
    return lines


def broken_links(path: Path, root: Path) -> list[tuple[int, str]]:
    """Relative targets of *path* that do not exist."""
    failures: list[tuple[int, str]] = []
    for number, line in scannable_lines(path.read_text(encoding="utf-8", errors="replace")):
        for target in LINK.findall(line):
            if not target or target.startswith("#") or target.startswith("//"):
                continue
            if SCHEME.match(target):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not relative:
                continue
            if not (path.parent / relative).exists():
                failures.append((number, f"broken relative link -> {target}"))
    return failures


def index_failures(root: Path, documents: list[Path]) -> list[tuple[Path, int, str]]:
    """docs/ files missing from their index page."""
    docs_root = root / "docs"
    hub = docs_root / "README.md"
    index = docs_root / "documentation-index.md"
    failures: list[tuple[Path, int, str]] = []
    if not hub.is_file() or not index.is_file():
        return [(docs_root, 0, "docs/README.md and docs/documentation-index.md must both exist")]
    hub_text, index_text = hub.read_text(encoding="utf-8"), index.read_text(encoding="utf-8")
    for document in documents:
        if docs_root not in document.parents or document in (hub, index):
            continue
        relative = document.relative_to(docs_root).as_posix()
        name = document.name
        if not any(f"]({target})" in index_text for target in (relative, name)):
            failures.append((index, 0, f"does not list docs/{relative}"))
        if document.parent == docs_root and f"]({name})" not in hub_text:
            failures.append((hub, 0, f"does not link the docs/{name} guide"))
    return failures


def build_parser() -> argparse.ArgumentParser:
    """CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="tree whose tracked Markdown is checked",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run both checks."""
    root = build_parser().parse_args(argv).repository_root.resolve()
    documents = tracked_markdown(root)
    problems = 0
    for document in documents:
        if _skipped(document.relative_to(root)):
            continue
        for number, message in broken_links(document, root):
            print(f"{document.relative_to(root)}:{number}: {message}")
            problems += 1
    for path, number, message in index_failures(root, documents):
        label = path.relative_to(root) if path.is_relative_to(root) else path
        print(f"{label}:{number}: {message}")
        problems += 1
    if problems:
        print(f"{problems} documentation problem(s) in {len(documents)} tracked Markdown file(s)")
        return 1
    print(f"OK: {len(documents)} tracked Markdown file(s), links and docs index consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
