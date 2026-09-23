"""Extended test suite for transcription service in journal_utilities."""

from unittest.mock import MagicMock, patch

import pytest

# Requires the transcribe extra; skip cleanly when it is not installed.
pytest.importorskip("whisperx")

from journal_utilities.transcribe.transcribe import TranscriptionService


@pytest.fixture
def transcription_service() -> TranscriptionService:
    """Set up a TranscriptionService instance with mocked models for testing."""
    with (
        patch("whisperx.load_model") as mock_load_model,
        patch("whisperx.load_align_model") as mock_align_model,
        patch("journal_utilities.transcribe.transcribe.DiarizationPipeline") as mock_diarize,
    ):
        mock_load_model.return_value = MagicMock()
        mock_align_model.return_value = (MagicMock(), MagicMock())
        mock_diarize.return_value = MagicMock()

        service = TranscriptionService(
            hf_token="test_token", device="cpu", batch_size=1, compute_type="int8"
        )

    return service


class TestOutputText:
    """Tests for the output_text method."""

    def test_output_text_single_speaker(self, transcription_service: TranscriptionService) -> None:
        """Test output_text with a single speaker."""
        input_data = [
            {
                "start": 7.622,
                "end": 23.423,
                "text": " Hello everyone and welcome.",
                "speaker": "SPEAKER_00",
            }
        ]
        expected_output = "SPEAKER_00:\nHello everyone and welcome."
        output_result = transcription_service.output_text(input_data)
        assert output_result == expected_output

    def test_output_text_multiple_speakers(self, transcription_service: TranscriptionService) -> None:
        """Test output_text with multiple speakers."""
        input_data = [
            {"text": " Hello everyone.", "speaker": "SPEAKER_00"},
            {"text": " Welcome to the Lab.", "speaker": "SPEAKER_00"},
            {"text": " Thanks for having me.", "speaker": "SPEAKER_01"},
        ]
        output_result = transcription_service.output_text(input_data)
        assert "SPEAKER_00:" in output_result
        assert "SPEAKER_01:" in output_result
        assert "Hello everyone." in output_result
        assert "Thanks for having me." in output_result

    def test_output_text_empty_input(self, transcription_service: TranscriptionService) -> None:
        """Test output_text with empty input."""
        assert transcription_service.output_text([]) == ""

    def test_output_text_unknown_speaker(self, transcription_service: TranscriptionService) -> None:
        """Test output_text when speaker is missing."""
        input_data = [
            {"text": " Hello everyone.", "start": 0.0, "end": 1.0},
        ]
        output_result = transcription_service.output_text(input_data)
        assert "UNKNOWN:" in output_result

    def test_output_text_empty_segments(self, transcription_service: TranscriptionService) -> None:
        """Test output_text with empty text segments."""
        input_data = [
            {"text": "", "speaker": "SPEAKER_00"},
            {"text": "   ", "speaker": "SPEAKER_00"},
        ]
        output_result = transcription_service.output_text(input_data)
        assert output_result == ""

    def test_output_text_mixed_empty_and_content(self, transcription_service: TranscriptionService) -> None:
        """Test output_text with mix of empty and content segments."""
        input_data = [
            {"text": " Hello.", "speaker": "SPEAKER_00"},
            {"text": "", "speaker": "SPEAKER_00"},
            {"text": " Goodbye.", "speaker": "SPEAKER_01"},
        ]
        output_result = transcription_service.output_text(input_data)
        assert "Hello." in output_result
        assert "Goodbye." in output_result


