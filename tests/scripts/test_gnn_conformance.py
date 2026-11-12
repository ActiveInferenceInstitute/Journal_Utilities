"""Outcome tests for the ``gnn`` gate arm's type-checker verdict.

``GNNTypeChecker().validate_gnn_files`` is three-valued: ``True`` when every
file validates, ``2`` when the run completed but one or more files had type or
consistency problems (or no GNN file was found), and ``False`` on a hard
failure. Only literal ``True`` may pass the arm — ``2`` is truthy, so a
truthiness test reports an invalid model as ``"verified"``.

The pinned parser is installed only in the throwaway ``uv`` environment the arm
uses, so these tests substitute a stub ``gnn`` package in ``sys.modules``; no
network and no pinned install are involved.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from scripts.gnn_conformance import ConformanceError, check, main

PIN: dict[str, str] = {
    "schema": "gnn-importer-pin/v1",
    "repository": "ActiveInferenceInstitute/Generalized_Notation_Notation",
    "revision": "8f293d9ba810e6eda5c09842d9c7ed9ffa5f92c1",
    "tag": "v5.0.3",
}

#: Stand-in sketch; the stubbed parser ignores its text.
SKETCH_TEXT = "## GNNSection\n\nActInfPOMDP\n"


class FakeParseResult:
    """The fields ``assert_clean`` reads off ``parse_gnn_formal``."""

    parse_errors: list[str] = []


class RecordingTypeChecker:
    """Stub checker: records the copied model directory, returns a fixed verdict."""

    verdict: object = True
    seen: list[tuple[Path, list[str]]] = []

    def validate_gnn_files(self, target_dir: Path, output_dir: Path, **kwargs: object) -> object:
        """Record the files the arm actually handed to the checker."""
        type(self).seen.append(
            (Path(target_dir), sorted(p.name for p in Path(target_dir).iterdir()))
        )
        return type(self).verdict


def install_fake_gnn(
    monkeypatch: pytest.MonkeyPatch, verdict: object
) -> type[RecordingTypeChecker]:
    """Register a stub ``gnn`` package whose type checker returns *verdict*."""
    checker_class = type(
        "StubTypeChecker", (RecordingTypeChecker,), {"verdict": verdict, "seen": []}
    )

    gnn = types.ModuleType("gnn")
    gnn.__version__ = "5.0.3"  # type: ignore[attr-defined]
    parsers = types.ModuleType("gnn.parsers")
    basic = types.ModuleType("gnn.parsers.basic")
    basic.parse_gnn_formal = lambda path: FakeParseResult()  # type: ignore[attr-defined]
    basic.validate_gnn_syntax = lambda text: (True, [])  # type: ignore[attr-defined]
    type_checker = types.ModuleType("gnn.type_checker")
    type_checker.GNNTypeChecker = checker_class  # type: ignore[attr-defined]
    gnn.parsers = parsers  # type: ignore[attr-defined]
    parsers.basic = basic  # type: ignore[attr-defined]

    modules = {
        "gnn": gnn,
        "gnn.parsers": parsers,
        "gnn.parsers.basic": basic,
        "gnn.type_checker": type_checker,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return checker_class


@pytest.fixture
def sketch_root(tmp_path: Path) -> Path:
    """A repository root holding exactly one ``*.gnn.md`` sketch."""
    (tmp_path / "probe.gnn.md").write_text(SKETCH_TEXT, encoding="utf-8")
    return tmp_path


def test_typecheck_passes_only_on_literal_true(
    monkeypatch: pytest.MonkeyPatch, sketch_root: Path
) -> None:
    """``True`` is the sole accepted verdict and the sketches reach the checker."""
    checker_class = install_fake_gnn(monkeypatch, True)

    summary = check(PIN, sketch_root)

    assert summary["result"] == "verified"
    assert summary["models"] == 1
    assert summary["source"] == "repository"
    ((model_dir, copied),) = checker_class.seen
    assert copied == ["000_probe.gnn.md"]
    assert model_dir.name == "models"


@pytest.mark.parametrize(
    "verdict",
    [
        pytest.param(2, id="2-invalid-files-or-none-found"),
        pytest.param(False, id="False-hard-failure"),
        pytest.param(None, id="None"),
        pytest.param(0, id="0"),
        pytest.param(1, id="1-equals-True-but-is-not-True"),
        pytest.param("True", id="string-True"),
    ],
)
def test_typecheck_refuses_every_non_true_verdict(
    monkeypatch: pytest.MonkeyPatch, sketch_root: Path, verdict: object
) -> None:
    """Any verdict other than literal ``True`` fails, and the verdict is reported."""
    install_fake_gnn(monkeypatch, verdict)

    with pytest.raises(ConformanceError) as excinfo:
        check(PIN, sketch_root)

    message = str(excinfo.value)
    assert repr(verdict) in message, message
    assert "only True passes" in message


def test_gate_arm_exits_nonzero_when_checker_reports_invalid(
    monkeypatch: pytest.MonkeyPatch,
    sketch_root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI the gate runs returns 1 and names the verdict on stderr."""
    install_fake_gnn(monkeypatch, 2)
    pin_path = tmp_path / "gnn-pin.json"
    pin_path.write_text(json.dumps(PIN), encoding="utf-8")

    exit_code = main(["--pin", str(pin_path), "--repository-root", str(sketch_root)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GNN conformance failed" in captured.err
    assert "returned 2" in captured.err
