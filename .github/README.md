# .github — CI, dependency updates, and GNN conformance

GitHub configuration for `ActiveInferenceInstitute/Journal_Utilities`. Nothing here
is part of the Python package; it governs automation only.

## Contents

| Path | Purpose |
| --- | --- |
| `workflows/test.yml` | Job `gate` (`Gate (lint · format · types · tests · docs)`) runs `run.py gate lint format types test docs` after one locked sync; job `gnn-conformance` (`gnn conformance (pinned)`) runs `run.py gate gnn` without a project sync. |
| `workflows/artifact-guard.yml` | Job `no-tracked-artifacts`: fails a push/PR that tracks generated or OS artifacts (`*.log`, `*.part`, `*.ytdl`, `.DS_Store`). |
| `dependabot.yml` | Weekly grouped updates for GitHub Actions and `uv` Python dependencies (`cooldown` 7 days). |
| `gnn-pin.json` | Pin document, schema `gnn-importer-pin/v1`: `ActiveInferenceInstitute/Generalized_Notation_Notation` at `v5.0.3` (`8f293d9…`). |
| `GNN.md` | What the conformance job proves (pin + parser check over every `*.gnn.md` sketch, or the pinned exemplar when the tree has none). |

## Local checks

The workflows do not restate any gate command: both `test.yml` jobs call
`uv run python run.py gate …`, the same entry point a contributor uses
([`../docs/RUN_GUIDE.md`](../docs/RUN_GUIDE.md)). `actionlint .github/workflows/*.yml`
lints the workflow files themselves; the gate commands are the repository commands in
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).

Setup actions are pinned by commit: `actions/checkout@3d3c42e5…` (v7.0.1) and
`astral-sh/setup-uv@68559e99…` (v10.3.3, caching enabled). This repository does not
use a composite `setup-python-uv` action.

Do not weaken, rename or reorder required checks, and do not edit `action` pins
or the Dependabot schedule as part of a documentation change.
