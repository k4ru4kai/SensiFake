"""Repository path contracts for canonical data and annotations."""

from pathlib import Path

from sensifake_annotation import (
    canonical_openfake_manifest,
    openfake_development_annotations,
)


def test_canonical_openfake_data_path_resolution(tmp_path: Path) -> None:
    assert canonical_openfake_manifest(tmp_path) == (
        tmp_path / "data/datasets/openfake/pilot-600/manifest.jsonl"
    )
    assert canonical_openfake_manifest().is_file()


def test_openfake_annotation_path_resolution(tmp_path: Path) -> None:
    assert openfake_development_annotations(tmp_path) == (
        tmp_path
        / "annotations/openfake/development-v0/sensitivity_annotations.csv"
    )
    assert openfake_development_annotations().is_file()
