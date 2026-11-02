"""Entity and relationship models for Active Inference transcript extraction."""

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ============================================================================
# Core Schema Models
# ============================================================================


class ConceptCategory(str, Enum):
    """Categories for concepts."""

    THEORETICAL = "theoretical"
    MATHEMATICAL = "mathematical"
    COMPUTATIONAL = "computational"
    NEUROSCIENCE = "neuroscience"
    PHILOSOPHY = "philosophy"
    METHODOLOGY = "methodology"


class Concept(BaseModel):
    """A concept, theory, or framework discussed in the transcript."""

    name: str = Field(..., description="Name of the concept")
    definition: str = Field(..., description="Definition or explanation provided")
    category: ConceptCategory = Field(..., description="Category of the concept")
    related_concepts: Sequence[str] = Field(
        default_factory=list, description="Names of related concepts mentioned"
    )


class ResearcherRole(str, Enum):
    """Role of a researcher in relation to the presentation."""

    COLLABORATOR = "collaborator"
    CITED_AUTHOR = "cited_author"
    MENTIONED = "mentioned"
    SPEAKER = "speaker"
    ADVISOR = "advisor"


class Researcher(BaseModel):
    """A researcher, scientist, or scholar mentioned in the transcript."""

    name: str = Field(..., description="Full name of the researcher")
    affiliation: str | None = Field(
        None, description="Institution or organization (omit if unknown)"
    )
    role: ResearcherRole = Field(..., description="Role in relation to the presentation")
    contribution: str | None = Field(
        None, description="Their contribution or relevance to the discussion"
    )


class CitationType(str, Enum):
    """Type of academic citation."""

    PAPER = "paper"
    BOOK = "book"
    WORKSHOP = "workshop"
    CONFERENCE = "conference"
    PREPRINT = "preprint"
    THESIS = "thesis"


class Citation(BaseModel):
    """A paper, book, or other work cited or referenced."""

    type: CitationType = Field(..., description="Type of citation")
    title: str = Field(..., description="Title of the work")
    authors: Sequence[str] = Field(default_factory=list, description="Authors if mentioned")
    venue: str | None = Field(None, description="Publication venue (journal, conference, etc.)")
    year: int | None = Field(None, description="Year of publication if mentioned")
    url: str | None = Field(None, description="URL if explicitly mentioned")
    context: str | None = Field(None, description="Brief context of how it was referenced")


class TermDomain(str, Enum):
    """Domain that a technical term belongs to."""

    MATHEMATICS = "mathematics"
    NEUROSCIENCE = "neuroscience"
    MACHINE_LEARNING = "machine_learning"
    PHYSICS = "physics"
    STATISTICS = "statistics"
    BIOLOGY = "biology"


class TechnicalTerm(BaseModel):
    """A technical term with explanation."""

    term: str = Field(..., description="The technical term")
    explanation: str = Field(..., description="Explanation or definition provided")
    domain: TermDomain = Field(..., description="Domain the term belongs to")
    synonyms: Sequence[str] = Field(
        default_factory=list, description="Alternative terms or synonyms mentioned"
    )


class CoreEntities(BaseModel):
    """Core entities extracted from an Active Inference transcript."""

    concepts: Sequence[Concept] = Field(
        default_factory=list, description="Main concepts, theories, or frameworks discussed"
    )
    researchers: Sequence[Researcher] = Field(
        default_factory=list, description="Key researchers, scientists, or scholars mentioned"
    )
    citations: Sequence[Citation] = Field(
        default_factory=list,
        description="Papers, books, or other works cited or referenced",
    )
    technical_terms: Sequence[TechnicalTerm] = Field(
        default_factory=list,
        description="Technical terminology with explanations",
    )
    key_insights: Sequence[str] = Field(
        default_factory=list,
        description="Main takeaways or key insights from the presentation",
    )


# ============================================================================
# Detailed Schema Models
# ============================================================================


class MethodTechnique(BaseModel):
    """A methodology, algorithm, or technique discussed."""

    name: str = Field(..., description="Name of the method or technique")
    description: str = Field(..., description="Description of the method")
    application: str | None = Field(None, description="How or where it's applied")
    implementation: str | None = Field(None, description="Implementation details if mentioned")


class MathematicalNotation(BaseModel):
    """Mathematical symbols and notation explained."""

    notation: str = Field(..., description="The mathematical notation or symbol")
    meaning: str = Field(..., description="What it represents")
    context: str | None = Field(None, description="Context in which it's used")


