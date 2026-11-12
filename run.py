#!/usr/bin/env python3
"""
Journal-Utilities — Top-level pipeline runner.

Reads ``config.ini`` for all pipeline settings and exposes subcommands:

    uv run python run.py config        Show current configuration
    uv run python run.py export        Export transcripts (formats from config.ini)
    uv run python run.py download      Download from YouTube (options from config.ini)
    uv run python run.py serve         Start the web interface
    uv run python run.py test          Run the test suite
    uv run python run.py full          Run the full pipeline
    uv run python run.py journal-check Validate a sibling ActiveInferenceJournal checkout
    uv run python run.py gate [ARM…]   Run gate arms (the commands CI runs)

The gate arms live in one table (`gate_commands`); CI calls this entry point
instead of restating the commands. See `docs/RUN_GUIDE.md`.
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.ini"

# ---------------------------------------------------------------------------
# Auto-bootstrap: re-exec via ``uv run`` when not inside the project venv.
# This lets bare ``python run.py`` work without manual ``uv run``.
# ---------------------------------------------------------------------------

_VENV_DIR = PROJECT_ROOT / ".venv"


def _in_project_venv() -> bool:
    """Return True when the running interpreter lives inside .venv/."""
    try:
        return Path(sys.executable).resolve().is_relative_to(_VENV_DIR)
    except (TypeError, ValueError):
        return False


def _bootstrap_via_uv() -> None:
    """Re-exec this script under ``uv run`` so all deps are available."""
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        return  # uv not installed — fall through and hope for the best

    cmd = [uv, "run", "python", str(Path(__file__).resolve()), *sys.argv[1:]]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger_boot = logging.getLogger("journal_utilities.run")
    logger_boot.info("Re-executing under uv for dependency resolution …")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    sys.exit(result.returncode)


def _gate_requested() -> bool:
    """True when this invocation selects the ``gate`` subcommand.

    The gate resolves its own interpreters and environments (and reports a
    missing dev toolchain explicitly), so it must not pay for a pipeline-env
    bootstrap first. ``uv run --no-project python run.py gate gnn`` depends on
    this: that job installs only the pinned parser.
    """
    argv = sys.argv[1:]
    for index, token in enumerate(argv):
        if token != "gate":
            continue
        previous = argv[index - 1] if index else ""
        return previous not in {"--config", "--log-level"}
    return False


# Only auto-bootstrap when run as a script, not when imported by tests
if (
    __name__ == "__main__"
    and not _in_project_venv()
    and "_UV_BOOTSTRAPPED" not in os.environ
    and not _gate_requested()
):
    os.environ["_UV_BOOTSTRAPPED"] = "1"
    _bootstrap_via_uv()

# Ensure the source package is importable when run directly
_src = str(PROJECT_ROOT / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

logger = logging.getLogger("journal_utilities.run")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def load_config(path: Path = CONFIG_PATH) -> configparser.ConfigParser:
    """Load and return the INI config, falling back to defaults."""
    config = configparser.ConfigParser()
    if path.exists():
        config.read(path, encoding="utf-8")
        logger.info("Loaded config from %s", path)
    else:
        logger.warning("Config file not found: %s — using defaults", path)
    return config


def get_bool(
    config: configparser.ConfigParser, section: str, key: str, fallback: bool = False
) -> bool:
    """Read a boolean value from config with a fallback."""
    try:
        return config.getboolean(section, key, fallback=fallback)
    except (ValueError, configparser.Error):
        return fallback


def get_str(config: configparser.ConfigParser, section: str, key: str, fallback: str = "") -> str:
    """Read a string value from config with a fallback."""
    try:
        return config.get(section, key, fallback=fallback)
    except configparser.Error:
        return fallback


def get_int(config: configparser.ConfigParser, section: str, key: str, fallback: int = 0) -> int:
    """Read an integer value from config with a fallback."""
    try:
        return config.getint(section, key, fallback=fallback)
    except (ValueError, configparser.Error):
        return fallback


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_config(config: configparser.ConfigParser, _args: argparse.Namespace) -> int:
    """Display the current configuration."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║           Journal-Utilities — Current Configuration        ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    if not CONFIG_PATH.exists():
        print("⚠  No config.ini found — using defaults\n")
        return 0

    for section in config.sections():
        print(f"  [{section}]")
        for key, value in config.items(section):
            if not value:
                print(f"    {key} = (empty)")
            elif value.lower() in ("true", "yes", "1"):
                print(f"    {key} = {value}  ✓")
            elif value.lower() in ("false", "no", "0"):
                print(f"    {key} = {value}  ✗")
            else:
                print(f"    {key} = {value}")
        print()

    return 0


