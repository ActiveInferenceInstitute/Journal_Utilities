#!/usr/bin/env python3
"""Pinned GNN conformance check for this repository.

Single implementation shared by ``run.py gate gnn`` and the
``gnn conformance (pinned)`` CI job. The pin in ``.github/gnn-pin.json``
(schema ``gnn-importer-pin/v1``) is the only source of the upstream
repository, tag and commit; this script never guesses a revision.

The ``gnn`` distribution is an external dependency and is imported lazily, so
an interpreter with no project environment can still read the pin:

    python scripts/gnn_conformance.py --requirements

prints the install specs (one per line) the caller has to provide, e.g.

    uv run --no-project --with defusedxml --with psutil --with pyyaml \
        --with "generalized-notation-notation @ git+https://github.com/..." \
        python scripts/gnn_conformance.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

PIN_SCHEMA = "gnn-importer-pin/v1"
PIN_REQUIRED_KEYS = ("schema", "repository", "revision", "tag")
# Local checkouts carry virtualenvs and caches that a CI checkout does not.
SKIP_DIRECTORIES = frozenset({".git", ".venv", "node_modules", "__pycache__", "site-packages"})
EXEMPLAR_PATH = "input/gnn_files/basics/static_perception.md"


class ConformanceError(RuntimeError):
    """The pin or the pinned parser does not match what this check requires."""


def load_pin(path: Path) -> dict[str, str]:
    """Read and validate the pin document."""
    try:
        pin = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConformanceError(f"missing pin file: {path}") from exc
    if not isinstance(pin, dict):
        raise ConformanceError(f"{path} must contain a JSON object")
    missing = [key for key in PIN_REQUIRED_KEYS if not isinstance(pin.get(key), str)]
    if missing:
        raise ConformanceError(f"{path} is missing string field(s): {', '.join(missing)}")
    if pin["schema"] != PIN_SCHEMA:
        raise ConformanceError(f"{path} schema is {pin['schema']!r}, expected {PIN_SCHEMA!r}")
    return pin


def install_requirements(pin: dict[str, str]) -> list[str]:
    """Exact install specs the pinned check needs."""
    spec = (
        "generalized-notation-notation @ "
        f"git+https://github.com/{pin['repository']}.git@{pin['revision']}"
    )
    return ["defusedxml", "psutil", "pyyaml", spec]


def sketch_paths(root: Path) -> list[Path]:
    """Every ``*.gnn.md`` sketch below *root*, skipping local-only directories."""
    found = [
        path
        for path in root.rglob("*.gnn.md")
        if not SKIP_DIRECTORIES.intersection(path.relative_to(root).parts)
    ]
    return sorted(found)


def check(pin: dict[str, str], root: Path) -> dict[str, object]:
    """Verify the installed parser against the pin and parse the sketches."""
    from gnn import __version__  # noqa: PLC0415  (external, optional dependency)
    from gnn.parsers.basic import (  # noqa: PLC0415
        parse_gnn_formal,
        validate_gnn_syntax,
    )
    from gnn.type_checker import GNNTypeChecker  # noqa: PLC0415

    def assert_clean(path: Path, label: str) -> None:
        """Reject a sketch or exemplar the pinned parser cannot read.

        ``parse_gnn_formal`` takes a path; ``validate_gnn_syntax`` takes text.
        """
        parsed = parse_gnn_formal(path)
        if parsed is None or getattr(parsed, "parse_errors", None):
            raise ConformanceError(f"{label} did not parse cleanly")
        valid, errors = validate_gnn_syntax(path.read_text(encoding="utf-8"))
        if not valid:
            raise ConformanceError(f"{label} syntax errors: {errors!r}")

    def typecheck(files: list[Path], output_dir: Path) -> None:
        """Copy *files* into a model directory and run the pinned type checker.

        The pinned checker's verdict is three-valued: ``True`` when every file
        validates, ``2`` when the run completed but a file had type or
        consistency problems (or no GNN file was found), and ``False`` on a
        hard failure. Only literal ``True`` is a pass — ``2`` is truthy, so a
        truthiness test would report an invalid model as verified.
        """
        model_dir = output_dir / "models"
        model_dir.mkdir()
        for index, path in enumerate(files):
            shutil.copy2(path, model_dir / f"{index:03d}_{path.name}")
        verdict = GNNTypeChecker().validate_gnn_files(model_dir, output_dir)
        if verdict is not True:
            raise ConformanceError(
                "GNN type checker rejected the checked sketches "
                f"(validate_gnn_files returned {verdict!r}; only True passes)"
            )

    expected_version = pin["tag"].removeprefix("v")
    if __version__ != expected_version:
        raise ConformanceError(
            f"installed GNN {__version__!r} does not match pin tag {pin['tag']!r}"
        )

    sketches = sketch_paths(root)
    with tempfile.TemporaryDirectory(prefix="repo-gnn-") as output:
        output_dir = Path(output)
        if sketches:
            for sketch in sketches:
                assert_clean(sketch, str(sketch))
            typecheck(sketches, output_dir)
            checked, source = len(sketches), "repository"
        else:
            url = (
                f"https://raw.githubusercontent.com/{pin['repository']}/"
                f"{pin['revision']}/{EXEMPLAR_PATH}"
            )
            exemplar = output_dir / Path(EXEMPLAR_PATH).name
            try:
                urllib.request.urlretrieve(url, exemplar)  # noqa: S310  (pinned https URL)
            except OSError as exc:
                raise ConformanceError(
                    f"no *.gnn.md sketch and the pinned exemplar is unreachable: {url}"
                ) from exc
            assert_clean(exemplar, url)
            typecheck([exemplar], output_dir)
            checked, source = 1, "pinned-exemplar"

    return {
        "gnn-version": __version__,
        "pin-revision": pin["revision"],
        "pin-tag": pin["tag"],
        "models": checked,
        "source": source,
        "result": "verified",
    }


def build_parser() -> argparse.ArgumentParser:
    """CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pin",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".github" / "gnn-pin.json",
        help="pin document (default: the repository's .github/gnn-pin.json)",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="tree searched for *.gnn.md sketches",
    )
    parser.add_argument(
        "--requirements",
        action="store_true",
        help="print the install specs required by the pinned check and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the conformance check."""
    args = build_parser().parse_args(argv)
    try:
        pin = load_pin(args.pin)
        if args.requirements:
            print("\n".join(install_requirements(pin)))
            return 0
        summary = check(pin, args.repository_root)
    except ConformanceError as exc:
        print(f"GNN conformance failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
