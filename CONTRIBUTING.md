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
uv run pytest tests/ -q                    # full suite (currently ~475 passed)
uv run ruff check src/ tests/ scripts/     # lint — matches CI
uv run mypy src                            # type check — matches CI
uv run python run.py journal-check         # read-only journal integrity gate
```

The CI workflow (`.github/workflows/test.yml`) runs pytest, ruff, and mypy,
plus the pinned GNN conformance baseline (see `.github/GNN.md`) — a PR must be
green on all of them. If you change the journal-maintenance scripts, also run
the `validate_journal.py` gate against the sibling journal.

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
