# .github — CI, dependency updates, and GNN conformance

GitHub configuration for `ActiveInferenceInstitute/Journal_Utilities`. Nothing here
is part of the Python package; it governs automation only.

## Contents

| Path | Purpose |
| --- | --- |
| `workflows/test.yml` | Required `test` job: pytest, `ruff check src/ tests/ scripts/`, `ruff format --check`, `mypy src`, and the read-only `scripts/validate_journal.py` gate. Also defines the `gnn conformance (pinned)` job. |
| `workflows/artifact-guard.yml` | Fails a push/PR that adds build artifacts (`__pycache__`, `*.pyc`, `.DS_Store`, caches) to the tree. |
| `dependabot.yml` | Weekly grouped updates for GitHub Actions and `uv` Python dependencies (`cooldown` 7 days). |
| `gnn-pin.json` | Pins `ActiveInferenceInstitute/Generalized_Notation_Notation` at `v5.0.3` (`8f293d9…`) for the GNN conformance job. |
| `GNN.md` | What the GNN conformance job proves (pin + parser check over every `*.gnn.md` sketch). |

## Local checks

`actionlint .github/workflows/*.yml` lints the workflows. The other gates are the
repository commands in [`../CONTRIBUTING.md`](../CONTRIBUTING.md); there is no
local runner that reproduces GitHub's hosted jobs exactly, so treat the workflow
files as the source of truth for CI.

Do not weaken, rename or reorder required checks, and do not edit `action` pins
or the Dependabot schedule as part of a documentation change.