def cmd_export(config: configparser.ConfigParser, _args: argparse.Namespace) -> int:
    """Export transcripts using formats from config.ini."""
    from journal_utilities.export import ExportFormat, export_transcripts

    data_dir = get_str(config, "general", "data_dir", "data/output")
    export_dir = get_str(config, "export", "output_dir", "data/export")

    transcript_dir = PROJECT_ROOT / data_dir / "transcripts"
    output_dir = PROJECT_ROOT / export_dir

    # Build format list from config
    fmt_map = {
        "plaintext": ExportFormat.PLAINTEXT,
        "pdf": ExportFormat.PDF,
        "markdown": ExportFormat.MARKDOWN,
        "json": ExportFormat.JSON,
        "html": ExportFormat.HTML,
    }

    formats: list[ExportFormat] = []
    for name, enum_val in fmt_map.items():
        if get_bool(config, "export", name, fallback=(name == "plaintext")):
            formats.append(enum_val)

    if not formats:
        logger.warning("No export formats enabled in config.ini [export] section")
        print("⚠  No export formats enabled in config.ini [export] section")
        return 1

    print(f"Formats:  {', '.join(f.value for f in formats)}")
    print(f"Source:   {transcript_dir}")
    print(f"Output:   {output_dir}")
    print()

    data_dir = PROJECT_ROOT / data_dir  # absolute path for metadata lookup
    results = export_transcripts(
        transcript_dir=transcript_dir,
        output_dir=output_dir,
        formats=formats,
        data_dir=data_dir,
    )

    if not results:
        print("⚠  No transcripts found to export")
        return 1

    for fmt_name, fmt_results in results.items():
        ok = sum(1 for r in fmt_results if r.status == "success")
        skip = sum(1 for r in fmt_results if r.status == "skipped")
        fail = sum(1 for r in fmt_results if r.status == "failed")
        print(f"  {fmt_name}: {ok} exported, {skip} skipped, {fail} failed")

    print("\n✓ Export complete")
    return 0


def cmd_download(config: configparser.ConfigParser, _args: argparse.Namespace) -> int:
    """Download from YouTube using options from config.ini."""
    from scripts.download_channel import main as download_main

    # Build argv for the script
    argv = []

    if get_bool(config, "download", "transcripts", fallback=True):
        argv.append("--transcripts")
    if get_bool(config, "download", "audio", fallback=True):
        argv.append("--audio")
    if get_bool(config, "download", "video", fallback=False):
        argv.append("--video")
    if get_bool(config, "download", "resume", fallback=True):
        argv.append("--resume")

    cookies = get_str(config, "download", "cookies_from_browser")
    if cookies:
        argv.extend(["--cookies-from-browser", cookies])

    max_videos = get_int(config, "download", "max_videos", fallback=0)
    if max_videos > 0:
        argv.extend(["--max-videos", str(max_videos)])

    delay = get_int(config, "download", "delay", fallback=1)
    if delay != 1:
        argv.extend(["--delay", str(delay)])

    # Pass the built arguments to the script's main function
    print(f"Running download_channel with args: {argv}")
    try:
        return download_main(argv)
    except SystemExit as exc:
        return exc.code
    except Exception:
        logger.exception("Download script failed")
        return 1


