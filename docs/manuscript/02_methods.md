# Methods

We inspected the documented maintenance sequence alongside the code and entry points pinned in the bibliography. The repository's schema guide identifies `scripts/enrich_metadata.py` as the metadata enrichment owner. `scripts/repair_split_transcripts.py` handles derived session consolidation, `scripts/generate_journal_indexes.py` regenerates indexes, and `scripts/validate_journal.py` checks consistency without modifying the corpus.

The analysis traced three classes of output: data held for an operator, curated corpus records, and user-facing renderings. We read the privacy and YouTube integration contracts to identify boundaries for media, publishing credentials and final write-back. This method requires no API credentials or hosted changes.
