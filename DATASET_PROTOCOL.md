# SensiFake Dataset Protocol

## Manual sensitivity annotation

Sensitivity is annotated manually from visible image content. Annotators must
not see or infer authenticity, source dataset, generator/model, prompt, image
path, or a filename that reveals a real/fake label. Automated sensitivity
prediction is outside this stage.

Each image receives three dimension scores:

- `public_relevance` (0–2): 0 for no evident public-interest relevance, 1 for
  limited or contextual relevance, and 2 for clear broad public relevance.
- `harm_urgency` (0–2): 0 for no observable urgent harm, 1 for a plausible or
  moderate harm concern, and 2 for a severe or time-critical concern.
- `vulnerability` (0–1): 0 when no observable vulnerability cue is present and
  1 when a visible person or context warrants added protection.

The application calculates:

```text
sensitivity_score = public_relevance + harm_urgency + vulnerability
```

Scores 0–1 map to `low`, 2–3 to `medium`, and 4–5 to `high`.
The annotator may add an optional observable rationale of at most 280
characters. An empty rationale is valid and is stored as an empty CSV value.
Rationales remain useful for ambiguous, low-confidence, or review cases, but
they are never required. Confidence is `high`, `medium`, or `low`. Low
confidence selects `needs_review` by default; the flag remains manually
editable. Initial annotations use `annotation_round = 1` and an automatic UTC
timestamp.

## Reproducibility and quality control

Manifest order is shuffled deterministically with seed 42 and represented by
opaque blind IDs. The 30-image calibration is the prefix of that order, so a
full run safely resumes the same records. Every save is an atomic CSV rewrite,
duplicates are rejected, and an existing annotation cannot be changed without
explicit confirmation.

Quality control includes low-confidence and review queues plus a deterministic,
blind 20% sample for a later re-annotation round. Authenticity/source joins are
permitted only in read-only presentation mode after a round is complete or an
annotation snapshot has been frozen.

The authoritative OpenFake pilot manifest is
`data/datasets/openfake/pilot-600/manifest.jsonl`. Development annotation
outputs live under `annotations/openfake/development-v0/`; SID-Set annotation
directories remain placeholders until genuine source data is collected.
