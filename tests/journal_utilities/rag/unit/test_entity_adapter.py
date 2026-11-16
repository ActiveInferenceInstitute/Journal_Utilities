"""
Unit tests for EntityAdapter conversion functions.
"""

import pytest
from pydantic import ValidationError

from journal_utilities.rag.adapters.entity_adapter import EntityAdapter
from journal_utilities.rag.models import Entity
from journal_utilities.rag.models.entities import (
    Citation,
    CitationType,
    Concept,
    ConceptCategory,
    CoreEntities,
    Researcher,
    ResearcherRole,
    TechnicalTerm,
    TermDomain,
)


class TestConvertCoreEntities:
    """Tests for EntityAdapter.convert_core_entities method."""

    def test_convert_empty_entities(self):
        """Test converting empty core entities."""
        core = CoreEntities(
            concepts=[], researchers=[], citations=[], technical_terms=[], key_insights=[]
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        assert len(entities) == 0

    def test_convert_concepts(self):
        """Test converting concepts to entities."""
        core = CoreEntities(
            concepts=[
                Concept(
                    name="Active Inference",
                    definition="A framework for understanding brain function",
                    category=ConceptCategory.THEORETICAL,
                    related_concepts=["Free Energy"],
                )
            ],
            researchers=[],
            citations=[],
            technical_terms=[],
            key_insights=[],
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        assert len(entities) >= 1
        concept_entity = next((e for e in entities if e.name == "Active Inference"), None)
        assert concept_entity is not None
        assert concept_entity.type == "concept"

    def test_convert_researchers(self):
        """Test converting researchers to entities."""
        core = CoreEntities(
            concepts=[],
            researchers=[
                Researcher(name="Karl Friston", role=ResearcherRole.CITED_AUTHOR, affiliation="UCL")
            ],
            citations=[],
            technical_terms=[],
            key_insights=[],
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        assert len(entities) >= 1
        researcher_entity = next((e for e in entities if e.name == "Karl Friston"), None)
        assert researcher_entity is not None
        assert researcher_entity.type == "researcher"

    def test_convert_citations(self):
        """Test converting citations to entities."""
        core = CoreEntities(
            concepts=[],
            researchers=[],
            citations=[
                Citation(
                    title="The Free Energy Principle",
                    type=CitationType.PAPER,
                    authors=["Friston, K."],
                    year=2010,
                )
            ],
            technical_terms=[],
            key_insights=[],
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        assert len(entities) >= 1
        citation_entity = next((e for e in entities if "Free Energy Principle" in e.name), None)
        assert citation_entity is not None
        assert citation_entity.type == "citation"

    def test_convert_technical_terms(self):
        """Test converting technical terms to entities."""
        core = CoreEntities(
            concepts=[],
            researchers=[],
            citations=[],
            technical_terms=[
                TechnicalTerm(
                    term="Variational Free Energy",
                    explanation="A bound on surprise",
                    domain=TermDomain.MATHEMATICS,
                )
            ],
            key_insights=[],
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        assert len(entities) >= 1
        term_entity = next((e for e in entities if e.name == "Variational Free Energy"), None)
        assert term_entity is not None
        assert term_entity.type == "technical_term"

    def test_convert_key_insights(self):
        """Test converting key insights to entities."""
        core = CoreEntities(
            concepts=[],
            researchers=[],
            citations=[],
            technical_terms=[],
            key_insights=["Active Inference unifies perception and action"],
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        assert len(entities) >= 1
        # The adapter names insights as "Insight 1", "Insight 2", etc.
        insight_entity = next((e for e in entities if e.name == "Insight 1"), None)
        assert insight_entity is not None
        assert insight_entity.type == "key_insight"
        # The insight content is in the description
        assert "Active Inference unifies" in insight_entity.description

    def test_convert_all_types(self):
        """Test converting all entity types together."""
        core = CoreEntities(
            concepts=[
                Concept(name="Concept1", definition="Def1", category=ConceptCategory.THEORETICAL)
            ],
            researchers=[Researcher(name="Researcher1", role=ResearcherRole.SPEAKER)],
            citations=[
                Citation(title="Citation1", authors=["A"], year=2020, type=CitationType.PAPER)
            ],
            technical_terms=[
                TechnicalTerm(term="Term1", explanation="Exp1", domain=TermDomain.NEUROSCIENCE)
            ],
            key_insights=["Insight1"],
        )

        entities = EntityAdapter.convert_core_entities(core, source="transcripts/a.txt")

        # Should have at least 5 entities (one of each type)
        assert len(entities) >= 5

        types = {e.type for e in entities}
        assert "concept" in types
        assert "researcher" in types
        assert "citation" in types
        assert "technical_term" in types
        assert "key_insight" in types


class TestExtractRelationships:
    """Tests for EntityAdapter.extract_relationships method."""

    def test_extract_relationships_empty(self):
        """Test extracting relationships from empty entities."""
        core = CoreEntities(
            concepts=[], researchers=[], citations=[], technical_terms=[], key_insights=[]
        )

        relationships = EntityAdapter.extract_relationships(core, source="transcripts/a.txt")

        assert len(relationships) == 0

    def test_extract_relationships_from_concepts(self):
        """Test extracting relationships from concepts with related_concepts."""
        core = CoreEntities(
            concepts=[
                Concept(
                    name="Active Inference",
                    definition="Test",
                    category=ConceptCategory.THEORETICAL,
                    related_concepts=["Free Energy", "Perception"],
                )
            ],
            researchers=[],
            citations=[],
            technical_terms=[],
            key_insights=[],
        )

        relationships = EntityAdapter.extract_relationships(core, source="transcripts/a.txt")

        # Should have 2 relationships from related_concepts
        assert len(relationships) >= 2


class TestEntityModel:
    """Tests for the Entity model itself."""

    def test_entity_creation(self):
        """Test basic entity creation."""
        entity = Entity(
            source="transcripts/a.txt",
            name="Test Entity",
            type="concept",
            description="A test",
            confidence=0.95,
            mentions=3,
            context=["ctx1", "ctx2"],
        )

        assert entity.name == "Test Entity"
        assert entity.type == "concept"
        assert entity.confidence == 0.95
        assert entity.mentions == 3
        assert len(entity.context) == 2

    @pytest.mark.parametrize("source", [None, "", "   "])
    def test_entity_requires_trusted_source(self, source):
        with pytest.raises(ValidationError):
            Entity(name="Insight 1", type="key_insight", source=source)

    def test_entity_with_metadata(self):
        """Test entity with custom metadata."""
        entity = Entity(
            source="transcripts/a.txt",
            name="Test",
            type="concept",
            confidence=0.9,
            mentions=1,
            context=["test"],
            metadata={"source": "transcript", "importance": "high"},
        )

        assert entity.metadata["source"] == "transcript"
        assert entity.metadata["importance"] == "high"


def test_caller_source_overrides_extraction_metadata(sample_core_entities):
    from journal_utilities.rag.models import ExtractedEntities

    extracted = ExtractedEntities(core=sample_core_entities, metadata={"source": "untrusted"})
    entities, relationships = EntityAdapter.convert_extracted_entities(extracted, source="trusted.txt")
    assert {entity.source for entity in entities} == {"trusted.txt"}
    assert {relationship.transcript_source for relationship in relationships} == {"trusted.txt"}
    assert {(relationship.source_type, relationship.target_type) for relationship in relationships} == {
        ("researcher", "citation")
    }
