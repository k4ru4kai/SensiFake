> Detailed workflow reference. Run all commands from the repository root. Start with the [main README](../README.md).

# SensiFake

SensiFake is a university computer-vision project investigating
content-sensitivity-aware deepfake detection. The current pipeline performs the
first technical collection stage: it builds a balanced pool of valid real and
synthetic images before later sensitivity annotation and benchmark selection.

## Status

The canonical OpenFake pilot at `data/datasets/openfake/pilot-600/` is complete:
600 unique images were collected from `ComplexDataLab/OpenFake`, with explicit
quotas of 300 real and 300 fake images. The local collection also contains
900 additional OpenFake images and 1,500 SID-Set images. Each collection is
balanced by its source real/fake labels. The current RRDataset selection
has 1,500 files (1,499 distinct hashes). Its local folder labels have no verified
copy provenance, so the unified manifest conservatively records them as unknown.

## Unified selection manifest

Run `.venv/bin/python scripts/datasets/build_unified_manifest.py` from the repository root.
It validates selected images and joins the 401 completed human annotations into
`data/unified/selected_images.csv`, with an incremental annotation registry and
`audit_report.json`. Original data is read-only. Repeated runs are deterministic;
unmatched annotations and conflicts are retained and reported. This curator-only
manifest is separate from the blinded app and does not select a golden set.
See [DATA_MANIFEST.md](data_manifest.md) for verified counts, RRDataset evidence,
schema, input limitations, and regeneration instructions.

To prepare the balanced RRDataset batch for manual annotation, run
`.venv/bin/python scripts/datasets/select_rrdataset_batch.py`. Import the resulting
`data/rrdataset-300-v1/annotation_batch.zip` in the shared app with role
`rrdataset`. It contains 300 distinct hashes, 50 from each of the six local
person/folder groups. Folder labels remain unverified hints, not authenticity
ground truth. The selection manifest and report accompany the ZIP; reruns
refuse to overwrite a different selection. See [DATA_MANIFEST.md](data_manifest.md).

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
- `scripts/collection/stream_collect.py` owns streaming, validation, persistence,
  deduplication, checkpoint/resume, retry/deadline handling, progress, and
  optional Kaggle synchronization. `scripts/collection/source_adapters/` contains only
  native source-schema normalization.

See [data/README.md](../data/README.md) for the run-by-run classification. Only
`data/datasets/...` is an input to the final dataset-building pipeline.

## Collection

The definitive OpenFake configuration is `configs/sources/openfake.toml`.
Reproduce it into an experiment directory for validation; do not write over the
canonical pilot:

```bash
uv run python scripts/collection/stream_collect.py \
  --config configs/sources/openfake.toml \
  --output data/experiments/openfake/validation/pilot-rebuild \
  --no-resume
```

Use `--resume` with a compatible checkpoint to continue an interrupted run.
Configuration fingerprints prevent unsafe resume when source-critical settings
change. Collection is reproducible with a fixed dataset revision and
configuration; the final pilot intentionally does not shuffle the source.

The SID-Set smoke collection configuration remains available for testing:

