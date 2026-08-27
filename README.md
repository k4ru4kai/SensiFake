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
