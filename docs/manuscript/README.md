# From Public Video to a Traceable Transcript Corpus

An architecture and verification study of Journal Utilities. [Pinned source tree](https://github.com/ActiveInferenceInstitute/Journal_Utilities/tree/123df152de4ceac54f233a2df8b507741cb3f2ca).

- [Abstract](00_abstract.md)
- [Introduction](01_introduction.md)
- [Methods](02_methods.md)
- [Results and limitations](03_results_and_limitations.md)
- [Discussion](04_discussion.md)
- [Bibliography](references.bib)

## Render and validate

Use a clean checkout named `Journal_Utilities` and the [pinned docxology renderer](https://github.com/docxology/template/tree/87704feae0a4490ef7dad9c931d268e8c30273c2).
Install Git, uv, Pandoc, XeLaTeX, and the packages listed in the
[template setup guide](https://github.com/docxology/template/blob/87704feae0a4490ef7dad9c931d268e8c30273c2/docs/guides/startup-and-setup.md).
Run from the root of the source checkout.

```sh
source_checkout="$(pwd -P)"
source_name="${source_checkout##*/}"
renderer_checkout="$(mktemp -d)/template"
git init "$renderer_checkout"
git -C "$renderer_checkout" fetch --depth=1 https://github.com/docxology/template.git 87704feae0a4490ef7dad9c931d268e8c30273c2
git -C "$renderer_checkout" checkout --detach FETCH_HEAD

cd "$renderer_checkout"
uv sync --locked
mkdir -p projects/working
ln -s "$source_checkout" "projects/working/$source_name"
uv run --no-sync python scripts/pipeline/stage_03_render.py --project "working/$source_name"
uv run --no-sync python scripts/pipeline/stage_04_validate.py --project "working/$source_name"
```

Stage 3 writes the combined PDF to `output/pdf/Journal_Utilities_combined.pdf` in
the source checkout. Stage 4 records its verdict in
`output/reports/validation_report.md`. The source and artifact bindings are
recorded in `output/reports/rendered_provenance.json`. Use a disposable
checkout to keep the generated files separate from source edits.
