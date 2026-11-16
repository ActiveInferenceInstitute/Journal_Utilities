"""Tests for run.py — config loading and CLI argument parsing."""

import configparser

# Import the run.py module from the project root
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from run import (
    build_parser,
    cmd_default,
    get_bool,
    get_int,
    get_str,
    load_config,
    main,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_config_file(tmp_path):
    """Create a temporary config.ini with known values."""
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        """\
[general]
data_dir = data/output
log_level = DEBUG

[download]
transcripts = true
audio = false
video = false
resume = true
max_videos = 10
delay = 2
cookies_from_browser = chrome

[export]
plaintext = true
pdf = false
markdown = true
json = false
html = false
output_dir = data/export

[interface]
host = 127.0.0.1
port = 9000

[database]
url = ws://localhost:8080/rpc
user = root
password = secret
namespace = test_ns
database = test_db
""",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def config(sample_config_file):
    """Load the sample config."""
    return load_config(sample_config_file)


# ---------------------------------------------------------------------------
# Config loading tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_load_existing_config(self, sample_config_file):
        cfg = load_config(sample_config_file)
        assert cfg.has_section("general")
        assert cfg.has_section("download")
        assert cfg.has_section("export")
        assert cfg.has_section("interface")
        assert cfg.has_section("database")

    def test_load_missing_config(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.ini")
        assert isinstance(cfg, configparser.ConfigParser)
        assert cfg.sections() == []

    def test_section_count(self, config):
        assert len(config.sections()) == 5


# ---------------------------------------------------------------------------
# Config helper tests
# ---------------------------------------------------------------------------


class TestConfigHelpers:
    def test_get_bool_true(self, config):
        assert get_bool(config, "download", "transcripts") is True

    def test_get_bool_false(self, config):
        assert get_bool(config, "download", "audio") is False

    def test_get_bool_missing_key(self, config):
        assert get_bool(config, "download", "nonexistent", fallback=True) is True

    def test_get_bool_missing_section(self, config):
        assert get_bool(config, "nosection", "nokey", fallback=False) is False

    def test_get_str(self, config):
        assert get_str(config, "general", "data_dir") == "data/output"

    def test_get_str_fallback(self, config):
        assert get_str(config, "general", "missing", "default_val") == "default_val"

    def test_get_int(self, config):
        assert get_int(config, "download", "max_videos") == 10

    def test_get_int_fallback(self, config):
        assert get_int(config, "download", "missing", fallback=99) == 99

    def test_interface_host(self, config):
        assert get_str(config, "interface", "host") == "127.0.0.1"

    def test_interface_port(self, config):
        assert get_int(config, "interface", "port") == 9000

    def test_database_values(self, config):
        assert get_str(config, "database", "user") == "root"
        assert get_str(config, "database", "password") == "secret"
        assert get_str(config, "database", "namespace") == "test_ns"


# ---------------------------------------------------------------------------
# CLI parser tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_parser_no_args(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_parser_config_command(self):
        parser = build_parser()
        args = parser.parse_args(["config"])
        assert args.command == "config"

    def test_parser_export_command(self):
        parser = build_parser()
        args = parser.parse_args(["export"])
        assert args.command == "export"

    def test_parser_download_command(self):
        parser = build_parser()
        args = parser.parse_args(["download"])
        assert args.command == "download"

    def test_parser_serve_command(self):
        parser = build_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"

    def test_parser_test_command(self):
        parser = build_parser()
        args = parser.parse_args(["test"])
        assert args.command == "test"

    def test_parser_full_command(self):
        parser = build_parser()
        args = parser.parse_args(["full"])
        assert args.command == "full"

    def test_parser_journal_check_command(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "journal-check",
                "--journal",
                "/tmp/journal",
                "--manifest",
                "/tmp/manifest.json",
                "--strict-manifest",
            ]
        )
        assert args.command == "journal-check"
        assert args.journal == Path("/tmp/journal")
        assert args.manifest == Path("/tmp/manifest.json")
        assert args.strict_manifest is True

    def test_parser_custom_config_path(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "/tmp/my.ini", "config"])
        assert args.config == Path("/tmp/my.ini")

    def test_parser_log_level_override(self):
        parser = build_parser()
        args = parser.parse_args(["--log-level", "DEBUG", "export"])
        assert args.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.fixture(autouse=True)
    def isolated_runner_logging(self, tmp_path, monkeypatch):
        import logging

        import run

        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path)
        try:
            yield
        finally:
            for handler in list(root.handlers):
                if handler not in handlers:
                    handler.close()
            root.handlers[:] = handlers
            root.setLevel(level)

    def test_config_command_returns_zero(self, sample_config_file):
        rc = main(["--config", str(sample_config_file), "config"])
        assert rc == 0

    def test_config_shows_sections(self, sample_config_file, capsys):
        main(["--config", str(sample_config_file), "config"])
        captured = capsys.readouterr()
        assert "[general]" in captured.out
        assert "[download]" in captured.out
        assert "[export]" in captured.out


