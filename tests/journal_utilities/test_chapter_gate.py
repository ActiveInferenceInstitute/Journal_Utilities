"""Chapter gate tests: one failing case per validation rule, plus generation
windowing, provenance, and the retry contract."""

import json
from datetime import UTC, datetime

import pytest

from journal_utilities.youtube.chapter_generator import (
    ChapterError,
    ChapterGenerator,
    build_windowed_transcript_text,
    generation_provenance,
    save_generated_chapters,
    validate_chapters,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TITLES = [
    "Introduction to Free Energy",
    "Markov Blankets and States",
    "Expected Free Energy Derivation",
    "Precision Weighted Prediction Errors",
    "Generative Models in Action",
    "Active Inference Closing Themes",
]


def good_chapters(duration: float = 3600.0, count: int = 6) -> list[dict]:
    """A list that passes every rule: >=3 chapters, first at 0:00, 10s+ gaps,
    last at >=80% of duration, 3-8 word titles <=60 chars, no filler, no
    speaker names."""
    step = (duration * 0.85) / (count - 1)
    return [{"start": round(i * step, 1), "title": TITLES[i % len(TITLES)]} for i in range(count)]


DURATION = 3600.0


# ---------------------------------------------------------------------------
# Rule: count >= 3
# ---------------------------------------------------------------------------


class TestRuleCount:
    def test_empty_list_fails(self):
        report = validate_chapters([], duration_seconds=DURATION)
        assert not report.passed
        assert any("count" in f for f in report.failures)

    def test_two_chapters_fail(self):
        report = validate_chapters(good_chapters()[:2], duration_seconds=DURATION)
        assert not report.passed
        assert any("chapters < minimum" in f for f in report.failures)

    def test_three_chapters_pass_count_rule(self):
        report = validate_chapters(good_chapters(count=3), duration_seconds=DURATION)
        assert not any("count" in f for f in report.failures)


# ---------------------------------------------------------------------------
# Rule: first chapter at 0:00
# ---------------------------------------------------------------------------


class TestRuleFirstAtZero:
    def test_first_not_at_zero_fails(self):
        chapters = good_chapters()
        chapters[0]["start"] = 5.0
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("first-at-zero" in f for f in report.failures)

    def test_first_at_zero_passes(self):
        report = validate_chapters(good_chapters(), duration_seconds=DURATION)
        assert not any("first-at-zero" in f for f in report.failures)


# ---------------------------------------------------------------------------
# Rule: gaps >= 10s
# ---------------------------------------------------------------------------


class TestRuleGaps:
    def test_nine_second_gap_fails(self):
        chapters = [
            {"start": 0.0, "title": TITLES[0]},
            {"start": 9.0, "title": TITLES[1]},
            {"start": 900.0, "title": TITLES[2]},
            {"start": 3200.0, "title": TITLES[3]},
        ]
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("gap" in f for f in report.failures)

    def test_exactly_ten_second_gap_passes(self):
        chapters = [
            {"start": 0.0, "title": TITLES[0]},
            {"start": 10.0, "title": TITLES[1]},
            {"start": 3200.0, "title": TITLES[2]},
        ]
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not any("gap" in f for f in report.failures)

    def test_duplicate_timestamps_fail(self):
        chapters = [
            {"start": 0.0, "title": TITLES[0]},
            {"start": 0.0, "title": TITLES[1]},
            {"start": 3200.0, "title": TITLES[2]},
        ]
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("gap" in f for f in report.failures)


# ---------------------------------------------------------------------------
# Rule: last chapter >= 80% of duration
# ---------------------------------------------------------------------------


class TestRuleCoverage:
    def test_last_below_eighty_percent_fails(self):
        chapters = good_chapters()
        chapters[-1]["start"] = 0.79 * DURATION
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("coverage" in f for f in report.failures)

    def test_last_at_eighty_percent_passes(self):
        chapters = good_chapters()
        chapters[-1]["start"] = 0.80 * DURATION
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not any("coverage" in f for f in report.failures)

    def test_missing_duration_skips_coverage_rule(self):
        # Without a duration the coverage rule cannot fire; list must still
        # pass on the other rules rather than fail wholesale.
        report = validate_chapters(good_chapters(), duration_seconds=None)
        assert report.passed


# ---------------------------------------------------------------------------
# Rule: titles 3-8 words, <= 60 chars
# ---------------------------------------------------------------------------


class TestRuleTitles:
    def test_two_word_title_fails(self):
        chapters = good_chapters()
        chapters[1]["title"] = "Free Energy"
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("title-words" in f for f in report.failures)

    def test_nine_word_title_fails(self):
        chapters = good_chapters()
        chapters[1]["title"] = "One Two Three Four Five Six Seven Eight Nine"
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("title-words" in f for f in report.failures)

    def test_title_over_sixty_chars_fails(self):
        chapters = good_chapters()
        chapters[1]["title"] = "A " + "very " * 14 + "long title"  # > 60 chars, 3+ words
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("title-chars" in f for f in report.failures)

    def test_eight_word_sixty_char_title_passes(self):
        chapters = good_chapters()
        title = "Eight word title sitting exactly at the boundary"
        assert len(title.split()) == 8 and len(title) <= 60
        chapters[1]["title"] = title
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not any("title" in f for f in report.failures)


# ---------------------------------------------------------------------------
# Rule: no filler words (uh, um, so, like)
# ---------------------------------------------------------------------------


class TestRuleFiller:
    @pytest.mark.parametrize("filler", ["uh", "um", "so", "like"])
    def test_filler_words_fail(self, filler):
        chapters = good_chapters()
        chapters[1]["title"] = f"Free Energy {filler} What Comes Next"
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("filler" in f for f in report.failures)

    def test_filler_inside_word_is_not_flagged(self):
        chapters = good_chapters()
        chapters[1]["title"] = "Somebody Likened Models To Organisms"
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not any("filler" in f for f in report.failures)


# ---------------------------------------------------------------------------
# Rule: no bare speaker names
# ---------------------------------------------------------------------------


class TestRuleSpeakerNames:
    @pytest.mark.parametrize(
        "title",
        [
            "Karl Friston",
            "Karl Friston.",
            "Karl Friston's",
            "Daniel Ari Friedman",
        ],
    )
    def test_bare_speaker_names_fail(self, title):
        chapters = good_chapters()
        chapters[1]["title"] = title
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("speaker-name" in f for f in report.failures)

    @pytest.mark.parametrize(
        "title",
        [
            "Karl Friston on Free Energy",
            "Free Energy Principle with Karl Friston",
            "Friston's Free Energy Formulation",
        ],
    )
    def test_topical_titles_with_names_pass(self, title):
        chapters = good_chapters()
        chapters[1]["title"] = title
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not any("speaker-name" in f for f in report.failures)


# ---------------------------------------------------------------------------
# Boundary / mixed cases
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_good_list_passes_all_rules(self):
        report = validate_chapters(good_chapters(), duration_seconds=DURATION)
        assert report.passed, report.failures

    def test_non_numeric_start_fails(self):
        chapters = good_chapters()
        chapters[2]["start"] = "not-a-number"
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert not report.passed
        assert any("start" in f for f in report.failures)

    def test_start_time_key_accepted(self):
        # yt-dlp chapter dicts use start_time
        chapters = good_chapters()
        for ch in chapters:
            ch["start_time"] = ch.pop("start")
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert report.passed, report.failures

    def test_failures_aggregate_not_short_circuit(self):
        chapters = good_chapters()
        chapters[0]["start"] = 4.0  # first-at-zero
        chapters[1]["title"] = "um"  # filler + too short + too few words
        chapters[-1]["start"] = 0.5 * DURATION  # coverage
        report = validate_chapters(chapters, duration_seconds=DURATION)
        assert len(report.failures) >= 4


# ---------------------------------------------------------------------------
# Windowed transcript rendering (3-5 min blocks over the FULL transcript)
# ---------------------------------------------------------------------------


class TestWindowedTranscript:
    def _segments(self, total_seconds: float, seg_step: float = 15.0) -> list[dict]:
        segs = []
        t = 0.0
        i = 0
        while t < total_seconds:
            segs.append({"start": t, "text": f"sentence {i}"})
            t += seg_step
            i += 1
        return segs

    def test_covers_full_transcript_not_just_head(self):
        segs = self._segments(7200.0)  # 2 hours
        text = build_windowed_transcript_text(segs, window_seconds=300.0)
        # Last window start must be near the transcript tail, not capped early
        assert "[01:55:00]" in text

    def test_windows_are_within_three_to_five_minutes(self):
        from journal_utilities.youtube.chapter_generator import parse_timestamp_to_seconds

        segs = self._segments(3600.0)
        for width in (180.0, 240.0, 300.0):
            text = build_windowed_transcript_text(segs, window_seconds=width)
            lines = [ln for ln in text.splitlines() if ln.startswith("[")]
            starts = [parse_timestamp_to_seconds(ln[1 : ln.index("]")]) for ln in lines]
            assert None not in starts
            assert starts[0] == 0.0
            # Window starts advance by the requested width (3-5 min steps)
            gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
            assert all(170.0 <= g <= 305.0 for g in gaps), (width, gaps[:5])

    def test_empty_transcript_renders_empty(self):
        assert build_windowed_transcript_text([]) == ""

    def test_timestamp_lines_carry_segment_text(self):
        segs = [{"start": 0.0, "text": "opening words"}, {"start": 200.0, "text": "later words"}]
        text = build_windowed_transcript_text(segs, window_seconds=300.0)
        assert "[00:00] opening words" in text
        assert "later words" in text


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_provenance_block_fields(self):
        stamp = datetime(2026, 9, 23, tzinfo=UTC)
        block = generation_provenance("gemma3:4b", stamp)
        assert block == {
            "source": "llm",
            "model": "gemma3:4b",
            "generated_at": "2026-09-23T00:00:00+00:00",
        }

    def test_save_skips_youtube_sourced_entries(self, tmp_path):
        cache = tmp_path / "video_chapters_llm.json"
        cache.write_text(
            json.dumps(
                {"abc123": {"source": "youtube", "chapters": [{"start": 0.0, "title": "x"}]}}
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="YouTube-sourced"):
            save_generated_chapters(
                str(cache),
                "abc123",
                [],
                model="gemma3:4b",
                generated_at=datetime.now(UTC),
            )

    def test_save_writes_provenance_payload(self, tmp_path):
        from journal_utilities.youtube.metadata_formatter import ChapterEntry

        cache = tmp_path / "video_chapters_llm.json"
        save_generated_chapters(
            str(cache),
            "vid456",
            [ChapterEntry(start=0.0, title="Introduction to Session")],
            model="gemma3:4b",
            generated_at=datetime(2026, 9, 23, tzinfo=UTC),
        )
        payload = json.loads(cache.read_text(encoding="utf-8"))
        entry = payload["vid456"]
        assert entry["source"] == "llm"
        assert entry["model"] == "gemma3:4b"
        assert entry["chapters"] == [{"start": 0.0, "title": "Introduction to Session"}]


# ---------------------------------------------------------------------------
# Gate + retry contract
# ---------------------------------------------------------------------------


class _FakeGenerator(ChapterGenerator):
    """Substitutes scripted model outputs for the HTTP backends."""

    def __init__(self, responses: list[str]):
        super().__init__(backend="ollama")
        self.responses = list(responses)
        self.calls = 0

    def _call(self, prompt: str) -> str:  # noqa: D102 - test double
        self.calls += 1
        return self.responses.pop(0)


class TestGenerationGate:
    def _segments(self, total_seconds: float) -> list[dict]:
        return [
            {"start": float(t), "end": float(t + 15), "text": f"words {t}"}
            for t in range(0, int(total_seconds), 15)
        ]

    def test_passing_output_returned_after_earlier_failures(self):
        # Attempt 1: last chapter short of 80% (gate fails).
        # Attempt 2: passes all rules.
        bad = "\n".join(
            f"{int(s // 60):02d}:{int(s % 60):02d} {t}"
            for s, t in zip([0, 600, 1200], TITLES[:3], strict=True)
        )
        good = "\n".join(
            f"{int(s // 60):02d}:{int(s % 60):02d} {t}"
            for s, t in zip([0, 600, 3300], TITLES[:3], strict=True)
        )
        gen = _FakeGenerator([bad, good])
        chapters = gen.generate_chapters(
            title="Test Session",
            transcript_segments=self._segments(3600.0),
            total_duration_seconds=3600.0,
            max_attempts=2,
        )
        assert [c.title for c in chapters] == TITLES[:3]
        assert gen.calls == 2

    def test_chapter_error_after_exhausted_attempts(self):
        bad = "\n".join(
            f"{int(s // 60):02d}:{int(s % 60):02d} {t}"
            for s, t in zip([0, 600, 1200], TITLES[:3], strict=True)
        )
        gen = _FakeGenerator([bad, bad, bad])
        with pytest.raises(ChapterError, match="failed the gate after 3 attempts"):
            gen.generate_chapters(
                title="Test Session",
                transcript_segments=self._segments(3600.0),
                total_duration_seconds=3600.0,
            )
        assert gen.calls == 3

    def test_no_transcript_raises_immediately(self):
        gen = _FakeGenerator([])
        with pytest.raises(ChapterError, match="no transcript"):
            gen.generate_chapters(title="X", transcript_segments=[], total_duration_seconds=60.0)
        assert gen.calls == 0

    def test_duration_defaults_to_transcript_tail_when_absent(self):
        # Without an explicit duration, the tail of the transcript is used.
        good = "\n".join(
            f"{int(s // 60):02d}:{int(s % 60):02d} {t}"
            for s, t in zip([0, 600, 3300], TITLES[:3], strict=True)
        )
        gen = _FakeGenerator([good])
        chapters = gen.generate_chapters(
            title="Test Session",
            transcript_segments=self._segments(3600.0),
        )
        assert len(chapters) == 3
