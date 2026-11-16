"""Adapter to convert CoreEntities schema to simple Entity/Relationship models."""

from collections.abc import Sequence

from journal_utilities.rag.models import (
    CoreEntities,
    DetailedAnalysis,
    Entity,
    ExtractedEntities,
    Relationship,
)


class EntityAdapter:
    """Converts CoreEntities to simple Entity and Relationship models for database storage."""

    @staticmethod
    def convert_core_entities(core: CoreEntities, *, source: str) -> Sequence[Entity]:
        """Convert CoreEntities to a flat list of Entity objects.

        Args:
            core: CoreEntities extraction result

        Returns:
            List of Entity objects for database storage
        """
        entities: list[Entity] = []

        # Convert concepts
        for concept in core.concepts:
            entities.append(
                Entity(
                    source=source,
                    name=concept.name,
                    type="concept",
                    description=concept.definition,
                    confidence=1.0,
                    mentions=1,
                    context=[concept.definition],
                    metadata={
                        "category": concept.category.value,
                        "related_concepts": concept.related_concepts,
                    },
                )
            )

        # Convert researchers
        for researcher in core.researchers:
            entities.append(
                Entity(
                    source=source,
                    name=researcher.name,
                    type="researcher",
                    description=researcher.contribution or "",
                    confidence=1.0,
                    mentions=1,
                    context=[researcher.contribution] if researcher.contribution else [],
                    metadata={
                        "affiliation": researcher.affiliation,
                        "role": researcher.role.value,
                    },
                )
            )

        # Convert citations
        for citation in core.citations:
            entities.append(
                Entity(
                    source=source,
                    name=citation.title,
                    type="citation",
                    description=citation.context or "",
                    confidence=1.0,
                    mentions=1,
                    context=[citation.context] if citation.context else [],
                    metadata={
                        "citation_type": citation.type.value,
                        "authors": citation.authors,
                        "venue": citation.venue,
                        "year": citation.year,
                        "url": citation.url or None,  # Convert empty string to None
                    },
                )
            )

        # Convert technical terms
        for term in core.technical_terms:
            entities.append(
                Entity(
                    source=source,
                    name=term.term,
                    type="technical_term",
                    description=term.explanation,
                    confidence=1.0,
                    mentions=1,
                    context=[term.explanation],
                    metadata={
                        "domain": term.domain.value,
                        "synonyms": term.synonyms,
                    },
                )
            )

        # Convert key insights as special entity type
        for idx, insight in enumerate(core.key_insights):
            entities.append(
                Entity(
                    source=source,
                    name=f"Insight {idx + 1}",
                    type="key_insight",
                    description=insight,
                    confidence=1.0,
                    mentions=1,
                    context=[insight],
                    metadata={},
                )
            )

        return entities

    @staticmethod
    def convert_detailed_analysis(detailed: DetailedAnalysis, *, source: str) -> Sequence[Entity]:
        """Convert DetailedAnalysis to a flat list of Entity objects.

        Args:
            detailed: DetailedAnalysis extraction result

        Returns:
            List of Entity objects for database storage
        """
        entities: list[Entity] = []

        # Convert methods/techniques
        for method in detailed.methods_techniques:
            entities.append(
                Entity(
                    source=source,
                    name=method.name,
                    type="method_technique",
                    description=method.description,
                    confidence=1.0,
                    mentions=1,
                    context=[method.description],
                    metadata={
                        "application": method.application,
                        "implementation": method.implementation,
                    },
                )
            )

        # Convert mathematical notation
        for notation in detailed.mathematical_notation:
            entities.append(
                Entity(
                    source=source,
                    name=notation.notation,
                    type="mathematical_notation",
                    description=notation.meaning,
                    confidence=1.0,
                    mentions=1,
                    context=[notation.meaning, notation.context]
                    if notation.context
                    else [notation.meaning],
                    metadata={"context": notation.context},
                )
            )

        # Convert equations
        for equation in detailed.equations:
            entities.append(
                Entity(
                    source=source,
                    name=equation.name or equation.formula[:50],
                    type="equation",
                    description=equation.context or "",
                    confidence=1.0,
                    mentions=1,
                    context=[equation.context] if equation.context else [],
                    metadata={
                        "formula": equation.formula,
                    },
                )
            )

        # Convert tools/resources
        for tool in detailed.tools_resources:
            entities.append(
                Entity(
                    source=source,
                    name=tool.name,
                    type="tool_resource",
                    description=tool.purpose or "",
                    confidence=1.0,
                    mentions=1,
                    context=[tool.purpose] if tool.purpose else [],
                    metadata={
                        "resource_type": tool.type.value,
                        "url": tool.url or None,  # Convert empty string to None
                    },
                )
            )

        # Convert research problems
        for problem in detailed.research_problems:
            entities.append(
                Entity(
                    source=source,
                    name=problem.problem[:100],  # Use first 100 chars as name
                    type="research_problem",
                    description=problem.problem,
                    confidence=1.0,
                    mentions=1,
                    context=[problem.problem],
                    metadata={
                        "current_approaches": problem.current_approaches,
                        "proposed_solution": problem.proposed_solution,
                    },
                )
            )

        # Convert applications
        for application in detailed.applications:
            entities.append(
                Entity(
                    source=source,
                    name=f"{application.domain} Application",
                    type="application",
                    description=application.description,
                    confidence=1.0,
                    mentions=1,
                    context=[application.description],
                    metadata={
                        "domain": application.domain,
                        "status": application.status.value,
                    },
                )
            )

        return entities

    @staticmethod
    def extract_relationships(core: CoreEntities, *, source: str) -> Sequence[Relationship]:
        """Extract relationships from CoreEntities structure.

        Args:
            core: CoreEntities extraction result

        Returns:
            List of Relationship objects derived from the entity structure
        """
        relationships: list[Relationship] = []

        # Extract concept relationships
        for concept in core.concepts:
            for related_concept in concept.related_concepts:
                relationships.append(
                    Relationship(
                        transcript_source=source,
                        source_type="concept",
                        target_type="concept",
                        source=concept.name,
                        target=related_concept,
                        relationship_type="related_to",
                        description=f"{concept.name} is related to {related_concept}",
                        confidence=0.9,
                        context=f"Mentioned in context of {concept.definition[:100]}",
                        metadata={"source_category": concept.category.value},
                    )
                )

        # Extract researcher-citation relationships (implicit)
        # If a researcher's name appears in citation authors, create relationship
        researcher_names = {r.name for r in core.researchers}
        for citation in core.citations:
            for author in citation.authors:
                if author in researcher_names:
                    relationships.append(
                        Relationship(
                            transcript_source=source,
                            source_type="researcher",
                            target_type="citation",
                            source=author,
                            target=citation.title,
                            relationship_type="authored",
                            description=f"{author} authored {citation.title}",
                            confidence=1.0,
                            context=citation.context or "",
                            metadata={"citation_type": citation.type.value},
                        )
                    )

        return relationships

    @classmethod
    def convert_extracted_entities(
        cls, extracted: ExtractedEntities, *, source: str
    ) -> tuple[Sequence[Entity], Sequence[Relationship]]:
        """Use caller-owned provenance, never a scientific extraction's metadata."""
        entities = list(cls.convert_core_entities(extracted.core, source=source))
        if extracted.detailed:
            entities.extend(cls.convert_detailed_analysis(extracted.detailed, source=source))
        relationships = cls.extract_relationships(extracted.core, source=source)
        return entities, relationships
