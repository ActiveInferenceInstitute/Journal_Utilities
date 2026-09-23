"""Tests for scripts/translate_subtitles_openrouter.py (pure logic, no network)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from translate_subtitles_openrouter import (  # noqa: E402
    translate_srt,
    translation_filename,
)

SRT = (
    "1\r\n00:00:02,940 --> 00:00:05,939\r\nhello there,\r\n\r\n"
    "2\r\n00:00:17,359 --> 00:00:20,520\r\ngood morning\r\n"
)


def test_translation_filename_strips_noisy_suffixes():
    assert translation_filename(Path("Reward Is Not Necessary.en(ca).srt"), "es") == (
        "Reward Is Not Necessary.en(ca).es.srt"
    )
    assert translation_filename(Path("Reward Is Not Necessary.en.srt"), "es") == (
        "Reward Is Not Necessary.es.srt"
    )
    assert translation_filename(Path("whatever.m4a.srt"), "fr") == "whatever.fr.srt"


def test_translate_srt_success_path(monkeypatch):
    from translate_subtitles_openrouter import translate_batch  # noqa: E402

    monkeypatch.setattr(
        "translate_subtitles_openrouter.translate_batch",
        lambda texts, lang, model, api_key, base_url, max_tokens=16000: texts,
    )
    out, fallbacks, cues = translate_srt(SRT, "es", "m", "k", "http://x", 60, 2)
    assert fallbacks == 0 and cues == 2
    assert out.replace("\r\n", "\n") == (
        "1\n00:00:02,940 --> 00:00:05,939\nhello there,\n\n"
        "2\n00:00:17,359 --> 00:00:20,520\ngood morning\n"
    )
    assert translate_batch  # keep the import referenced / avoid unused warning


def test_translate_srt_falls_back_to_source_when_api_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr("translate_subtitles_openrouter.translate_batch", boom)
    out, fallbacks, cues = translate_srt(SRT, "es", "m", "k", "http://x", 60, 2)
    # Both single-cue chunks fell back to the source text; structure preserved.
    assert fallbacks == 2 and cues == 2
    assert out.replace("\r\n", "\n") == (
        "1\n00:00:02,940 --> 00:00:05,939\nhello there,\n\n"
        "2\n00:00:17,359 --> 00:00:20,520\ngood morning\n"
    )


def test_load_api_key_requires_env_or_repo_env(monkeypatch, tmp_path):
    from translate_subtitles_openrouter import load_api_key  # noqa: E402

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("translate_subtitles_openrouter.Path", lambda *a: tmp_path / "nope")
    try:
        load_api_key()
        raise AssertionError("should have exited")
    except SystemExit as e:
        assert "OPENROUTER_API_KEY" in str(e)


def test_existing_translation_checks_both_spellings(tmp_path):
    from translate_subtitles_openrouter import existing_translation

    item = tmp_path / "Item_001"
    legacy = item / "Translations"
    legacy.mkdir(parents=True)
    (legacy / "V.es.srt").write_text("existing", encoding="utf-8")

    found = existing_translation(item, "V.es.srt")
    assert found is not None and found.exists() and found.name == "V.es.srt"
    assert existing_translation(item, "V.de.srt") is None


def test_main_skips_existing_translation_in_legacy_spelling(tmp_path, monkeypatch, capsys):
    from translate_subtitles_openrouter import main

    journal = tmp_path / "journal"
    item = journal / "data/video/activeinferenceinstitute/Series/Item_001"
    (item / "captions").mkdir(parents=True)
    (item / "captions" / "V.en.srt").write_text(SRT, encoding="utf-8")
    (item / "Translations").mkdir()
    (item / "Translations" / "V.es.srt").write_text("existing", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["prog", "--journal", str(journal), "--lang", "es"])
    monkeypatch.setattr("translate_subtitles_openrouter.load_api_key", lambda: "k")

    def boom(*args, **kwargs):
        raise AssertionError("translate_srt must not run for already-existing output")

    monkeypatch.setattr("translate_subtitles_openrouter.translate_srt", boom)

    assert main() == 0
    out = capsys.readouterr().out
    assert "skipped 1 existing" in out
    # Nothing new was written and the legacy file is untouched.
    assert len(list(item.rglob("*.srt"))) == 2
    assert (item / "Translations" / "V.es.srt").read_text(encoding="utf-8") == "existing"
