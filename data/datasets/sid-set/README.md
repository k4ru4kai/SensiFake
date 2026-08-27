# SID-Set placeholder

No SID-Set data has been collected. A future smoke test will use
`configs/sources/sid_set.toml` and write first to `data/experiments/sid-set/`;
only a separately validated result may later be promoted into this directory.

The live Hugging Face schema was probed on 2026-08-27. It exposes the `default`
configuration with `train` (210,000 rows) and `validation` (30,000 rows) splits.
Both `image` and `mask` are declared as Hugging Face Image features; `img_id` is
a string, `width`, `height`, and `label` are int64. With decoding disabled,
images are `{bytes, path}` mappings. Masks are absent for observed real and
full-synthetic records and encoded mappings for observed tampered records.

The verified native mapping is 0=real, 1=full synthetic, and 2=tampered. The
binary core adapter maps these to `real`, `fake`, and `skip` respectively. The
smoke configuration enforces a 50-source-record ceiling and a 10-image target.

Before opening the stream, the collector resolves the configured symbolic
Hugging Face revision (currently `main`) to an immutable dataset commit SHA. It
uses that SHA for `load_dataset` and records both the requested and resolved
revisions in collection provenance; resolution failure stops the run.

A bounded revision check on 2026-08-27 resolved `main` to
`dc03ead57929879319ce30a82bfcfb8d317b10bd`. It examined five source records,
accepted one real and one full-synthetic image, skipped one tampered record and
two additional synthetic records after their quota was filled. Its disposable
output remains under `data/experiments/sid-set/smoke/`; no SID-Set data has been
promoted here.
