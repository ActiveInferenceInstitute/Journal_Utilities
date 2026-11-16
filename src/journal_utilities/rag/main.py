"""Select transcript extraction work explicitly; readiness alone is not a run."""

import argparse
import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import structlog

from journal_utilities.rag.adapters.entity_adapter import EntityAdapter
from journal_utilities.rag.extractors.cohere_extractor import CohereExtractor
from journal_utilities.rag.graph.surreal_client import SurrealDBClient
from journal_utilities.rag.models import Transcript
from journal_utilities.rag.settings import settings
from journal_utilities.rag.utils import setup_logging

logger = structlog.get_logger(__name__)


def _date_from_filename(filename: str) -> datetime:
    """Use a valid filename date, otherwise the deterministic unknown-date sentinel."""
    match = re.search(r"(\d{4})[-_/. ](\d{1,2})[-_/. ](\d{1,2})", filename)
    if match:
        try:
            year, month, day = (int(part) for part in match.groups())
            return datetime(year, month, day)
        except ValueError:
            pass
    return datetime.min


def _load_transcript(path: Path, *, source: str) -> Transcript:
    return Transcript(
        title=path.stem,
        date=_date_from_filename(path.name),
        content=path.read_text(encoding="utf-8"),
        source=source,
    )


class JournalRAGPipeline:
    """A transcript is complete only after every required entity and edge persists."""

    def __init__(self) -> None:
        setup_logging(debug=settings.debug)
        # Selection/migration/empty queues must not require or invoke a provider.
        self.extractor: CohereExtractor | None = None
        self.db_client = SurrealDBClient()

    async def connect(self) -> None:
        await self.db_client.connect()

    async def disconnect(self) -> None:
        await self.db_client.disconnect()

    async def process_transcript(self, transcript: Transcript) -> Mapping[str, int]:
        transcript_id = await self.db_client.get_or_create_transcript(transcript)
        await self.db_client.update_transcript_status(transcript_id, processed=False)
        if self.extractor is None:
            self.extractor = CohereExtractor()
        core = self.extractor.extract_core_entities(transcript.content)
        entities = EntityAdapter.convert_core_entities(core, source=transcript.source)
        relationships = EntityAdapter.extract_relationships(core, source=transcript.source)
        identities = {(entity.type, entity.name) for entity in entities}
        for relationship in relationships:
            for identity in (
                (relationship.source_type, relationship.source),
                (relationship.target_type, relationship.target),
            ):
                if identity not in identities:
                    raise ValueError(f"Required relationship endpoint missing: {identity!r}")
        entity_ids = {}
        for entity in entities:
            entity_ids[(entity.type, entity.name)] = await self.db_client.create_entity(entity)
        for relationship in relationships:
            # Returned IDs, not a fresh name-only search, choose the endpoints.
            await self.db_client.create_relationship(
                relationship,
                source_id=entity_ids[(relationship.source_type, relationship.source)],
                target_id=entity_ids[(relationship.target_type, relationship.target)],
            )
        await self.db_client.update_transcript_status(transcript_id, processed=True)
        return {"entities": len(entity_ids), "relationships": len(relationships)}

    async def process_transcript_file(self, file_path: Path) -> Mapping[str, int]:
        return await self.process_transcript(_load_transcript(file_path, source=str(file_path)))

    async def process_from_database(self, base_path: Path | None = None) -> Mapping[str, int]:
        paths = await self.db_client.get_unprocessed_transcript_paths()
        totals = {
            "total": len(paths),
            "processed": 0,
            "failed": 0,
            "total_entities": 0,
            "total_relationships": 0,
        }
        for source in paths:
            path = base_path / source if base_path is not None else Path(source)
            try:
                stats = await self.process_transcript(_load_transcript(path, source=source))
                totals["processed"] += 1
                totals["total_entities"] += stats["entities"]
                totals["total_relationships"] += stats["relationships"]
            except Exception as exc:
                totals["failed"] += 1
                logger.error(
                    "Transcript incomplete; remains pending", source=source, error=str(exc)
                )
        return totals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--file", nargs="+", type=Path, dest="files", help="Extract these transcript files"
    )
    selection.add_argument(
        "--pending", action="store_true", help="Extract pending database source paths"
    )
    selection.add_argument(
        "--migrate-source-identity",
        action="store_true",
        help="Explicit schema migration; quiescent database and backup required; no attribution backfill",
    )
    parser.add_argument("--base-path", type=Path, help="Resolve pending relative source paths here")
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.migrate_source_identity:
        client = SurrealDBClient()
        try:
            await client.connect(migrate_source_identity=True)
            print(json.dumps({"migration": client.migration_summary}))
            return 0
        except Exception as exc:
            logger.error("Source identity migration refused or failed", error=str(exc))
            return 1
        finally:
            await client.disconnect()
    pipeline = JournalRAGPipeline()
    try:
        await pipeline.connect()
        stats: dict[str, int]
        if args.pending:
            stats = dict(await pipeline.process_from_database(base_path=args.base_path))
        else:
            stats = {
                "total": len(args.files),
                "processed": 0,
                "failed": 0,
                "total_entities": 0,
                "total_relationships": 0,
            }
            for path in args.files:
                try:
                    result = await pipeline.process_transcript_file(path)
                    stats["processed"] += 1
                    stats["total_entities"] += result["entities"]
                    stats["total_relationships"] += result["relationships"]
                except Exception as exc:
                    stats["failed"] += 1
                    logger.error("Transcript incomplete", source=str(path), error=str(exc))
        print(json.dumps(stats))
        return 1 if stats["failed"] else 0
    except Exception as exc:
        logger.error("Extraction run failed", error=str(exc))
        return 1
    finally:
        await pipeline.disconnect()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.base_path is not None and not args.pending:
        parser.error("--base-path is only valid with --pending")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
