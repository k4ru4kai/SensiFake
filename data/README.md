# SensiFake local data layout

The canonical training-data input is `data/datasets/openfake/pilot-600/`. Only
validated material under `data/datasets/...` should be treated as input to the
final dataset-building pipeline.

`data/experiments/` contains reproducible or disposable collection runs:

- `openfake/smoke/` contains the initial `smoke-test` run.
- `openfake/validation/` contains precollection and target-100 validation runs.
- `openfake/production-gates/` contains the two monitored production-gate runs.
- `openfake/monitoring/` contains monitoring evidence for the 600-image pilot.
- `sid-set/` is reserved for a future mocked-first smoke collection.

`data/archives/openfake/` contains immutable publication backups and the
original `sensifake-600.zip`. Archives are provenance material, not active
training input, and must not be deleted merely because they appear redundant.

SID-Set has not been downloaded or collected. Its canonical placeholder is
documented in `data/datasets/sid-set/README.md`.
