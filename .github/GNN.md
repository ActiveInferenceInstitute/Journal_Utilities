# GNN conformance

`gnn conformance (pinned)` is the job key `gnn-conformance` in
`.github/workflows/test.yml`. It runs one command,
`uv run python run.py gate gnn`, which executes `scripts/gnn_conformance.py` in a
throwaway `uv` environment containing only the pinned parser.

The check reads `.github/gnn-pin.json` — schema `gnn-importer-pin/v1` — which pins
`ActiveInferenceInstitute/Generalized_Notation_Notation` at `v5.0.3`
(`8f293d9ba810e6eda5c09842d9c7ed9ffa5f92c1`). The pin is the only source of the
repository, tag and revision; the script's `--requirements` output is derived from it,
so the workflow never restates the revision.

The job verifies the pin and installed parser, parses every `*.gnn.md` sketch
in the repository (`parse_gnn_formal` on the path, `validate_gnn_syntax` on the text),
and type-checks copies of them. When the repository has no sketch yet,
it parses the pinned upstream `input/gnn_files/basics/static_perception.md`
exemplar; this is a pipeline and pin conformance baseline, not a claim that the
repository already contains a model. The arm prints one JSON summary line
(`gnn-version`, `pin-revision`, `models`, `source`, `result`).
