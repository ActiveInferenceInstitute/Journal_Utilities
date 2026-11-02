"""Tests for Active Inference entity models."""

import pytest
from pydantic import ValidationError

from journal_utilities.rag.models import (
    Application,
    ApplicationStatus,
    Citation,
    CitationType,
    Concept,
    ConceptCategory,
    CoreEntities,
    DetailedAnalysis,
    Equation,
    ExtractedEntities,
    MathematicalNotation,
    MethodTechnique,
    Researcher,
    ResearcherRole,
    ResearchProblem,
    ResourceType,
    TechnicalTerm,
    TermDomain,
    ToolResource,
)


def test_concept_creation(sample_concept: Concept) -> None:
    """Test creating a concept."""
    assert sample_concept.name == "Free Energy Principle"
    assert sample_concept.category == ConceptCategory.THEORETICAL
    assert len(sample_concept.related_concepts) == 2
    assert "Active Inference" in sample_concept.related_concepts


def test_concept_validation() -> None:
    """Test concept validation requires all required fields."""
    with pytest.raises(ValidationError):
        Concept(
            name="Test",
            # Missing required fields: definition, category
        )


def test_researcher_creation(sample_researcher: Researcher) -> None:
    """Test creating a researcher."""
    assert sample_researcher.name == "Karl Friston"
    assert sample_researcher.affiliation == "University College London"
    assert sample_researcher.role == ResearcherRole.CITED_AUTHOR


def test_researcher_role_enum() -> None:
    """Test researcher role enum validation."""
    valid_roles = [
        ResearcherRole.COLLABORATOR,
        ResearcherRole.CITED_AUTHOR,
        ResearcherRole.MENTIONED,
        ResearcherRole.SPEAKER,
        ResearcherRole.ADVISOR,
    ]
    for role in valid_roles:
        researcher = Researcher(name="Test", role=role)
        assert researcher.role in valid_roles


def test_citation_creation(sample_citation: Citation) -> None:
    """Test creating a citation."""
    assert sample_citation.type == CitationType.PAPER
    assert sample_citation.title == "The Free Energy Principle: A Unified Brain Theory?"
    assert len(sample_citation.authors) == 1
    assert sample_citation.year == 2010


def test_citation_url_validation() -> None:
    """Test citation URL handling."""
    # Valid URL - accepted
    citation = Citation(
        type=CitationType.PAPER,
        title="Test Paper",
        url="https://example.com/paper.pdf",
    )
    assert citation.url == "https://example.com/paper.pdf"

    # URL can be None
    citation_no_url = Citation(
        type=CitationType.PAPER,
        title="Test Paper",
        url=None,
    )
    assert citation_no_url.url is None

    # Any string is accepted (validation happens at API level via schema description)
    citation_any_string = Citation(
        type=CitationType.PAPER,
        title="Test Paper",
        url="not-a-valid-url",  # Accepted as string, but API guided to provide valid URLs
    )
    assert citation_any_string.url == "not-a-valid-url"


def test_technical_term_creation(sample_technical_term: TechnicalTerm) -> None:
    """Test creating a technical term."""
    assert sample_technical_term.term == "Variational Free Energy"
    assert sample_technical_term.domain == TermDomain.MATHEMATICS
    assert len(sample_technical_term.synonyms) == 2


def test_core_entities_creation(sample_core_entities: CoreEntities) -> None:
    """Test creating core entities container."""
    assert len(sample_core_entities.concepts) == 2
    assert len(sample_core_entities.researchers) == 2
    assert len(sample_core_entities.citations) == 1
    assert len(sample_core_entities.technical_terms) == 1
    assert len(sample_core_entities.key_insights) == 2


def test_core_entities_json_serialization(sample_core_entities: CoreEntities) -> None:
    """Test JSON serialization of core entities."""
    # Export to JSON
    json_str = sample_core_entities.model_dump_json()
    assert isinstance(json_str, str)
    assert "Active Inference" in json_str

    # Parse back from JSON
    parsed = CoreEntities.model_validate_json(json_str)
    assert parsed.concepts[0].name == sample_core_entities.concepts[0].name