```bash
uv run python scripts/collection/stream_collect.py \
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

## Shared manual annotation

For annotation on separate computers without a shared server, see
[OFFLINE_ANNOTATION.md](offline_annotation.md). It provides disjoint local
databases and a validated merge of completed work.

Start **one shared Streamlit process** for the three annotators from the repository
root. By default, the SQLite database is saved at
`annotations/shared/sensifake.sqlite3` on that host:

```bash
uv sync --group dev
uv run streamlit run scripts/annotation/app.py --server.address 0.0.0.0
```

For another location, pass `-- --storage /absolute/persistent/path/sensifake.sqlite3`
or set `SENSIFAKE_STORAGE` to an absolute path. Keep the repository or chosen
storage directory on persistent local disk. The database contains original image
bytes, batch memberships, provenance, drafts, completed annotations, and all
reviews. SQLite uses WAL, full synchronous writes, and transactional reservations
and saves. Use local disk, not a network filesystem. Back up the database using
SQLite's backup API, or stop the app before copying the database and any WAL
files together. The files can be large because image bytes are included.

Use a trusted shared host and give each person the same app URL. Names are
self-declared identities, not authenticated accounts; use consistent, distinct
names. Case, surrounding whitespace, and Unicode presentation differences are
normalized for identity checks. The host must supply access control if needed.
No deployment is configured; an ephemeral cloud disk is not persistent storage.

1. **Import batches:** Open *Import batches*, enter a unique name and dataset
   role, upload a ZIP, and click *Import batch*. Any positive number of images
   is accepted within the limits below. All files are validated before the
   transaction commits. Unsafe paths, links, encrypted entries, unreadable
   images, and repeated filenames are rejected. No archive is extracted to
   user-selected filesystem paths. SHA-256 duplicates are reported, stored once,
   and linked to their batch/filename entries. Their existing annotation applies
   to every membership; provenance is retained independently for each filename.
2. **Preserve existing work:** Under *Import existing completed annotations*,
   import the validated 401-row snapshot once. Its exact audited SHA-256 is
   checked, as are every image hash and the annotation schema. This creates
   separate `gold_development` (101) and `human_train` (300) batches and preserves
   the recorded annotators, rubric values, and timestamps. These completed
   annotations initially await independent review. Source CSVs remain unchanged.
   Sara's seven-row draft and experimental Qwen outputs are never scanned or
   imported. The host needs the snapshot and its three referenced collection
   directories for this import; afterwards the database is self-contained.
3. **Annotate:** Enter your name, choose one batch or all open batches, and click
   *Resume or reserve an image*. Only pixels and an opaque ID are displayed.
   Keep the existing 0–2 / 0–2 / 0–1 rubric; the app derives the 0–5 total and
   low/medium/high level. Rationale is optional. Low confidence selects
   `needs_review`, which remains editable. Widget changes save a draft and
   renew the reservation; text changes are sent when leaving the field.
   Click *Save completed annotation* to finish, then reserve the next image.
   Closing the browser preserves submitted drafts. Unsent keystrokes cannot be
   recovered. Resume uses the same name, and abandoned reservations expire
   after 15 minutes (configurable). Expired sessions cannot save over a later
   reservation. *Release image* returns it immediately while retaining the draft.
4. **Review:** Enter your own name and select *Review*. Reserve an annotation
   from another person. The original annotation is displayed; confirm the
   current decision or correct it with a required reason. The original remains
   immutable and every review is appended. Corrections count as confirmed by
   that reviewer. *Include previously reviewed images* permits another review
   of the latest decision. Self-review is rejected using normalized names.
   The `needs_review` rubric flag is retained even after confirmation; it is
   separate from the independently recorded review status.
5. **Progress and exports:** See per-batch and overall counts and download
   *Current annotations*, *Confirmed annotations*, or *Review history* at any
   time. Incomplete and closed batches can be exported. Current annotations use
   the latest reviewed values when present, with the original decision retained
   in `original_annotation_json`. History contains one row per review and batch
   filename membership. Exports include batch/role, hash, original filename,
   annotator, reviewer, timestamps, provenance, and rubric fields. Empty exports
   still contain headers. Duplicate memberships intentionally produce multiple
   rows; overall progress counts each image hash once. Refresh the page to see
   work saved by other users.

Batch checkboxes in *Import batches* control whether a batch is open to the
queues. Closing a batch does not delete it or prevent an existing reservation
from finishing. A resumed reservation takes precedence over a newly selected
batch filter; release it first to change scope.

### ZIP provenance format

Images may be in subdirectories. An optional root `metadata.json` maps exact
ZIP filenames to JSON provenance objects. All supplied fields are preserved:

```json
{
  "selection/photo.png": {
    "source_dataset": "RRDataset",
    "normalized_label": "real",
    "label_source": "authoritative source manifest reference",
    "source_image_id": "example-123"
  }
}
```

`normalized_label` accepts `real`, `fake`, or `unknown`. Supplying real/fake
requires `label_source`; its accuracy is the importer's responsibility. Without
an explicit label the app stores `unknown`, including for names like `real_1.jpg`.
Metadata for absent filenames is rejected. No labels are inferred from folders.
ZIPs are limited to 10,000 entries, 512 MiB uncompressed, 40 MiB per image, and
2 MiB metadata; Pillow's image-size safety checks apply. Streamlit's default
upload limit also applies (configure `server.maxUploadSize` on the shared host
if necessary). Use single-frame images. Split larger selections into batches.

### Legacy tools and verification

`scripts/legacy/annotation_app.py`, the assignment builders, and `scripts/legacy/ANNOTATION_APP.md` describe
the older fixed-manifest/per-person CSV workflow. They remain available under scripts/legacy/ for
historical reproducibility and presentation; they do not share state with the new database.
Use `scripts/annotation/app.py` for the shared workflow. Existing annotation CSVs
and collection manifests are not rewritten or automatically synchronized.
`docs/dataset_protocol.md` remains the source for experimental split roles.

```bash
uv run pytest tests/test_shared_annotation.py tests/test_sensitivity_annotation.py
```

Tests cover simultaneous claims and saves, expired reservations, draft recovery,
ZIP safety, duplicate images, immutable originals, review history, incomplete
exports, and a Streamlit smoke test. The local 401-row import check skips when
its ignored data files are unavailable in another checkout.