class TestRemoveWords:
    """Tests for the remove_words method."""

    def test_remove_words_from_dict(self, transcription_service: TranscriptionService) -> None:
        """Test removing 'words' key from a dictionary."""
        input_data = {
            "text": "Hello",
            "words": [{"word": "Hello", "start": 0.0, "end": 0.5}],
            "speaker": "SPEAKER_00"
        }
        result = transcription_service.remove_words(input_data)
        assert "words" not in result
        assert result["text"] == "Hello"
        assert result["speaker"] == "SPEAKER_00"

    def test_remove_words_from_list(self, transcription_service: TranscriptionService) -> None:
        """Test removing 'words' from list of dicts."""
        input_data = [
            {"text": "Hello", "words": [{"word": "Hello"}]},
            {"text": "World", "words": [{"word": "World"}]},
        ]
        result = transcription_service.remove_words(input_data)
        assert len(result) == 2
        assert "words" not in result[0]
        assert "words" not in result[1]

    def test_remove_words_nested(self, transcription_service: TranscriptionService) -> None:
        """Test removing 'words' from nested structures."""
        input_data = {
            "segments": [
                {"text": "Hello", "words": [{"word": "Hello"}]}
            ],
            "words": ["should", "be", "removed"]
        }
        result = transcription_service.remove_words(input_data)
        assert "words" not in result
        assert "words" not in result["segments"][0]

    def test_remove_words_empty_input(self, transcription_service: TranscriptionService) -> None:
        """Test remove_words with empty inputs."""
        assert transcription_service.remove_words({}) == {}
        assert transcription_service.remove_words([]) == []

    def test_remove_words_no_words_key(self, transcription_service: TranscriptionService) -> None:
        """Test remove_words when no 'words' key exists."""
        input_data = {"text": "Hello", "speaker": "SPEAKER_00"}
        result = transcription_service.remove_words(input_data)
        assert result == input_data


class TestSimplifyTranscript:
    """Tests for the simplify_transcript method."""

    def test_simplify_transcript_basic(self, transcription_service: TranscriptionService) -> None:
        """Test simplify_transcript removes words arrays."""
        detailed = {
            "segments": [
                {
                    "text": "Hello",
                    "words": [{"word": "Hello", "start": 0.0}]
                }
            ]
        }
        result = transcription_service.simplify_transcript(detailed)
        assert "words" not in result.get("segments", [{}])[0]

    def test_simplify_transcript_preserves_other_fields(self, transcription_service: TranscriptionService) -> None:
        """Test simplify_transcript keeps non-words fields."""
        detailed = [
            {
                "text": "Hello",
                "start": 0.0,
                "end": 1.0,
                "speaker": "SPEAKER_00",
                "words": [{"word": "Hello"}]
            }
        ]
        result = transcription_service.simplify_transcript(detailed)
        assert result[0]["text"] == "Hello"
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 1.0
        assert result[0]["speaker"] == "SPEAKER_00"
        assert "words" not in result[0]


class TestTranscriptionServiceInit:
    """Tests for TranscriptionService initialization."""

    def test_initialization_stores_parameters(self) -> None:
        """Test that initialization stores all parameters."""
        with (
            patch("whisperx.load_model") as mock_load_model,
            patch("whisperx.load_align_model") as mock_align_model,
            patch("journal_utilities.transcribe.transcribe.DiarizationPipeline") as mock_diarize,
        ):
            mock_load_model.return_value = MagicMock()
            mock_align_model.return_value = (MagicMock(), MagicMock())
            mock_diarize.return_value = MagicMock()

            service = TranscriptionService(
                hf_token="my_token",
                device="cuda",
                batch_size=16,
                compute_type="float16"
            )

            assert service.hf_token == "my_token"
            assert service.device == "cuda"
            assert service.batch_size == 16
            assert service.compute_type == "float16"

    def test_initialization_loads_models(self) -> None:
        """Test that initialization loads all required models."""
        with (
            patch("whisperx.load_model") as mock_load_model,
            patch("whisperx.load_align_model") as mock_align_model,
            patch("journal_utilities.transcribe.transcribe.DiarizationPipeline") as mock_diarize,
        ):
            mock_load_model.return_value = MagicMock()
            mock_align_model.return_value = (MagicMock(), MagicMock())
            mock_diarize.return_value = MagicMock()

            TranscriptionService(
                hf_token="token",
                device="cpu",
                batch_size=1,
                compute_type="int8"
            )

            mock_load_model.assert_called_once()
            mock_align_model.assert_called_once()
            mock_diarize.assert_called_once()
