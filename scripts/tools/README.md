# Repository tools

Maintenance utilities for migrations, data preparation, conversions, and
administrative validation live here. They are run explicitly from the repository
root; they are not part of the Streamlit application.

See [the annotation migration guide](../../docs/annotation.md) before running
`migrate_annotations_to_sqlite.py` on real annotation files.

`review_snapshots.py create|inspect|merge` supports asynchronous review handoffs.
Create registers an issued snapshot in the master; merge appends validated reviews.
