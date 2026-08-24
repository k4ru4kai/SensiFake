# SensiFake

SensiFake is a university computer-vision project investigating
content-sensitivity-aware deepfake detection. The current pipeline performs the
first technical collection stage: it builds a balanced pool of valid real and
synthetic images before later sensitivity annotation and benchmark selection.

## Status

The OpenFake pilot collection is complete: 600 unique images were collected
from `ComplexDataLab/OpenFake`, with explicit quotas of 300 real and 300 fake
images. A baseline detection model is the next planned milestone.

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

## Collection

The definitive pilot configuration is `configs/openfake_600.toml`. Start a new
collection with:

```bash
uv run python scripts/stream_collect.py \
  --config configs/openfake_600.toml \
  --output data/sensifake-600 \
  --no-resume
```

Use `--resume` with a compatible checkpoint to continue an interrupted run.
Configuration fingerprints prevent unsafe resume when source-critical settings
change. Collection is reproducible with a fixed dataset revision and
configuration; the final pilot intentionally does not shuffle the source.

The collector validates images with Pillow, hashes and stores original encoded
bytes, rejects duplicates, writes an append-only manifest, and creates atomic
checkpoints and summaries. Kaggle publishing is disabled by default and requires
the explicit `--publish-kaggle` flag.

`data/` is intentionally excluded from Git, including collected images,
manifests, checkpoints, summaries, monitoring evidence, and diagnostic runs.
Credentials and local environment files are also ignored. Only source code,
configuration, tests, documentation, and dependency metadata belong in this
repository.
