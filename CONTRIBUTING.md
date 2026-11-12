# Contributing to Journal-Utilities

Thanks for contributing to the Active Inference Institute's Journal-Utilities!
This project is a public submodule of the ActiveInferenceInstitute org — anything
merged is public. Please read this whole page before opening a PR.

## Dev setup

```bash
uv sync --all-extras
cp .env.example .env   # fill in real values; never commit .env
```

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are required. All commands
below are run from the repo root.

## What belongs where

- `src/journal_utilities/` — the package (per-module `README.md` + `AGENTS.md`).
- `scripts/` — one-off and journal-maintenance CLIs (documented in `scripts/README.md`).
- `run.py` — the pipeline CLI entry point; all pipeline options come from `config.ini`.
- `docs/` — module guides (one file per module); `docs/README.md` is the index.
- `tests/` — pytest suite (see `tests/README.md` and `tests/AGENTS.md` for the
  mock policy: real methods and real fixtures; mocks only for external I/O that
  can't run in CI).

**If you modify a module, update its doc** (`docs/<module>.md`). If you add a
script, document it in `scripts/README.md`. If you add a config option, document
it in `docs/configuration.md` and `config.ini`. Stale docs are bugs here.

## Gate workflow (run before pushing)

```bash
uv sync --frozen --extra rag --extra interface --extra export --dev
uv run python run.py gate              # lint, format, types, tests, docs, gnn
```

Every arm is separately runnable (`uv run python run.py gate lint`, `… gate test`,
`… gate gnn`, …) and CI calls that same table — see
[`docs/RUN_GUIDE.md`](docs/RUN_GUIDE.md). `gate test-full` is the one arm that also
reaches the network in tests and measures coverage.

The CI workflow (`.github/workflows/test.yml`) runs the `gate` job and the pinned
`gnn conformance (pinned)` job (see [`.github/GNN.md`](.github/GNN.md)); a PR must be
green on all of them. GitHub Actions is billing-locked organization-wide, so a local
`run.py gate` on a provisioned checkout is the gate that counts. If you change the
journal-maintenance scripts, also run the `validate_journal.py` gate against the
sibling journal:
`uv run python run.py journal-check`.

## Style

- Formatting uses `ruff format` (`make format`); lint via
  `ruff` (`make lint`).
- Commits use conventional-style messages: `docs: …`, `fix: …`, `feat: …`,
  `chore: …`, with a short scope when useful (e.g. `docs(scripts): …`).
- Prefer small, logical commits over one large diff.

## Security rules (non-negotiable)

- **Never commit `cookies.txt`, `.env`, or any credential.** `cookies.txt` was
  once leaked in this repo's history and was purged; it is gitignored and the
  downloader runs cookie-free by default.
- **Never use `--cookies-from-browser` with a tracked output path.**
- **No internal/private paths in committed files** — use repo-relative paths and
  neutral placeholders (see `.env.example`).
- PRs that add secrets or private paths will be rejected and reported.

## Pull requests

1. Branch off `main` (`git checkout -b fix/your-change`).
2. Make the change, run the gate workflow above.
3. Open the PR with a short description of what and why.
4. CI must pass; a maintainer will review.

## License

This project is released under [CC0 1.0 Universal](LICENSE) (public domain
dedication). By contributing you agree to dedicate your contribution to the
public domain under the same terms.
