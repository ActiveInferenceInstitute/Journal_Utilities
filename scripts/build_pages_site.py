#!/usr/bin/env python3
"""CLI: compile ActiveInferenceJournal into the static GitHub Pages bundle.

Extends the SPA bundle build with M4 static per-item pages, ``sitemap.xml``,
and ``robots.txt`` (spec: ActiveInferenceJournal ``docs/m4-site-spec.md``).

Usage:
    python scripts/build_pages_site.py --journal ../ActiveInferenceJournal --output dist

Modes:
    default     Build (dry-run preview of what would be written, no files).
    --apply     Write the bundle to --output.
    --check     Build to a temp dir and report drift: nonzero exit when the
                emitted files differ from an existing --output (CI freshness
                gate); also nonzero when --output has no prior build.
"""

from __future__ import annotations

import argparse
import filecmp
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from journal_utilities.site.builder import build_site  # noqa: E402


def _tree_files(root: Path) -> dict[str, Path]:
    return {
        str(p.relative_to(root)): p
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".nojekyll" != p.name
    }


def _drift(built: Path, existing: Path) -> list[str]:
    """Files that differ between a fresh build and the deployed output."""
    drift: list[str] = []
    new_files = _tree_files(built)
    old_files = _tree_files(existing)
    for rel in sorted(set(new_files) | set(old_files)):
        if rel not in old_files:
            drift.append(f"missing from output: {rel}")
        elif rel not in new_files:
            drift.append(f"stale in output: {rel}")
        elif not filecmp.cmp(new_files[rel], old_files[rel], shallow=False):
            drift.append(f"differs: {rel}")
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build static journal site (SPA + M4 per-item pages, sitemap, robots)."
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=REPO.parent / "ActiveInferenceJournal",
        help="Path to ActiveInferenceJournal repo root (default: ../ActiveInferenceJournal)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "dist",
        help="Output directory for the static site (default: dist)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the bundle (default is a dry-run report only)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Drift check: build to temp, compare with --output, exit 1 on drift",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean output directory before building",
    )
    args = parser.parse_args()

    if args.check and args.apply:
        parser.error("--check and --apply are mutually exclusive")

    if not args.journal.exists():
        print(f"Error: Journal directory not found at {args.journal}", file=sys.stderr)
        return 1

    if args.check:
        with tempfile.TemporaryDirectory(prefix="pages-drift-") as tmp:
            fresh = Path(tmp) / "build"
            result = build_site(journal_dir=args.journal, output_dir=fresh, static_pages=True)
            if not args.output.exists():
                print(f"DRIFT: no existing output at {args.output}")
                return 1
            drift = _drift(fresh, args.output)
        if drift:
            print(f"DRIFT: {len(drift)} file(s) differ from {args.output}:")
            for line in drift[:50]:
                print(f"  {line}")
            if len(drift) > 50:
                print(f"  … and {len(drift) - 50} more")
            return 1
        print(f"OK: {result['items_processed']} items, no drift vs {args.output}")
        return 0

    if not args.apply:
        print(
            "Dry run (no files written). Use --apply to write the bundle "
            f"to {args.output}, or --check to compare with an existing build."
        )
        result = build_site(
            journal_dir=args.journal,
            output_dir=Path(tempfile.mkdtemp(prefix="pages-preview-")),
            static_pages=True,
        )
        print(
            f"Would write: {result['items_processed']} items, "
            f"{result['pages_written']} item pages + sitemap.xml + robots.txt"
        )
        return 0

    print(f"Building static website from {args.journal} -> {args.output}...")
    result = build_site(
        journal_dir=args.journal,
        output_dir=args.output,
        clean=not args.no_clean,
        static_pages=True,
    )
    print(
        f"✓ Static site build complete: {result['items_processed']} items, "
        f"{result['pages_written']} item pages in {result['output_dir']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
