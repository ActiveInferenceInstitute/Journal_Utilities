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
