# SensiFake Sensitivity Annotation App

The local Streamlit artifact supports reproducible, blinded manual sensitivity
annotation of the existing OpenFake pilot. It reads the authoritative manifest,
resolves the existing image files, shuffles them with seed 42, and displays only
image bytes and opaque IDs. It never predicts sensitivity and never writes to
the images or collector manifest.

Annotations autosave atomically after every successful Previous, Save, or Next
action to
`annotations/openfake/development-v0/sensitivity_annotations.csv`. Existing
rows resume by content hash and annotation round. Changed non-empty rows require
the on-screen overwrite confirmation. `sensitivity_rationale` is always present
in the CSV schema but is optional: a blank input is saved as an empty string.
When useful, annotators can provide up to 280 observable characters for
ambiguous, low-confidence, or needs-review cases.

## Commands

Install the locked environment:

```bash
uv sync
```

Run the required 30-image calibration:

```bash
uv run streamlit run scripts/legacy/annotation_app.py -- --mode annotation --calibration
```

Run the full 600-image annotation, resuming the calibration rows:

```bash
uv run streamlit run scripts/legacy/annotation_app.py -- --mode annotation
```

Run a five-image session-only demo that cannot alter the real annotation CSV:

```bash
uv run streamlit run scripts/legacy/annotation_app.py -- --mode annotation --demo
```

Run the read-only presentation artifact after round 1 is complete:

```bash
uv run streamlit run scripts/legacy/annotation_app.py -- --mode presentation
```

Alternatively, report from an explicitly frozen snapshot:

```bash
uv run streamlit run scripts/legacy/annotation_app.py -- --mode presentation \
  --frozen-annotations \
  annotations/openfake/development-v0/frozen/sensitivity_annotations_round1.csv
```

Presentation mode is gated: without `--frozen-annotations`, all 600 manifest
images must have a valid annotation for the selected round. The complete
dashboard then joins authenticity and source metadata in memory. Annotation
mode never performs or displays that join.

The Quality Control tab exports the deterministic blind 20% round-2 sample.
That exported list is the preparation artifact for the later re-annotation
workflow; SID-Set is not read or collected by this application. The annotation
CSV uses `(content_hash, annotation_round)` as its duplicate-safe key.
