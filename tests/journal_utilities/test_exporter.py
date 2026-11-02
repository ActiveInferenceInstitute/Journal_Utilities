"""Tests for the export module."""

import json
from pathlib import Path

import pytest

from journal_utilities.export.exporter import (
    ExportFormat,
    ExportResult,
    _stem_to_title,
    export_single,
    export_transcripts,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def transcript_dir(tmp_path):
    """Create a temporary directory with sample transcript files."""
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "abc123XYZ_q.txt").write_text(
        "Hello world.\nThis is a test transcript.\nActive Inference is discussed.\n",
        encoding="utf-8",
    )
    (tdir / "def456ABC_r.txt").write_text(
        "Second transcript content.\nMore text here.\n",
        encoding="utf-8",
    )
    return tdir


@pytest.fixture
def output_dir(tmp_path):
    """Create a temporary output directory."""
    odir = tmp_path / "export"
    odir.mkdir()
    return odir


@pytest.fixture
def single_transcript(tmp_path):
    """Create a single transcript file."""
    path = tmp_path / "test_video.txt"
    path.write_text(
        "This is a sample transcript.\nLine two.\nLine three.\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# ExportResult tests
# ---------------------------------------------------------------------------


class TestExportResult:
    def test_file_size_str_none(self):
        r = ExportResult(source_path="x", format=ExportFormat.PLAINTEXT, status="success")
        assert r.file_size_str == ""

    def test_file_size_str_bytes(self):
        r = ExportResult(
            source_path="x",
            format=ExportFormat.PLAINTEXT,
            status="success",
            file_size_bytes=512,
        )
        assert "512.0 B" == r.file_size_str

    def test_file_size_str_kilobytes(self):
        r = ExportResult(
            source_path="x",
            format=ExportFormat.PLAINTEXT,
            status="success",
            file_size_bytes=2048,
        )
        assert "2.0 KB" == r.file_size_str

    def test_file_size_str_megabytes(self):
        r = ExportResult(
            source_path="x",
            format=ExportFormat.PLAINTEXT,
            status="success",
            file_size_bytes=5 * 1024 * 1024,
        )
        assert "5.0 MB" == r.file_size_str


# ---------------------------------------------------------------------------
# _stem_to_title tests
# ---------------------------------------------------------------------------


class TestStemToTitle:
    def test_youtube_id_passthrough(self):
        assert _stem_to_title("abc123XYZ_q") == "abc123XYZ_q"

    def test_slug_to_title(self):
        assert _stem_to_title("my-great-video") == "My Great Video"

    def test_underscore_slug(self):
        assert _stem_to_title("active_inference_lecture") == "Active Inference Lecture"


# ---------------------------------------------------------------------------
# export_single tests
# ---------------------------------------------------------------------------


class TestExportSingle:
    def test_plaintext_export(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.PLAINTEXT)
        assert result.status == "success"
        assert result.output_path is not None
        out = Path(result.output_path)
        assert out.exists()
        assert out.suffix == ".txt"
        content = out.read_text(encoding="utf-8")
        assert "sample transcript" in content

    def test_markdown_export(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.MARKDOWN)
        assert result.status == "success"
        out = Path(result.output_path)
        content = out.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "title:" in content
        assert "# Test Video" in content

    def test_json_export(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.JSON)
        assert result.status == "success"
        out = Path(result.output_path)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "transcript" in data
        assert "word_count" in data
        assert data["word_count"] > 0

    def test_html_export(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.HTML)
        assert result.status == "success"
        out = Path(result.output_path)
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "<title>" in content

    def test_skip_existing(self, single_transcript, output_dir):
        result1 = export_single(single_transcript, output_dir, ExportFormat.PLAINTEXT)
        assert result1.status == "success"
        result2 = export_single(
            single_transcript, output_dir, ExportFormat.PLAINTEXT, skip_existing=True
        )
        assert result2.status == "skipped"

    def test_overwrite_existing(self, single_transcript, output_dir):
        result1 = export_single(single_transcript, output_dir, ExportFormat.PLAINTEXT)
        assert result1.status == "success"
        result2 = export_single(
            single_transcript, output_dir, ExportFormat.PLAINTEXT, skip_existing=False
        )
        assert result2.status == "success"

    def test_missing_source(self, output_dir):
        fake_path = Path("/nonexistent/path/video.txt")
        result = export_single(fake_path, output_dir, ExportFormat.PLAINTEXT)
        assert result.status == "failed"
        assert "Read error" in result.error

    def test_empty_transcript(self, tmp_path, output_dir):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        result = export_single(empty, output_dir, ExportFormat.PLAINTEXT)
        assert result.status == "failed"
        assert "empty" in result.error.lower()

    def test_result_has_timing(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.PLAINTEXT)
        assert result.duration_seconds >= 0

    def test_result_has_file_size(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.PLAINTEXT)
        assert result.file_size_bytes is not None
        assert result.file_size_bytes > 0


# ---------------------------------------------------------------------------
# export_transcripts (batch) tests
# ---------------------------------------------------------------------------


class TestExportTranscripts:
    def test_batch_plaintext(self, transcript_dir, output_dir):
        results = export_transcripts(transcript_dir, output_dir, formats=[ExportFormat.PLAINTEXT])
        assert "plaintext" in results
        assert len(results["plaintext"]) == 2
        successes = [r for r in results["plaintext"] if r.status == "success"]
        assert len(successes) == 2

    def test_batch_multiple_formats(self, transcript_dir, output_dir):
        results = export_transcripts(
            transcript_dir,
            output_dir,
            formats=[ExportFormat.PLAINTEXT, ExportFormat.JSON],
        )
        assert len(results) == 2
        assert "plaintext" in results
        assert "json" in results

    def test_batch_empty_dir(self, tmp_path, output_dir):
        empty_dir = tmp_path / "empty_transcripts"
        empty_dir.mkdir()
        results = export_transcripts(empty_dir, output_dir)
        assert results == {}

    def test_batch_creates_format_subdirs(self, transcript_dir, output_dir):
        export_transcripts(
            transcript_dir,
            output_dir,
            formats=[ExportFormat.MARKDOWN, ExportFormat.HTML],
        )
        assert (output_dir / "markdown").is_dir()
        assert (output_dir / "html").is_dir()

    def test_batch_default_format(self, transcript_dir, output_dir):
        results = export_transcripts(transcript_dir, output_dir)
        assert "plaintext" in results


# ---------------------------------------------------------------------------
# PDF export tests (conditional on fpdf2)
# ---------------------------------------------------------------------------


class TestPDFExport:
    @pytest.fixture(autouse=True)
    def check_fpdf2(self):
        try:
            import fpdf  # noqa: F401
        except ImportError:
            pytest.skip("fpdf2 not installed")

    def test_pdf_export(self, single_transcript, output_dir):
        result = export_single(single_transcript, output_dir, ExportFormat.PDF)
        assert result.status == "success"
        out = Path(result.output_path)
        assert out.exists()
        assert out.suffix == ".pdf"
        content = out.read_bytes()
        assert content[:5] == b"%PDF-"
