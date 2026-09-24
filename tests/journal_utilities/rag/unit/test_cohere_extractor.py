"""
Unit tests for CohereExtractor with mocked Cohere API.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# Requires the rag extra; skip cleanly when it is not installed.
pytest.importorskip("cohere")

from journal_utilities.rag.extractors.cohere_extractor import CohereExtractor
from journal_utilities.rag.models.entities import CoreEntities, DetailedAnalysis


@pytest.fixture
def mock_settings():
    """Mock settings for CohereExtractor."""
    with patch("journal_utilities.rag.extractors.cohere_extractor.settings") as mock:
        mock.cohere_api_key = "test-api-key"
        mock.cohere_model = "test-model"
        yield mock


@pytest.fixture
def mock_cohere_client():
    """Mock the Cohere client."""
    with patch("journal_utilities.rag.extractors.cohere_extractor.cohere.ClientV2") as mock:
        yield mock


@pytest.fixture
def mock_schemas():
    """Mock schema loading."""
    with patch("journal_utilities.rag.extractors.cohere_extractor.load_core_schema") as mock_core, \
         patch("journal_utilities.rag.extractors.cohere_extractor.load_detailed_schema") as mock_detailed:
        mock_core.return_value = {"type": "object"}
        mock_detailed.return_value = {"type": "object"}
        yield mock_core, mock_detailed


class TestCohereExtractorInit:
    """Tests for CohereExtractor initialization."""

    def test_init_with_defaults(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test initialization uses settings by default."""
        extractor = CohereExtractor()

        assert extractor.api_key == "test-api-key"
        assert extractor.model == "test-model"
        mock_cohere_client.assert_called_once_with(api_key="test-api-key")

    def test_init_with_custom_values(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test initialization with custom api_key and model."""
        extractor = CohereExtractor(api_key="custom-key", model="custom-model")

        assert extractor.api_key == "custom-key"
        assert extractor.model == "custom-model"
        mock_cohere_client.assert_called_once_with(api_key="custom-key")

    def test_init_loads_schemas(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test initialization loads both schemas."""
        mock_core, mock_detailed = mock_schemas

        CohereExtractor()

        mock_core.assert_called_once()
        mock_detailed.assert_called_once()


class TestExtractCoreEntities:
    """Tests for extract_core_entities method."""

    def test_extract_core_entities_success(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test successful core entity extraction."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text=json.dumps({
            "concepts": [],
            "researchers": [],
            "citations": [],
            "technical_terms": [],
            "key_insights": []
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_core_entities("Test transcript text")

        assert isinstance(result, CoreEntities)
        mock_client_instance.chat.assert_called_once()

    def test_extract_core_entities_with_data(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test extraction returns populated entities."""
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text=json.dumps({
            "concepts": [
                {
                    "name": "Active Inference",
                    "definition": "A framework for understanding behavior",
                    "category": "theoretical",
                    "related_concepts": []
                }
            ],
            "researchers": [
                {
                    "name": "Karl Friston",
                    "role": "cited_author",
                    "affiliation": "UCL"
                }
            ],
            "citations": [],
            "technical_terms": [],
            "key_insights": ["Key insight 1"]
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_core_entities("Test transcript")

        assert len(result.concepts) == 1
        assert result.concepts[0].name == "Active Inference"
        assert len(result.researchers) == 1
        assert result.researchers[0].name == "Karl Friston"
        assert len(result.key_insights) == 1

    def test_extract_core_entities_handles_error(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test extraction raises exception on API error."""
        mock_client_instance = MagicMock()
        mock_client_instance.chat.side_effect = Exception("API Error")
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()

        with pytest.raises(Exception, match="API Error"):
            extractor.extract_core_entities("Test transcript")


class TestExtractDetailedAnalysis:
    """Tests for extract_detailed_analysis method."""

    def test_extract_detailed_analysis_success(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test successful detailed analysis extraction."""
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text=json.dumps({
            "methods_techniques": [],
            "mathematical_notation": [],
            "equations": [],
            "tools_resources": [],
            "research_problems": [],
            "applications": []
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_detailed_analysis("Test transcript")

        assert isinstance(result, DetailedAnalysis)

    def test_extract_detailed_analysis_with_data(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test detailed extraction returns populated data."""
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text=json.dumps({
            "methods_techniques": [
                {
                    "name": "Variational Inference",
                    "description": "A method for approximating intractable integrals"
                }
            ],
            "mathematical_notation": [],
            "equations": [],
            "tools_resources": [
                {
                    "name": "pymdp",
                    "type": "library",
                    "purpose": "Active Inference in Python"
                }
            ],
            "research_problems": [],
            "applications": []
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_detailed_analysis("Test transcript")

        assert len(result.methods_techniques) == 1
        assert result.methods_techniques[0].name == "Variational Inference"
        assert len(result.tools_resources) == 1


class TestExtractComplete:
    """Tests for extract_complete method."""

    def test_extract_complete_with_detailed(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test complete extraction includes both core and detailed."""
        mock_response_core = MagicMock()
        mock_response_core.message.content = [MagicMock(text=json.dumps({
            "concepts": [],
            "researchers": [],
            "citations": [],
            "technical_terms": [],
            "key_insights": []
        }))]

        mock_response_detailed = MagicMock()
        mock_response_detailed.message.content = [MagicMock(text=json.dumps({
            "methods_techniques": [],
            "mathematical_notation": [],
            "equations": [],
            "tools_resources": [],
            "research_problems": [],
            "applications": []
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.side_effect = [mock_response_core, mock_response_detailed]
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_complete("Test transcript", transcript_id="test-123")

        assert result.core is not None
        assert result.detailed is not None
        assert result.transcript_id == "test-123"
        assert mock_client_instance.chat.call_count == 2

    def test_extract_complete_without_detailed(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test complete extraction can skip detailed analysis."""
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text=json.dumps({
            "concepts": [],
            "researchers": [],
            "citations": [],
            "technical_terms": [],
            "key_insights": []
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_complete("Test", include_detailed=False)

        assert result.core is not None
        assert result.detailed is None
        assert mock_client_instance.chat.call_count == 1


class TestBackwardCompatibility:
    """Tests for deprecated backward compatibility methods."""

    def test_extract_entities_calls_core_entities(self, mock_settings, mock_cohere_client, mock_schemas):
        """Test deprecated extract_entities calls extract_core_entities."""
        mock_response = MagicMock()
        mock_response.message.content = [MagicMock(text=json.dumps({
            "concepts": [],
            "researchers": [],
            "citations": [],
            "technical_terms": [],
            "key_insights": []
        }))]

        mock_client_instance = MagicMock()
        mock_client_instance.chat.return_value = mock_response
        mock_cohere_client.return_value = mock_client_instance

        extractor = CohereExtractor()
        result = extractor.extract_entities("Test")

        assert isinstance(result, CoreEntities)