# ---------------------------------------------------------------------------
# Default pipeline tests
# ---------------------------------------------------------------------------


class TestDefaultPipeline:
    """Tests for cmd_default — the pipeline that runs with no subcommand."""

    def test_default_shows_config(self, config, capsys, monkeypatch):
        """Config display (Step 1/5) should print all sections."""
        import argparse

        import run

        args = argparse.Namespace(command=None, config=None, log_level=None)
        # Monkeypatch heavy steps to keep the test fast
        monkeypatch.setattr(run, "cmd_export", lambda cfg, a: 0)
        monkeypatch.setattr(run, "cmd_test", lambda cfg, a: 0)
        monkeypatch.setattr(run, "cmd_serve", lambda cfg, a: 0)

        cmd_default(config, args)
        captured = capsys.readouterr()
        assert "Step 1/5" in captured.out
        assert "[general]" in captured.out
        assert "[download]" in captured.out

    def test_default_pipeline_fails_closed_on_test_error(self, config, monkeypatch):
        """A failing test step must not start the web interface by default."""
        import argparse

        import run

        args = argparse.Namespace(command=None, config=None, log_level=None)
        monkeypatch.setattr(run, "cmd_export", lambda cfg, a: 0)
        monkeypatch.setattr(run, "cmd_test", lambda cfg, a: 7)
        monkeypatch.setattr(run, "cmd_serve", lambda cfg, a: pytest.fail("serve started"))

        assert run.cmd_default(config, args) == 7

    def test_default_validates_data(self, config, capsys, monkeypatch):
        """Validation step (Step 2/5) should report on data directories."""
        import argparse

        import run

        args = argparse.Namespace(command=None, config=None, log_level=None)
        monkeypatch.setattr(run, "cmd_export", lambda cfg, a: 0)
        monkeypatch.setattr(run, "cmd_test", lambda cfg, a: 0)
        monkeypatch.setattr(run, "cmd_serve", lambda cfg, a: 0)

        cmd_default(config, args)
        captured = capsys.readouterr()
        assert "Step 2/5" in captured.out
        # Should mention data directory status (either ✓ or ✗)
        assert "Data directory" in captured.out

    def test_default_shows_clickable_url(self, config, capsys, monkeypatch):
        """Step 5/5 should print the clickable URL before serving."""
        import argparse

        args = argparse.Namespace(command=None, config=None, log_level=None)

        # Monkeypatch cmd_serve to avoid actually starting the server
        import run

        monkeypatch.setattr(run, "cmd_serve", lambda cfg, a: 0)
        # Monkeypatch cmd_test to avoid running real tests
        monkeypatch.setattr(run, "cmd_test", lambda cfg, a: 0)
        # Monkeypatch cmd_export to avoid running real export
        monkeypatch.setattr(run, "cmd_export", lambda cfg, a: 0)

        rc = cmd_default(config, args)
        captured = capsys.readouterr()
        assert "http://127.0.0.1:9000" in captured.out
        assert "Open in browser" in captured.out
        assert rc == 0


@pytest.fixture
def export_corpus(config, tmp_path, monkeypatch):
    import run

    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path)
    transcripts = tmp_path / "data" / "output" / "transcripts"
    transcripts.mkdir(parents=True)
    config.set("export", "markdown", "false")
    return config, transcripts, tmp_path / "data" / "export" / "plaintext"


def test_export_empty_directory_is_incomplete(export_corpus):
    import argparse

    import run

    cfg, _, _ = export_corpus
    assert run.cmd_export(cfg, argparse.Namespace()) == 1