def _port_in_use(port: int) -> bool:
    """Return True when *port* is already bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind(("", port))
            return False
        except OSError:
            return True


def _free_port(port: int) -> bool:
    """Try to kill whatever is occupying *port*.  Return True on success."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return True

        my_pid = str(os.getpid())
        for pid in pids:
            if pid == my_pid:
                continue
            logger.info("Killing stale process %s on port %d", pid, port)
            os.kill(int(pid), signal.SIGTERM)

        # Brief wait for cleanup
        import time as _t

        _t.sleep(0.5)
        return not _port_in_use(port)
    except Exception as exc:
        logger.warning("Could not free port %d: %s", port, exc)
        return False


def cmd_serve(config: configparser.ConfigParser, _args: argparse.Namespace) -> int:
    """Start the web interface."""
    import uvicorn

    from journal_utilities.interface.app import create_app

    host = get_str(config, "interface", "host", "0.0.0.0")
    port_str = get_str(config, "interface", "port", "8000")
    port = int(port_str)

    # ── Auto-resolve port conflicts ────────────────────────────────
    if _port_in_use(port):
        logger.warning("Port %d already in use — attempting to free it", port)
        if _free_port(port):
            logger.info("Port %d freed successfully", port)
        else:
            logger.error("Cannot free port %d — aborting serve", port)
            print(f"  ✗ Port {port} is occupied and could not be freed.")
            print(f"    Try: lsof -ti :{port} | xargs kill -9")
            return 1

    print(f"Starting web interface at http://{host}:{port}")

    # Configure uvicorn logging to match ours if needed,
    # but uvicorn has its own config. We'll let it handle itself.
    try:
        app = create_app()
        # log_config=None tells uvicorn to use the existing logging configuration
        # which allows our root logger (with FileHandler) to capture the logs.
        uvicorn.run(app, host=host, port=port, log_config=None)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.exception("Web interface failed")
        return 1


def cmd_test(_config: configparser.ConfigParser, _args: argparse.Namespace) -> int:
    """Run the test suite."""
    print("Running tests...\n")
    # Tests still run best in a separate process to avoid pollution
    cmd = ["uv", "run", "pytest", "tests/", "-v"]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def cmd_full(config: configparser.ConfigParser, _args: argparse.Namespace) -> int:
    """Run the full pipeline (download → export)."""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║           Running Full Pipeline                            ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    print("Step 1/2: Download")
    rc = cmd_download(config, _args)
    if rc != 0:
        print(f"\n✗ Download failed (exit code {rc})")
        return rc

    print("\nStep 2/2: Export")
    rc = cmd_export(config, _args)
    if rc != 0:
        print(f"\n✗ Export failed (exit code {rc})")
        return rc

    print("\n✓ Full pipeline complete")
    return 0


