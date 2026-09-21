# SensiFake

SensiFake is a university computer-vision project investigating
content-sensitivity-aware deepfake detection. The current pipeline performs the
first technical collection stage: it builds a balanced pool of valid real and
synthetic images before later sensitivity annotation and benchmark selection.

## Status

The canonical OpenFake pilot at `data/datasets/openfake/pilot-600/` is complete:
600 unique images were collected from `ComplexDataLab/OpenFake`, with explicit
quotas of 300 real and 300 fake images. SID-Set has not yet been collected.

The pilot uses sequential streaming selection with explicit per-label quotas.
It is balanced, but it is not a globally random sample. Hugging Face streaming
shuffle is disabled because buffering image-bearing records caused excessive
memory use, even with small buffers.

## Setup

The project uses Python 3.12 and [uv](https://docs.astral.sh/uv/):

```bash
uv python install 3.12
uv sync --group dev
```

The collector streams one record at a time. For the Hugging Face Parquet source,
`batch_size=1` and `pyarrow.dataset.ParquetFragmentScanOptions(pre_buffer=False)`
avoid background image-heavy prefetching while preserving the original encoded
image bytes.

## Repository layout

- `data/datasets/` contains canonical, validated pipeline inputs.
- `data/experiments/` contains smoke, validation, production-gate, and
  monitoring runs that can be reproduced or discarded after review.
- `data/archives/` contains immutable backups and packaged snapshots.
- `annotations/openfake/development-v0/` contains the current OpenFake human
  development annotations.
- `scripts/stream_collect.py` owns streaming, validation, persistence,
  deduplication, checkpoint/resume, retry/deadline handling, progress, and
  optional Kaggle synchronization. `scripts/source_adapters/` contains only
  native source-schema normalization.

See `data/README.md` for the run-by-run classification. Only
`data/datasets/...` is an input to the final dataset-building pipeline.

## Collection

The definitive OpenFake configuration is `configs/sources/openfake.toml`.
Reproduce it into an experiment directory for validation; do not write over the
canonical pilot:

```bash
uv run python scripts/stream_collect.py \
  --config configs/sources/openfake.toml \
  --output data/experiments/openfake/validation/pilot-rebuild \
  --no-resume
```

Use `--resume` with a compatible checkpoint to continue an interrupted run.
Configuration fingerprints prevent unsafe resume when source-critical settings
change. Collection is reproducible with a fixed dataset revision and
configuration; the final pilot intentionally does not shuffle the source.

The future mocked-first SID-Set smoke test is configured but has not been run:

```bash
uv run python scripts/stream_collect.py \
  --config configs/sources/sid_set.toml \
  --output data/experiments/sid-set/smoke-10 \
  --no-resume
```

Before running that command, confirm the live split/config and native streamed
image representation. SID-Set label 2 (`tampered`) is intentionally skipped
from the binary core dataset.

The collector validates images with Pillow, hashes and stores original encoded
bytes, rejects duplicates, writes an append-only manifest, and creates atomic
checkpoints and summaries. Kaggle publishing is disabled by default and requires
the explicit `--publish-kaggle` flag.

## Annotation

The Streamlit app reads the canonical OpenFake manifest and writes to
`annotations/openfake/development-v0/sensitivity_annotations.csv` by default:

```bash
uv run streamlit run annotation_app.py -- --mode annotation
```

See `ANNOTATION_APP.md` and `DATASET_PROTOCOL.md` for blinding, autosave,
re-annotation, and presentation-mode rules.

Local dataset payloads and annotation CSVs remain excluded from Git. The small
layout and placeholder README files are tracked; credentials and local
environment files remain ignored.

## Manual annotation

The maintainer generates **human-train-v0 once for the whole team**, using three
agreed annotator IDs. Annotators must not generate or modify assignments. From
the repository root, install the environment:

```bash
uv sync
```

Maintainer preview (writes nothing; replace the example IDs before use):

```bash
uv run python scripts/build_human_train_assignment.py --help
uv run python scripts/build_human_train_assignment.py --annotators alice bob carol --dry-run
```

When ready, the maintainer runs the same command without `--dry-run`. The seed
defaults to 42. Selection uses seeded SHA-256 ranking, independent of input row
order and annotator argument order. The master contains 300 unique, originally
unassigned images, 75 per source/class combination. Each annotator receives 100
images, 25 per combination, in a deterministic shuffled order. Gold development
and test are excluded; the original Gold/Silver CSV is never changed.

The master is `annotations/splits/human_train_assignment.csv`; the three tasks
are `annotations/tasks/human-train-v0/<annotator_id>.csv`. Existing identical
outputs return `unchanged`; conflicting files cause an error without overwriting.
The command prints counts, per-annotator distributions and each file's SHA-256.
The maintainer distributes the tasks and matching local dataset images to the
team, retaining the master for auditing. Tasks contain only `blind_id`,
`content_hash`, `component`, `relative_image_path`, and `annotation_order`.
Source/class columns are omitted; required component/path fields can still
reveal provenance or class when inspected, so the app displays only images and
blind IDs. Do not inspect task metadata or the master while annotating.

List the available IDs without launching Streamlit:

```bash
uv run python annotation_app.py --list-annotators
```

Start your own session (replace `alice` with your assigned ID):

```bash
uv run streamlit run annotation_app.py -- --mode human-train --annotator alice
```

This mode loads only your 100 images and writes automatically to
`annotations/human-train-v0/alice/sensitivity_annotations.csv`. **Save**, **Next**
and **Previous** save the current image atomically. Widget changes alone are not
saved: press one of these buttons before closing. A new session resumes at the
first unannotated image in task order. Once all 100 are complete, the progress
indicator shows 100/100 and saved images remain available for review. Changes to
saved annotations require explicit overwrite confirmation. Do not run multiple
sessions for the same ID simultaneously.

The session's ID and output are fixed at launch; output overrides and unsafe IDs
are rejected. Missing tasks/images produce an error: ask the maintainer to
provide them. Gold development uses its existing separate mode and output.
IDs select local tasks; this is a trusted-team workflow, not account authentication.

To save **only your CSV** in Git, use its exact path. `-f` is needed because
annotation outputs are ignored by default; `--only` excludes other staged work:

```bash
git add -f -- annotations/human-train-v0/alice/sensitivity_annotations.csv
git commit --only -m "Add alice human training annotations" -- annotations/human-train-v0/alice/sensitivity_annotations.csv
```

Coordinate one owner per ID and share commits through the team's normal review
workflow. Never stage another annotator's CSV or regenerate the team's tasks.
