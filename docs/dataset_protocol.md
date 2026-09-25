# SensiFake Dataset Protocol

## Scope and primary task

SensiFake's primary task is binary authenticity classification:

```text
real
fake
```

Authenticity labels come from the source datasets. The vision-language model
(VLM) annotates semantic sensitivity only; it must not predict authenticity and
is not the final detector.

The planned experimental comparison is:

1. a baseline authenticity detector;
2. a sensitivity-aware detector, for example through loss weighting;
3. an optional multi-task extension with a second sensitivity head, only if
   time and experimental results justify it.

## Final 3,000-image dataset

The final corpus contains 3,000 images, balanced by source and authenticity:

| Source | Real | Fake | Total |
| --- | ---: | ---: | ---: |
| OpenFake | 750 | 750 | 1,500 |
| SID-Set | 750 | 750 full synthetic | 1,500 |
| **Total** | **1,500** | **1,500** | **3,000** |

The OpenFake allocation includes the existing 600-image pilot (300 real and
300 fake). It therefore requires 900 additional images: 450 real and 450 fake.
For SID-Set, native label 0 maps to `real`, native label 1 (`full_synthetic`)
maps to `fake`, and native label 2 (`tampered`) is excluded from the binary
core dataset.

Both sources are read through Hugging Face streaming with their separate
adapters and the common collector. Collection provenance must retain:

- source dataset and configuration;
- split;
- requested revision and resolved immutable commit SHA;
- source ID;
- native label and its normalized `real`/`fake` mapping;
- SHA-256 content hash.

The authoritative OpenFake pilot manifest remains
`data/datasets/openfake/pilot-600/manifest.jsonl`. SID-Set data will not be
promoted into `data/datasets/sid-set/` until a bounded collection has been
completed and validated.

## Semantic sensitivity labels

Sensitivity is represented by three independently stored axes:

- `public_relevance` (0–2): 0 for no evident public-interest relevance, 1 for
  limited or contextual relevance, and 2 for clear broad public relevance;
- `harm_urgency` (0–2): 0 for no observable urgent harm, 1 for a plausible or
  moderate harm concern, and 2 for a severe or time-critical concern;
- `vulnerability` (0–1): 0 when no observable vulnerability cue is present and
  1 when a visible person or context warrants added protection.

The aggregate score and level are:

```text
sensitivity_score = public_relevance + harm_urgency + vulnerability

low:    0–1
medium: 2–3
high:   4–5
```

Each annotation keeps the three component scores, aggregate score, final
level, confidence, rationale, `needs_review`, and annotation provenance as
separate fields. The rationale is optional, limited to 280 observable-content
characters, and an empty rationale is valid. Confidence is `high`, `medium`,
or `low`; low confidence selects `needs_review` by default, while the flag
remains manually editable.

The distribution of `low`, `medium`, and `high` is unknown before annotation
and is not assumed to be balanced. It will be measured and handled through
stratified sampling, per-class metrics, and, where appropriate, training
weights.

## Definitive Gold/Silver protocol

| Subset | Size | Annotation | Use |
| --- | ---: | --- | --- |
| Gold development | 101 | Human, already completed on OpenFake | Rubric definition, prompt development, and examples |
| Silver training | 2,599 | VLM | Extended training |
| Gold validation | 100 | Human and blind to the VLM | Threshold selection, error analysis, and calibration |
| Gold test | 200 | Human and blind to the VLM | Locked final evaluation |

The complete training set is:

```text
101 Gold development + 2,599 Silver = 2,700 images
```

The held-out evaluation data is:

```text
100 Gold validation + 200 Gold test = 300 images
```

The total human annotation effort is:

```text
101 already completed + 300 new = 401 human annotations
```

There is no additional separate 360-image or 15% audit. The 300 new Gold
annotations also form the VLM audit sample. The existing 101 images are
development data and are not part of the final test set.

Annotation provenance must distinguish the following origins explicitly:

```text
human
vlm
human_reviewed
```

VLM annotations are Silver labels (or validated pseudo-labels after the audit),
not ground truth. `human_reviewed` identifies a VLM-produced annotation that
was subsequently reviewed by a human; it must remain distinguishable from a
fully blind `human` annotation.

## Gold selection and split integrity

The 200-image Gold test set is selected randomly and stratified at least by
source and authenticity. It is locked after selection and must not be used to
change the prompt, rubric, thresholds, or model.

The 100-image Gold validation set intentionally covers:

- cases predicted as `high`;
- low-confidence cases;
- unstable or discordant VLM outputs;
- both OpenFake and SID-Set;
- both authenticity classes.

Annotators must not see VLM responses during human annotation. They also must
not see or infer authenticity, source dataset, generator/model, prompt, image
path, or filenames that reveal a `real`/`fake` label.

Exact content-hash duplicates and groups of substantially equivalent images
must not cross the training, validation, and test boundaries. A unified
manifest owns the split assignments and references the source files without
physically duplicating them.

## VLM validation

The VLM assigns only the semantic sensitivity axes and derived level. Agreement
against the human Gold annotations is evaluated with:

- weighted Cohen's kappa for the ordinal axes and sensitivity level;
- macro-F1;
- per-class precision, recall, and F1;
- confusion matrices;
- mean absolute error on `sensitivity_score`;
- exact-score accuracy and the percentage within plus or minus 1;
- recall for `high` cases;
- qualitative error analysis.

No acceptance threshold or unmeasured result is fixed in advance. Thresholds
are documented as project design choices after the experiment, based on Gold
validation; the locked Gold test is used only for final reporting. Silver
labels are frozen only after this validation stage.

## Existing development annotation workflow

The completed OpenFake development annotations live under
`annotations/openfake/development-v0/`. Their historical collection procedure
remains reproducible: manifest order was shuffled deterministically with seed
42 and represented by opaque blind IDs; the 30-image calibration was the prefix
of that order, so the full run resumed the same records. Initial annotations
used `annotation_round = 1` with an automatic UTC timestamp.

The annotation application uses atomic CSV rewrites, rejects duplicates, and
requires explicit confirmation before changing an existing annotation. Its
quality-control views include low-confidence and review queues plus a
deterministic blind 20% development re-annotation sample. This is development
consistency checking, not an additional population-wide VLM audit. Source and
authenticity joins are allowed only in read-only presentation mode after a
round is complete or its snapshot has been frozen.

## Execution order

1. Collect 1,500 SID-Set images.
2. Collect 900 additional OpenFake images without modifying the pilot.
3. Create and validate the unified 3,000-image manifest without physically
   duplicating files.
4. Run the VLM on images not already annotated.
5. Select and annotate the 300 new Gold images.
6. Evaluate the VLM against Gold.
7. Freeze the Silver labels.
8. Create the final leakage-controlled splits.
9. Train and compare the authenticity detectors.
