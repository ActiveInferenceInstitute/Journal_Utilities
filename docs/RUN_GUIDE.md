# Gate and CI run guide

One entry point, one copy of every command:

```bash
uv run python run.py gate [ARM ...]     # default: all arms
uv run python run.py gate report        # measure every arm, rewrite docs/_generated/gate-arms.md
```

The arms are defined once, in `gate_commands()` in [`../run.py`](../run.py). CI calls
that same table (`.github/workflows/test.yml`), so a contributor and a hosted runner
run the same argv. Nothing in this file is a second definition; if an arm changes,
the table changes and this page follows.

## Environment

The suite imports the `rag`, `interface`, and `export` extras (Cohere/SurrealDB,
FastAPI/uvicorn, fpdf2) and the dev tools. The Apple-Silicon and GPU transcription
extras are imported lazily and are not needed for any arm:

```bash
uv sync --frozen --extra rag --extra interface --extra export --dev
```

`run.py gate` resolves the interpreter itself: the project `.venv` when it exists,
otherwise the running interpreter, whose missing toolchain is reported with that
exact sync command instead of a traceback.

## Arms

| Arm | Command | Proves |
| --- | --- | --- |
| `lint` | `ruff check src/ tests/ scripts/` | Ruff rules from `pyproject.toml` |
| `format` | `ruff format --check src/ tests/ scripts/` | Formatting (`ruff format` replaced black) |
| `types` | `mypy src` | Strict typing over the package (per-module overrides documented in `pyproject.toml`) |
| `test` | `pytest tests/ -q` with `CI=true` | The CI selection: same suite, live-network download tests self-skip (see `tests/journal_utilities/test_downloader.py`); counts are in the generated page |
| `test-full` | `pytest tests/ -q --cov=src --cov-report=term-missing` | Everything this host can reach, including live downloads, plus coverage |
| `docs` | `python scripts/check_docs_links.py` | Every relative link in tracked Markdown resolves; `docs/*.md` stays listed in `docs/documentation-index.md` and linked from `docs/README.md` |
| `gnn` | `uv run --no-project --with … python scripts/gnn_conformance.py` | The pinned parser parses and type-checks the GNN sketches |

`gate all` runs `lint`, `format`, `types`, `test`, `docs`, `gnn` in that order and
stops reporting per arm; it is the pre-push gate. `test-full` is deliberately not in
`all`: it is the only arm that reaches the network in tests, so it is run when network
behavior is what changed.

## GNN arm details

- Pin: [`.github/gnn-pin.json`](../.github/gnn-pin.json), schema `gnn-importer-pin/v1`,
  `ActiveInferenceInstitute/Generalized_Notation_Notation` at `v5.0.3`
  (`8f293d9ba810e6eda5c09842d9c7ed9ffa5f92c1`).
- [`.github/GNN.md`](../.github/GNN.md) records what the job parses and type-checks.
- The arm asks the check script for its install specs (`--requirements`), so the pin
  is read in exactly one place, then runs it in a throwaway `uv` environment. No
  project dependency is installed for this arm.
- With no `*.gnn.md` sketch in the tree, the check parses the pinned upstream
  `input/gnn_files/basics/static_perception.md` exemplar; that is a pipeline and pin
  baseline, not a claim that this repository contains a model.

## CI

| Workflow | Job key | Display name | Runs |
| --- | --- | --- | --- |
| `.github/workflows/test.yml` | `gate` | `Gate (lint · format · types · tests · docs)` | `run.py gate lint format types test docs` |
| `.github/workflows/test.yml` | `gnn-conformance` | `gnn conformance (pinned)` | `run.py gate gnn` |
| `.github/workflows/artifact-guard.yml` | `no-tracked-artifacts` | `No tracked *.log / *.part / *.ytdl / .DS_Store` | `git ls-files` check |

Both `test.yml` jobs use `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`
(v7.0.1) and `astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2`
(v10.3.3, caching enabled). This repository does not use a composite
`setup-python-uv` action; the `gate` job syncs the single locked environment above,
and the `gnn` job installs only the pinned parser.

GitHub Actions is billing-locked for the organization, so the hosted jobs are not the
proof: `uv run python run.py gate` on a provisioned checkout is.

## Measured wall time

Two files carry the evidence; neither is prose that can drift:

| File | Role | Maintained by |
| --- | --- | --- |
| [`gate-baseline.json`](gate-baseline.json) | Pre-entry-point readings: the same checks run as raw `ruff` / `mypy` / `pytest` commands, plus the same-command comparison that isolates the coverage removal | recorded once, reviewed like code, then left alone |
| [`_generated/gate-arms.md`](_generated/gate-arms.md) | Before/after per arm, deltas, each arm's own result line, the coverage total, and the exact after/before commands | `uv run python run.py gate report` |

The generator reads the baseline file, so this guide states no timing and no test
count of its own. Read the generated page for numbers; two caveats it also records:
warm caches flatter `types` and `gnn`, and `test-full` varies with the network because
it runs the live download tests.

## Adding an arm

1. Add the argv to `gate_commands()` and the name to `GATE_ARMS` in `run.py`
   (add it to `GATE_REPORT_ARMS` as well if the report should measure it).
2. Add the row to the arms table above and any rule it enforces to the doc it protects.
3. Run `uv run python run.py gate <arm>` and, if the timing page should change,
   `uv run python run.py gate report`.