def cmd_journal_check(_config: configparser.ConfigParser, args: argparse.Namespace) -> int:
    """Run the read-only integrity gate for ActiveInferenceJournal."""
    from scripts.repair_split_transcripts import repair_journal
    from scripts.validate_journal import print_report, validate_journal

    utilities = args.utilities.resolve()
    journal = args.journal.resolve()
    manifest = (args.manifest or utilities / "data/output/channel_videos.json").resolve()

    print(f"Journal: {journal}")
    print(f"Utilities: {utilities}")
    print(f"Manifest: {manifest}\n")
    report = validate_journal(journal, manifest, args.strict_manifest)
    print_report(report)
    if not report.ok:
        return 1

    try:
        stale_transcripts = repair_journal(journal, utilities, check=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: split transcript check failed: {exc}", file=sys.stderr)
        return 1
    if stale_transcripts:
        print("split transcript validation: FAIL", file=sys.stderr)
        return 1
    print("split transcript validation: PASS")
    return 0


def cmd_default(config: configparser.ConfigParser, args: argparse.Namespace) -> int:
    """Default pipeline: config → validate → export → test → serve.

    Runs when ``python run.py`` is invoked with **no** subcommand.
    Reads all settings from ``config.ini`` and performs every step
    with full terminal logging, real validation, and a clickable URL.

    Pipeline steps are individually configurable via ``[pipeline]``
    in ``config.ini``. Test failures block the web interface by default;
    set ``test_strict=false`` only for an intentional diagnostic run.
    """
    import time as _time

    t0 = _time.time()

    # ── Pipeline step flags (all default to True) ─────────────────
    run_config = get_bool(config, "pipeline", "config", fallback=True)
    run_validate = get_bool(config, "pipeline", "validate", fallback=True)
    run_export = get_bool(config, "pipeline", "export", fallback=True)
    run_tests = get_bool(config, "pipeline", "test", fallback=True)
    run_serve = get_bool(config, "pipeline", "serve", fallback=True)
    test_strict = get_bool(config, "pipeline", "test_strict", fallback=True)

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║       Journal-Utilities — Default Pipeline                  ║")
    print("║       Running steps from config.ini [pipeline]              ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    data_dir = get_str(config, "general", "data_dir", "data/output")
    host = get_str(config, "interface", "host", "0.0.0.0")
    port = get_str(config, "interface", "port", "8000")

    step = 0
    enabled_steps = sum([run_config, run_validate, run_export, run_tests, run_serve])

    # ------------------------------------------------------------------
    # Step — Show configuration
    # ------------------------------------------------------------------
    if run_config:
        step += 1
        print("━" * 62)
        print(f"  Step {step}/{enabled_steps} ▸ Configuration")
        print("━" * 62)
        cmd_config(config, args)

    # ------------------------------------------------------------------
    # Step — Validate data directories & content
    # ------------------------------------------------------------------
    if run_validate:
        step += 1
        print("━" * 62)
        print(f"  Step {step}/{enabled_steps} ▸ Data Validation")
        print("━" * 62)

        data_root = PROJECT_ROOT / data_dir
        transcript_dir = data_root / "transcripts"
        audio_dir = data_root / "audio"

        issues: list[str] = []

        # Data root
        if data_root.is_dir():
            logger.info("✓ Data directory exists: %s", data_root)
            print(f"  ✓ Data directory: {data_root}")
        else:
            msg = f"Data directory missing: {data_root}"
            logger.warning("✗ %s", msg)
            issues.append(msg)
            print(f"  ✗ {msg}")

        # Transcripts
        if transcript_dir.is_dir():
            txt_files = list(transcript_dir.glob("*.txt"))
            logger.info("✓ Transcript directory: %d .txt files", len(txt_files))
            print(f"  ✓ Transcripts: {len(txt_files)} .txt files in {transcript_dir}")
            if not txt_files:
                issues.append("Transcript directory exists but contains no .txt files")
        else:
            msg = f"Transcript directory missing: {transcript_dir}"
            logger.warning("✗ %s", msg)
            issues.append(msg)
            print(f"  ✗ {msg}")

        # Audio
        if audio_dir.is_dir():
            audio_files = list(audio_dir.iterdir())
            audio_count = sum(1 for f in audio_files if f.is_file())
            logger.info("✓ Audio directory: %d files", audio_count)
            print(f"  ✓ Audio: {audio_count} files in {audio_dir}")
        else:
            logger.info("ℹ  Audio directory not found (optional): %s", audio_dir)
            print(f"  ℹ  Audio directory not found (optional): {audio_dir}")

        # Export output dir
        export_dir = PROJECT_ROOT / get_str(config, "export", "output_dir", "data/export")
        if export_dir.is_dir():
            logger.info("✓ Export output directory exists: %s", export_dir)
            print(f"  ✓ Export output directory: {export_dir}")
        else:
            logger.info("ℹ  Export output directory will be created: %s", export_dir)
            print(f"  ℹ  Export output directory will be created: {export_dir}")

        if issues:
            print(f"\n  ⚠  Validation found {len(issues)} issue(s):")
            for issue in issues:
                print(f"     • {issue}")
            print()
        else:
            print("\n  ✓ All validations passed\n")

    # ------------------------------------------------------------------
    # Step — Export transcripts
    # ------------------------------------------------------------------
    if run_export:
        step += 1
        print("━" * 62)
        print(f"  Step {step}/{enabled_steps} ▸ Export")
        print("━" * 62)
        rc = cmd_export(config, args)
        if rc != 0:
            logger.warning("Export step returned non-zero: %d", rc)
            print(f"  ⚠  Export finished with warnings (exit code {rc})\n")
        else:
            print()

    # ------------------------------------------------------------------
    # Step — Run tests (non-blocking unless test_strict = true)
    # ------------------------------------------------------------------
    if run_tests:
        step += 1
        print("━" * 62)
        print(f"  Step {step}/{enabled_steps} ▸ Tests")
        print("━" * 62)
        rc = cmd_test(config, args)
        if rc != 0:
            logger.warning("Test suite returned non-zero: %d", rc)
            print(f"  ⚠  Tests finished with failures (exit code {rc})")
            if test_strict:
                print("  ✗  test_strict=true — aborting pipeline\n")
                return rc
            print("  ℹ  Continuing to serve (test_strict=false)\n")
        else:
            print("  ✓ All tests passed\n")

    elapsed = _time.time() - t0

    # ------------------------------------------------------------------
    # Step — Serve web interface
    # ------------------------------------------------------------------
    if run_serve:
        step += 1
        print("━" * 62)
        print(f"  Step {step}/{enabled_steps} ▸ Web Interface")
        print("━" * 62)
        display_host = "localhost" if host in ("0.0.0.0", "") else host
        url = f"http://{display_host}:{port}"

        print(f"\n  Pipeline steps 1–{step - 1} completed in {elapsed:.1f}s")
        print("  Starting web interface...\n")
        print("╔══════════════════════════════════════════════════════════════╗")
        print(f"║  ➜  Open in browser: {url:<39}║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print()
        logger.info("Starting web interface at %s", url)

        return cmd_serve(config, args)

    print(f"\n  Pipeline completed in {elapsed:.1f}s")
    return 0


# ---------------------------------------------------------------------------
# Gate arms — one entry point, the same commands CI runs
# ---------------------------------------------------------------------------

#: Arms `gate all` runs, in order: offline-safe and pre-push sized.
GATE_ARMS = ("lint", "format", "types", "test", "docs", "gnn")
#: Arms `gate report` measures: everything above plus the network/coverage arm.
GATE_REPORT_ARMS = ("lint", "format", "types", "test", "test-full", "docs", "gnn")
GATE_REPORT_PATH = PROJECT_ROOT / "docs" / "_generated" / "gate-arms.md"
GATE_GNN_SCRIPT = PROJECT_ROOT / "scripts" / "gnn_conformance.py"
GATE_DOCS_SCRIPT = PROJECT_ROOT / "scripts" / "check_docs_links.py"


def _gate_python() -> str:
    """Interpreter that owns the dev toolchain (the project venv when present)."""
    venv_python = _VENV_DIR / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _gnn_requirements() -> list[str]:
    """Install specs for the pinned parser, read from the pin by the check itself."""
    completed = subprocess.run(
        [_gate_python(), str(GATE_GNN_SCRIPT), "--requirements"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _gnn_command() -> list[str]:
    """The `gnn` arm: pinned parser in a throwaway uv environment, no project sync."""
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for the gnn arm: https://docs.astral.sh/uv/")
    command = [uv, "run", "--no-project"]
    for requirement in _gnn_requirements():
        command += ["--with", requirement]
    command += ["python", str(GATE_GNN_SCRIPT)]
    return command


def gate_commands() -> dict[str, list[str]]:
    """Arm name -> exact argv. These are the only copies of the gate commands."""
    python = _gate_python()
    return {
        "lint": [python, "-m", "ruff", "check", "src/", "tests/", "scripts/"],
        "format": [python, "-m", "ruff", "format", "--check", "src/", "tests/", "scripts/"],
        "types": [python, "-m", "mypy", "src"],
        "test": [python, "-m", "pytest", "tests/", "-q"],
        "test-full": [
            python,
            "-m",
            "pytest",
            "tests/",
            "-q",
            "--cov=src",
            "--cov-report=term-missing",
        ],
        "docs": [python, str(GATE_DOCS_SCRIPT)],
        "gnn": _gnn_command(),
    }


def gate_env(arm: str) -> dict[str, str]:
    """Environment for one arm.

    `test` mirrors a hosted runner: the live-network download tests skip
    themselves when `CI` is set (see `tests/journal_utilities/test_downloader.py`),
    so the default arm is the same selection CI exercises. `test-full` leaves
    `CI` alone and runs every test this host can reach.
    """
    env = dict(os.environ)
    if arm == "test":
        env["CI"] = "true"
    return env


def _toolchain_problem(python: str) -> str:
    """Explain how to provision the dev toolchain, or ``""`` when it is present."""
    probe = subprocess.run(
        [python, "-c", "import pytest, ruff, mypy"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode == 0:
        return ""
    return (
        f"{python} is missing the dev toolchain (pytest, ruff, mypy).\n"
        "Provision it with: uv sync --frozen --extra rag --extra interface "
        "--extra export --dev"
    )


def _gate_summary(output: str) -> str:
    """One line that says what the arm concluded."""
    import re

    interesting = re.compile(r"passed|failed|error|Success|All checks|already formatted|^OK:")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if interesting.search(line):
            return line[:160]
    return lines[-1][:160] if lines else ""


def _run_gate_arm(arm: str, command: list[str]) -> tuple[int, float, str]:
    """Run one arm from the repository root; return (exit code, seconds, output)."""
    import time as _time

    started = _time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=gate_env(arm),
        capture_output=True,
        text=True,
    )
    return completed.returncode, _time.perf_counter() - started, completed.stdout + completed.stderr


def _git_revision() -> str:
    """Short HEAD, or `unknown` when git is unavailable."""
    completed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or "unknown"


def _display_command(command: list[str]) -> str:
    """Shell-quoted arm command with repository paths made relative."""
    import shlex

    root = str(PROJECT_ROOT)
    relative = [part.replace(root + os.sep, "./").replace(root, ".") for part in command]
    return shlex.join(relative)


def _write_gate_report(commands: dict[str, list[str]]) -> int:
    """Measure every arm once and regenerate docs/_generated/gate-arms.md."""
    import platform
    from datetime import UTC, datetime

    # The `docs` arm validates links, including the links to this file: give the
    # path a truthful "in progress" body before measuring so a fresh report cannot
    # fail on its own output.
    GATE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    GATE_REPORT_PATH.write_text(
        "# Gate arms — measured wall time\n\n"
        "> Measurement in progress; re-run `uv run python run.py gate report`.\n",
        encoding="utf-8",
    )

    rows = [(arm, *_run_gate_arm(arm, commands[arm])) for arm in GATE_REPORT_ARMS]
    uv_version = subprocess.run(
        ["uv", "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    lines = [
        "# Gate arms — measured wall time",
        "",
        "<!-- generated by `uv run python run.py gate report`; never hand-edit a number here -->",
        "",
        "One run per arm on the host that produced this file. The `test` arm is the CI",
        "selection (live-network download tests skip when `CI` is set); `test-full` runs",
        "everything this host can reach, including those network downloads, so its number",
        "varies with the network. The `gnn` arm installs the pinned parser into a throwaway",
        "`uv` environment on first use. Runs are warm-cache: the mypy and uv caches",
        "from earlier runs are reused.",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Host | `{platform.platform()}` |",
        f"| Python | `{sys.version.split()[0]}` |",
        f"| uv | `{uv_version or 'not installed'}` |",
        f"| Commit | `{_git_revision()}` |",
        f"| Measured | {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} |",
        "",
        "| Arm | Command | Result | Wall time (s) |",
        "| --- | --- | --- | --- |",
    ]
    for arm, code, seconds, _output in rows:
        command = _display_command(commands[arm])
        result = "pass" if code == 0 else f"**fail (exit {code})**"
        lines.append(f"| `{arm}` | `{command}` | {result} | {seconds:.2f} |")
    lines += [
        "",
        "Test counts and coverage come from the arm output; `test-full` reports coverage",
        "over `src/` because the arm passes `--cov=src --cov-report=term-missing`.",
        "",
    ]
    GATE_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {GATE_REPORT_PATH.relative_to(PROJECT_ROOT)}")
    return 0 if all(code == 0 for _arm, code, _seconds, _output in rows) else 1


def cmd_gate(_config: configparser.ConfigParser, args: argparse.Namespace) -> int:
    """Run gate arms by name (see `docs/RUN_GUIDE.md`)."""
    import shlex
    selected: list[str] = args.arms or ["all"]
    commands = gate_commands()

    if "report" in selected:
        return _write_gate_report(commands)

    arms = list(GATE_ARMS) if "all" in selected else selected
    unknown = [arm for arm in arms if arm not in commands]
    if unknown:
        print(
            f"Unknown gate arm(s): {', '.join(unknown)}\n"
            f"Choose from: {', '.join(GATE_ARMS)}, all, report",
            file=sys.stderr,
        )
        return 2

    if {"lint", "format", "types", "test", "test-full"}.intersection(arms):
        problem = _toolchain_problem(_gate_python())
        if problem:
            print(problem, file=sys.stderr)
            return 2

    failures: list[str] = []
    for arm in arms:
        print(f"\n▸ gate {arm}: {shlex.join(commands[arm])}", flush=True)
        code, seconds, output = _run_gate_arm(arm, commands[arm])
        print(f"  {'ok  ' if code == 0 else 'FAIL'} {seconds:6.2f}s  {_gate_summary(output)}")
        if code != 0:
            failures.append(arm)
            print(output)

    if failures:
        print(f"\nFailed arm(s): {', '.join(failures)}")
        return 1
    print(f"\nAll {len(arms)} gate arm(s) passed")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Journal-Utilities — Pipeline runner (reads config.ini)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to config.ini (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override log level from config.ini",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("config", help="Show current configuration")
    subparsers.add_parser("export", help="Export transcripts (formats from config.ini)")
    subparsers.add_parser("download", help="Download from YouTube (options from config.ini)")
    subparsers.add_parser("serve", help="Start the web interface")
    subparsers.add_parser("test", help="Run the test suite")
    subparsers.add_parser("full", help="Run the full pipeline (download → export)")
    gate = subparsers.add_parser(
        "gate",
        help="Run gate arms (lint, format, types, test, test-full, docs, gnn)",
    )
    gate.add_argument(
        "arms",
        nargs="*",
        help="Arms to run (default: all). Also available: report (rewrites the timing doc)",
    )
    journal_check = subparsers.add_parser(
        "journal-check", help="Validate a sibling ActiveInferenceJournal checkout"
    )
    journal_check.add_argument(
        "--journal",
        type=Path,
        default=PROJECT_ROOT.parent / "ActiveInferenceJournal",
        help="ActiveInferenceJournal checkout (default: %(default)s)",
    )
    journal_check.add_argument(
        "--utilities",
        type=Path,
        default=PROJECT_ROOT,
        help="Journal-Utilities checkout containing the manifest (default: %(default)s)",
    )
    journal_check.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override the channel manifest path",
    )
    journal_check.add_argument(
        "--strict-manifest",
        action="store_true",
        help="Treat canonical journal IDs absent from the manifest as errors",
    )

    return parser


COMMAND_MAP = {
    "config": cmd_config,
    "export": cmd_export,
    "download": cmd_download,
    "serve": cmd_serve,
    "test": cmd_test,
    "full": cmd_full,
    "journal-check": cmd_journal_check,
    "gate": cmd_gate,
}


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, load config, dispatch to subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load config
    config = load_config(args.config)

    # Configure logging
    log_level = args.log_level or get_str(config, "general", "log_level", "INFO")

    # Setup root logger with both StreamHandler and FileHandler
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (repo-wide log.txt)
    file_handler = logging.FileHandler(PROJECT_ROOT / "log.txt", mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if not args.command:
        return cmd_default(config, args)

    handler = COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(config, args)


if __name__ == "__main__":
    sys.exit(main())
