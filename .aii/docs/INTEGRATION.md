# InstituteOS integration — Journal-Utilities

## Identity

| Field | Value |
| --- | --- |
| Repository | `ActiveInferenceInstitute/Journal_Utilities` |
| Affiliation | `institute` |
| Category | `publication` |
| Status | `active` |
| Maturity | `released` |
| Steward | Active Inference Institute |
| Default branch | `main` |
| Current release | — |
| License | `CC0-1.0` |
| Citation | Active Inference Institute — Journal-Utilities. |

## Federation

| Setting | Value |
| --- | --- |
| Dashboard mode | `repos` |
| Analytics | `true` |
| Dashboard | `true` |
| Sync policy | `pull` |
| Registries | — |
| Tags | journal, video-library, transcription, pipeline, python |

## Ecosystem relations

| Repository | Relation | Note |
| --- | --- | --- |
| `ActiveInferenceInstitute/InstituteOS` | `referenced-by` | Federated via the InstituteOS .aii manifest. |
| `ActiveInferenceInstitute/Active_Inference_Ontology` | `references` | Uses Active Inference Ontology terms. |
| `ActiveInferenceInstitute/ActiveInferenceJournal` | `referenced-by` | Featured in Institute materials. |

## Key artifacts

| Path | Kind | Description |
| --- | --- | --- |
| `README.md` | `doc` | Repository overview. |
| `run.py` | `code` | Pipeline CLI runner (config/export/download/serve/test/full/journal-check). |
| `src` | `code` | Source tree. |
| `scripts` | `code` | CLI tools and journal maintenance scripts. |
| `Makefile` | `code` | Convenience targets wrapping the CLIs and gates. |
| `pyproject.toml` | `code` | Python package config. |
| `LICENSE` | `doc` | License. |
| `AGENTS.md` | `doc` | Agent guidance. |
| `CITATION.cff` | `citation` | Machine-readable citation metadata. |
| `tests` | `test` | Test suite. |
| `docs` | `doc` | Documentation tree. |

## Portable tasks

| Task | Command | Working directory | Description |
| --- | --- | --- | --- |
| `lint` | `uv run python run.py gate lint` | `.` | Run the gate linter. |
| `format` | `uv run python run.py gate format` | `.` | Check formatting through the gate. |
| `types` | `uv run python run.py gate types` | `.` | Run the gate type checker. |
| `test` | `uv run python run.py gate test` | `.` | Run the CI test selection. |
| `test-full` | `uv run python run.py gate test-full` | `.` | Run tests with coverage, including reachable live downloads. |
| `docs` | `uv run python run.py gate docs` | `.` | Check docs/documentation-index.md, links and the Publishing pins. No manuscript command. |
| `gnn` | `uv run python run.py gate gnn` | `.` | Check GNN conformance using .github/gnn-pin.json. |

## Validation

```bash
python -m aii_platform.aii_sidecar.validate <repo> --completeness
python -m aii_platform.aii_sidecar docs <repo> --overwrite
python -m aii_platform.aii_sidecar.run <repo> --list
```

The sidecar is valid when `validate` prints `OK` and reports no missing artifact,
manifest, link, or declared-doc path. Completeness is a curation target, not a
runtime requirement.

## Data boundary

This sidecar carries metadata only. It does not grant execution permission, does not
replace the repository's own documentation, and must not be used to move private
content into a public repository. Task execution is limited to trusted checkouts.
