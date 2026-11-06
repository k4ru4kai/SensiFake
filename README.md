# SensiFake — v0.1 Research Project

SensiFake explores whether an image's semantic sensitivity should affect the
evidence needed to classify it as real. It combines a sensitivity-annotated
real/fake dataset with independent image classifiers and a configurable fusion
threshold. This release provides dataset access, historical experiments, saved
results and lightweight verification tools.

## Dataset

The [published Hugging Face corpus](https://huggingface.co/datasets/K4ru4k4i/SensiFake/tree/0804959a6daab0e8041e5120e366580543726905)
contains **4,499 unique images**: 1,500 OpenFake, 1,500 SID-Set and 1,499 RRDataset.
It has 2,249 real / 2,250 fake images; 1,101 sensitivity labels are human-provided
and 3,398 are automatic **silver** labels. Human labels take precedence.

Images stay on Hugging Face. The resolver pins revision
`0804959a6daab0e8041e5120e366580543726905`, checks SHA-256 integrity and loads
images into memory or a disposable job cache. Git contains schema, aggregate
metadata and [privacy-minimized research CSVs](docs/PRIVACY_PATCH.md), not dataset
images, model weights or operational databases.

## Architecture

Collection/manual review → ordinal V3 labeler → labelled corpus → ADN + CSN → fusion.

- **Ordinal V3 auto-annotator:** two cumulative ResNet50 outputs, for sensitivity
  score ≥1 and ≥2. Its historical supervision split is 769/192/140; recorded
  decoding thresholds are 0.50/0.44.
- **ADN:** an image-only binary real/fake classifier.
- **Downstream CSN:** a separate image-only, three-class sensitivity classifier,
  distinct from the ordinal V3 labeler.
- **Fusion:** with `rho = w_L*p_low + w_M*p_medium + w_H*p_high`, predict real
  only when `p_real > 0.5 + epsilon*rho`. Ties are fake. Increasing epsilon can
  reduce missed fakes while increasing false alarms.

The [calibration experiments](experiments/fusion_calibration/README.md) document
fixed-weight sweeps, joint searches and exact-breakpoint analysis. Each selected
parameter belongs to its data, checkpoints and objective; no epsilon is universally optimal.

## Quick start

Use Python 3.12. These tools do not train models:

```bash
python -m pip install -r requirements/calibration-observed.txt
python experiments/fusion_calibration/verify_recorded_results.py
python -m pytest -q
```

The requirements record a tested environment rather than a portable lock. The
inherited benchmark dependencies need a separate environment; see [reproduction
notes](docs/REPRODUCTION.md).

```python
import csv, io
from sensifake_data import PublishedDataset

corpus = PublishedDataset()
rows = list(csv.DictReader(io.StringIO(corpus.manifest_bytes.decode())))
image = corpus.load_image(rows[0])  # verified RGB pixels, no permanent download
with corpus.temporary_cache() as job:
    image = job.load_image(rows[0])
```

See the [quickstart notebook](notebooks/sensifake_quickstart.ipynb), preserved
historical notebooks under `notebooks/`, and the unchanged `benchmark/` tools and
results. Full training, inference and historical grid-search commands are not
supported v0.1 entrypoints. Some newly imported source was [withheld pending
contributor permission](docs/DEFERRED_SOURCE.md); its saved results and methodology remain available.

## Recorded experimental results

These are historical experiments, not a single independently reproduced final model.

| Experiment | Evaluation population | Recorded result |
| --- | --- | --- |
| Ordinal V3 labeler | 140 human-labelled test images | Accuracy 0.7571; macro-F1 0.7086 |
| ADN baseline | 450 seed-20 validation images | Accuracy 0.7933; fake recall 0.8444 |
| Fixed-grid / exact selected fusion | Same 450 validation images | Accuracy 0.7711; fake recall 0.8622 |
| Joint weight/epsilon selection | Same 450 validation images | Accuracy 0.7667; fake recall 0.8667 |

The included verifier reproduces selected-policy arithmetic from saved
probabilities without images or checkpoints. See the calibration README and
[run provenance matrix](docs/RUN_PROVENANCE_MATRIX.md).

## Limitations and attribution

Most sensitivity labels are silver. Small high-sensitivity subsets and repeated
model comparisons limit generalization claims. Seed-20 validation and seed-35
test populations overlap by **90 image identities**: do not use the former to
retrospectively calibrate the latter. The 0.036 and 0.10 notebook variants use
rounded weights and are not interchangeable with exact 1/3, 2/3, 1 calibration.

Research CSVs are minimized, **not anonymous**; public history still permits
linkage. Existing contributor credits, benchmark history, source attribution and
license notices are preserved. No new blanket license is applied. Code, images,
annotations and weights have separate rights; see the [license and attribution
review](docs/LICENSE_AND_ATTRIBUTION_REVIEW.md). Hugging Face content is unchanged.
`CITATION.cff.draft` remains an unapproved proposal.
