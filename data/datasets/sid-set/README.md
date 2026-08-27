# SID-Set placeholder

No SID-Set data has been collected. A future smoke test will use
`configs/sources/sid_set.toml` and write first to `data/experiments/sid-set/`;
only a separately validated result may later be promoted into this directory.

The mocked adapter assumes the live `train` split has `img_id`, `image`,
`mask`, and integer `label` fields, and that Hugging Face exposes `image` as its
standard image feature (encoded bytes or a provider path after decoding is
disabled). The named config is currently left empty. Confirm those assumptions
with a bounded live smoke test before collecting.
