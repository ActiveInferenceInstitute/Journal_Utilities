# Writing the ActiveInferenceJournal corpus

The schema belongs to ActiveInferenceJournal, not this pipeline repository:

- [Canonical schema prose](https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/blob/main/docs/SCHEMA.md)
  defines the folder layout, metadata and raw-versus-derived transcript layers.
- [Publishing contract](https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/blob/main/docs/workflows/publishing.md)
  defines cross-repository identity and joins.
- [Pinned identity schema](workflows/record-identity.schema.json) is copied unchanged
  from the lead and checked by the [local Publishing integration](workflows/publishing.md).

Do not maintain a second schema definition here. The following chapters describe
how Journal-Utilities writes and checks the corpus.

## How the pipeline writes this

`scripts/enrich_metadata.py` owns the enrichment operation on `metadata.json` and
keeps URL fields URL-only. Non-URL Coda display text is preserved as `slides_label`
or `paper_title`; placeholder values such as `n/a` are omitted.

The derived indexes are regenerated with:

```bash
python scripts/generate_journal_indexes.py --journal ../ActiveInferenceJournal
python scripts/generate_journal_indexes.py --journal ../ActiveInferenceJournal --check
```

`scripts/repair_split_transcripts.py` repairs derived split-session outputs when
source session pairs are present. Identity and transcript structure are defined
by the canonical documents linked above, not by filenames in this repository.

## Reproducible maintenance sequence

Run the stages from the Journal-Utilities checkout with the sibling journal path
explicitly named:

```bash
# 1. Preview enrichment; add --apply only after reviewing the report.
python scripts/enrich_metadata.py --journal ../ActiveInferenceJournal
python scripts/enrich_metadata.py --journal ../ActiveInferenceJournal --apply

# 2. Rebuild complete split-session artifacts and derived indexes.
python scripts/repair_split_transcripts.py \
  --journal ../ActiveInferenceJournal --utilities .
python scripts/generate_journal_indexes.py --journal ../ActiveInferenceJournal

# 3. Read-only release gate.
python scripts/validate_journal.py \
  --journal ../ActiveInferenceJournal \
  --manifest data/output/channel_videos.json
```

The final gate is deliberately non-mutating. It verifies that metadata remains
the source of truth for both indexes, every duplicate target exists, canonical
video IDs are unique, split transcript records have stable identities, manifest
coverage has no missing videos, enrichment URL fields contain real URLs, and
the journal `main` checkout contains neither credentials nor audio. Use
`--strict-manifest` when the manifest has just been freshly enumerated and
canonical extras must also fail the check.