class Equation(BaseModel):
    """A key equation explicitly discussed."""

    name: str | None = Field(None, description="Name or description of the equation")
    formula: str = Field(..., description="The equation itself (plain text or LaTeX)")
    context: str | None = Field(None, description="Where/how this equation is used")


class ResourceType(str, Enum):
    """Type of tool or resource."""

    SOFTWARE = "software"
    LIBRARY = "library"
    FRAMEWORK = "framework"
    DATASET = "dataset"
    REPOSITORY = "repository"
    DOCUMENTATION = "documentation"
    PLATFORM = "platform"


class ToolResource(BaseModel):
    """Software, library, dataset, or other resource mentioned."""

    name: str = Field(..., description="Name of the tool or resource")
    type: ResourceType = Field(..., description="Type of resource")
    url: str | None = Field(None, description="URL if explicitly mentioned")
    purpose: str | None = Field(None, description="Purpose or use case")


class ResearchProblem(BaseModel):
    """A research problem, challenge, or open question discussed."""

    problem: str = Field(..., description="Description of the problem")
    current_approaches: Sequence[str] = Field(
        default_factory=list, description="Current approaches to addressing it"
    )
    proposed_solution: str | None = Field(None, description="Solution proposed in the presentation")


class ApplicationStatus(str, Enum):
    """Status of an application."""

    PROPOSED = "proposed"
    IN_DEVELOPMENT = "in_development"
    DEMONSTRATED = "demonstrated"


class Application(BaseModel):
    """A real-world application or use case mentioned."""

    domain: str = Field(..., description="Application domain (e.g., robotics, neuroscience, AI)")
    description: str = Field(..., description="Description of the application")
    status: ApplicationStatus = Field(..., description="Status of the application")


class DetailedAnalysis(BaseModel):
    """Detailed technical analysis from an Active Inference transcript."""

    methods_techniques: Sequence[MethodTechnique] = Field(
        default_factory=list,
        description="Methodologies, algorithms, or techniques discussed in detail",
    )
    mathematical_notation: Sequence[MathematicalNotation] = Field(
        default_factory=list,
        description="Important mathematical symbols and notation explained",
    )
    equations: Sequence[Equation] = Field(
        default_factory=list,
        description="Key equations explicitly discussed",
    )
    tools_resources: Sequence[ToolResource] = Field(
        default_factory=list,
        description="Software, libraries, datasets, or other resources mentioned",
    )
    research_problems: Sequence[ResearchProblem] = Field(
        default_factory=list,
        description="Research problems, challenges, or open questions discussed",
    )
    applications: Sequence[Application] = Field(
        default_factory=list,
        description="Real-world applications or use cases mentioned",
    )


# ============================================================================
# Combined Extraction Result
# ============================================================================


class ExtractedEntities(BaseModel):
    """Complete extraction result combining core and detailed entities."""

    core: CoreEntities
    detailed: DetailedAnalysis | None = None
    transcript_id: str | None = None
    extracted_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Simple Storage Models (for DB compatibility)
# ============================================================================


class Transcript(BaseModel):
    """Transcript metadata and content."""

    title: str = Field(..., description="Title of the transcript")
    date: datetime = Field(..., description="Date of the transcript/presentation")
    content: str = Field(..., description="Full transcript text content")
    source: str = Field(..., description="Source path or URL of the transcript")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    processed: bool = Field(default=False, description="Whether entities have been extracted")
    created_at: datetime = Field(
        default_factory=datetime.now, description="When record was created"
    )


class Entity(BaseModel):
    """Simple generic entity for database storage."""

    name: str = Field(..., description="Entity name")
    type: str = Field(..., description="Entity type (concept, researcher, citation, etc.)")
    description: str = Field(default="", description="Description or definition")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")
    mentions: int = Field(default=1, ge=1, description="Number of mentions")
    context: Sequence[str] = Field(default_factory=list, description="Context snippets")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class Relationship(BaseModel):
    """Simple generic relationship for database storage."""

    source: str = Field(..., description="Source entity name")
    target: str = Field(..., description="Target entity name")
    relationship_type: str = Field(..., description="Type of relationship")
    description: str = Field(default="", description="Description of the relationship")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score")
    context: str = Field(default="", description="Context where relationship was identified")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