@pytest.mark.parametrize("bad_bytes", [b"   ", b"\xff\xfe"])
def test_export_mixed_success_and_failure_is_nonzero(export_corpus, bad_bytes):
    import argparse

    import run

    cfg, transcripts, output = export_corpus
    (transcripts / "good.txt").write_text("A valid transcript", encoding="utf-8")
    (transcripts / "bad.txt").write_bytes(bad_bytes)
    assert run.cmd_export(cfg, argparse.Namespace()) == 1
    assert "A valid transcript" in (output / "good.txt").read_text(encoding="utf-8")
    assert not (output / "bad.txt").exists()


def test_export_read_permission_failure_is_nonzero(export_corpus, monkeypatch):
    import argparse

    import run

    cfg, transcripts, _ = export_corpus
    blocked = transcripts / "blocked.txt"
    blocked.write_text("Cannot read", encoding="utf-8")
    read_text = Path.read_text

    def guarded_read(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("Access denied")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    assert run.cmd_export(cfg, argparse.Namespace()) == 1


def test_export_success_and_existing_outputs_remain_successful(export_corpus):
    import argparse

    import run

    cfg, transcripts, output = export_corpus
    (transcripts / "good.txt").write_text("A valid transcript", encoding="utf-8")
    assert run.cmd_export(cfg, argparse.Namespace()) == 0
    saved = (output / "good.txt").read_bytes()
    assert run.cmd_export(cfg, argparse.Namespace()) == 0
    assert (output / "good.txt").read_bytes() == saved


@pytest.mark.parametrize("command", ["cmd_full", "cmd_default"])
def test_required_export_failure_stops_pipeline(export_corpus, monkeypatch, command):
    import argparse

    import run

    cfg, transcripts, _ = export_corpus
    (transcripts / "empty.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(run, "cmd_download", lambda *_: 0)
    monkeypatch.setattr(run, "cmd_test", lambda *_: pytest.fail("tests started after failed export"))
    monkeypatch.setattr(run, "cmd_serve", lambda *_: pytest.fail("server started after failed export"))
    assert getattr(run, command)(cfg, argparse.Namespace()) == 1


def test_occupied_listener_survives_serve_refusal(config, monkeypatch):
    import argparse
    import socket

    import run

    uvicorn = pytest.importorskip("uvicorn")
    pytest.importorskip("fastapi")
    monkeypatch.setattr(run.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("listener discovery attempted"))
    monkeypatch.setattr(run.os, "kill", lambda *_args, **_kwargs: pytest.fail("listener termination attempted"))
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: pytest.fail("occupied server started"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)
        port = listener.getsockname()[1]
        config.set("interface", "port", str(port))
        assert run.cmd_serve(config, argparse.Namespace()) == 1
        with socket.create_connection(("127.0.0.1", port), timeout=2) as probe:
            accepted, _ = listener.accept()
            with accepted:
                probe.sendall(b"still alive")
                assert accepted.recv(11) == b"still alive"


@pytest.mark.parametrize("absolute", [False, True])
def test_serve_loads_configured_corpus(config, tmp_path, monkeypatch, absolute):
    import argparse
    import json

    import run

    uvicorn = pytest.importorskip("uvicorn")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    chosen = tmp_path / "chosen"
    chosen.mkdir()
    (chosen / "channel_videos.json").write_text(json.dumps({"videos": [
        {"id": "chosen12345", "title": "Chosen corpus", "upload_date": "20250101"}
    ]}), encoding="utf-8")
    monkeypatch.setattr(run, "PROJECT_ROOT", tmp_path)
    config.set("general", "data_dir", str(chosen) if absolute else "chosen")
    config.set("interface", "port", "0")
    observed = []

    def serve_boundary(app, **_kwargs):
        with TestClient(app) as client:
            response = client.get("/api/videos")
            observed.extend(video["id"] for video in response.json()["videos"])

    monkeypatch.setattr(uvicorn, "run", serve_boundary)
    assert run.cmd_serve(config, argparse.Namespace()) == 0
    assert observed == ["chosen12345"]


def test_export_writer_failure_is_nonzero(export_corpus, monkeypatch):
    import argparse

    import run

    cfg, transcripts, output = export_corpus
    (transcripts / "blocked.txt").write_text("Readable input", encoding="utf-8")
    write_text = Path.write_text

    def guarded_write(path, *args, **kwargs):
        if path == output / "blocked.txt":
            raise OSError("Output device unavailable")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write)
    assert run.cmd_export(cfg, argparse.Namespace()) == 1
