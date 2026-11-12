# Publishing — Journal_Utilities integration

The [lead Publishing contract](https://github.com/ActiveInferenceInstitute/ActiveInferenceJournal/blob/main/docs/workflows/publishing.md)
is authoritative. This member follows its migration step without changing the schema
or migrating another repository.

## Member facts

- Gate: `uv run python run.py gate <arm>`, with `lint`, `format`, `types`, `test`,
  `test-full`, `docs` and `gnn` defined in [`run.py`](../../run.py).
- Docs index: [`docs/documentation-index.md`](../documentation-index.md).
- Manuscript command: none.
- GNN pin: [`.github/gnn-pin.json`](../../.github/gnn-pin.json); its existing `gnn`
  arm remains authoritative.

[`.aii/config.yaml`](../../.aii/config.yaml) records a task for each documented arm,
uses the gate entry point, and replaces the missing integration-doc path with the
docs index. The docs task records the absence of a manuscript command; the GNN task
points to the existing pin.

## Canonical copies and drift checks

The following artifacts are copied byte-for-byte from ActiveInferenceJournal commit
`d8ec888a8f3051a66bed9af047ee4b206050bdce`. These are upstream copies, not member-owned
implementations; update them together with these digests, never edit their grammar
or reformat the Python copies locally.

```text
record-identity.schema.json  84f6c4df6efc3f15f0d8a9a05c8aabd0cbdc08b0f4feac5fcc8ae860a81e306b
identity.py  847328ff163fa90c869495164869caf4e83313748e8a444dbab8d4e459b11074
identity_selftest.py  bf029061b62c0b1d0275d71126fc7f962242ee7d32847958dc481fc2877fbe49
```

The existing `docs` arm calls [`scripts/gate/check_docs.py`](../../scripts/gate/check_docs.py).
It retains the member's link and index checker, then runs the lead's
[`identity.py`](../../scripts/gate/identity.py) to load the
[unchanged schema](record-identity.schema.json) and verify this digest block.
It also runs the exact member-copy checks specified by the lead:

```bash
python3 scripts/gate/identity.py --verify-copy docs/workflows/record-identity.schema.json
python3 scripts/gate/identity.py --verify-copy scripts/gate/identity.py
python3 scripts/gate/identity.py --verify-copy scripts/gate/identity_selftest.py
```

The copied [lead selftest](../../scripts/gate/identity_selftest.py) proves that a
matching Python copy passes and a diverged copy fails. All identity checks use only
the standard library and require neither network access nor a JSON Schema package.

The lead contract says to keep checks the member already proves rather than
adding duplicates. The member's gate registry, relative-link/index checks,
measurement generator and GNN wrapper therefore remain in place; no lead-specific
CLI, corpus scan or measurement pipeline is transplanted. The raw transcript
validator also remains authoritative for its existing checks.

## Schema ownership

[`JOURNAL_SCHEMA.md`](../JOURNAL_SCHEMA.md) now points to the lead for schema and
identity definitions and retains only the pipeline writing and maintenance
instructions. It is no longer a prose mirror.

## Local verification

Run `uv run python run.py gate docs` and `uv run python run.py gate test`.
The documented `test-full` arm adds coverage and attempts live downloads. The `test`
arm sets `CI=true`, but its channel and playlist enumeration tests still call
YouTube. An offline sandbox cannot certify either arm's live-network behavior.
GitHub Actions is billing-locked; local command output, not hosted job status,
is the gate evidence.