def test_method_technique_creation() -> None:
    """Test creating a method/technique."""
    method = MethodTechnique(
        name="Variational Inference",
        description="A method for approximating intractable Bayesian inference",
        application="Used in active inference for belief updating",
    )
    assert method.name == "Variational Inference"
    assert method.application is not None


def test_mathematical_notation_creation() -> None:
    """Test creating mathematical notation."""
    notation = MathematicalNotation(
        notation="F",
        meaning="Variational Free Energy",
        context="Used to quantify surprise in active inference",
    )
    assert notation.notation == "F"
    assert notation.meaning == "Variational Free Energy"


def test_equation_creation() -> None:
    """Test creating an equation."""
    equation = Equation(
        name="Free Energy",
        formula="F = E_q[ln q(x) - ln p(x,y)]",
        context="Fundamental equation in active inference",
    )
    assert equation.formula == "F = E_q[ln q(x) - ln p(x,y)]"


def test_tool_resource_creation() -> None:
    """Test creating a tool/resource."""
    tool = ToolResource(
        name="PyMDP",
        type=ResourceType.LIBRARY,
        url="https://github.com/infer-actively/pymdp",
        purpose="Python library for active inference",
    )
    assert tool.name == "PyMDP"
    assert tool.type == ResourceType.LIBRARY


def test_research_problem_creation() -> None:
    """Test creating a research problem."""
    problem = ResearchProblem(
        problem="How to scale active inference to complex environments",
        current_approaches=["Hierarchical models", "Deep active inference"],
        proposed_solution="Use of structured generative models",
    )
    assert problem.problem.startswith("How to scale")
    assert len(problem.current_approaches) == 2


def test_application_creation() -> None:
    """Test creating an application."""
    app = Application(
        domain="Robotics",
        description="Using active inference for robotic control",
        status=ApplicationStatus.DEMONSTRATED,
    )
    assert app.domain == "Robotics"
    assert app.status == ApplicationStatus.DEMONSTRATED


def test_detailed_analysis_creation() -> None:
    """Test creating detailed analysis container."""
    analysis = DetailedAnalysis(
        methods_techniques=[
            MethodTechnique(
                name="Message Passing",
                description="Algorithm for belief propagation",
            )
        ],
        equations=[Equation(formula="F = E_q[ln q(x) - ln p(x,y)]")],
    )
    assert len(analysis.methods_techniques) == 1
    assert len(analysis.equations) == 1


def test_extracted_entities_creation(sample_core_entities: CoreEntities) -> None:
    """Test creating complete extraction result."""
    extracted = ExtractedEntities(
        core=sample_core_entities,
        transcript_id="test-001",
    )
    assert extracted.transcript_id == "test-001"
    assert extracted.core == sample_core_entities
    assert extracted.detailed is None
    assert extracted.extracted_at is not None


def test_extracted_entities_with_detailed() -> None:
    """Test extraction with both core and detailed analysis."""
    core = CoreEntities(
        concepts=[
            Concept(
                name="Test Concept",
                definition="A test",
                category=ConceptCategory.THEORETICAL,
            )
        ],
        researchers=[],
        technical_terms=[],
    )

    detailed = DetailedAnalysis(
        methods_techniques=[MethodTechnique(name="Test Method", description="A test method")],
    )

    extracted = ExtractedEntities(
        core=core,
        detailed=detailed,
        transcript_id="test-002",
    )

    assert extracted.core.concepts[0].name == "Test Concept"
    assert extracted.detailed is not None
    assert len(extracted.detailed.methods_techniques) == 1


def test_extracted_entities_export_to_dict(sample_core_entities: CoreEntities) -> None:
    """Test exporting extraction to dictionary."""
    extracted = ExtractedEntities(
        core=sample_core_entities,
        transcript_id="test-003",
    )

    data = extracted.model_dump()
    assert isinstance(data, dict)
    assert "core" in data
    assert "transcript_id" in data
    assert data["transcript_id"] == "test-003"
