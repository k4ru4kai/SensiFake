# SensiFake local data layout

The canonical collections are stored under `data/datasets/`. Only
validated material under `data/datasets/...` should be treated as input to the
final dataset-building pipeline.

`data/experiments/` contains reproducible or disposable collection runs:

- `openfake/smoke/` contains the initial `smoke-test` run.
- `openfake/validation/` contains precollection and target-100 validation runs.
- `openfake/production-gates/` contains the two monitored production-gate runs.
- `openfake/monitoring/` contains monitoring evidence for the 600-image pilot.
- `sid-set/` contains historical SID-Set collection checks when present locally.

`data/archives/openfake/` contains immutable publication backups and the
original `sensifake-600.zip`. Archives are provenance material, not active
training input, and must not be deleted merely because they appear redundant.

The documented local collection includes SID-Set `candidate-1500`; the actual
images are not distributed in Git. See [the dataset audit](../docs/data_manifest.md)
for recorded counts and provenance limitations. A fresh clone does not contain
the local collections, RRDataset ZIPs, or generated unified manifests.
