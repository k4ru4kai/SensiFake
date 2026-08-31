"""Repository path contracts for canonical data and annotations."""

from pathlib import Path

from sensifake_annotation import (
    canonical_openfake_additional_manifest,
    canonical_openfake_manifest,
    canonical_openfake_pilot_manifest,
    canonical_sid_set_manifest,
    gold_silver_assignment_path,
    openfake_development_annotations,
)


def test_canonical_openfake_data_path_resolution(tmp_path: Path) -> None:
    assert canonical_openfake_manifest(tmp_path) == (
        tmp_path / "data/datasets/openfake/pilot-600/manifest.jsonl"
    )
    assert canonical_openfake_pilot_manifest(tmp_path) == (
        tmp_path / "data/datasets/openfake/pilot-600/manifest.jsonl"
    )
    assert canonical_openfake_manifest().is_file()
    assert canonical_openfake_pilot_manifest().is_file()


def test_canonical_additional_openfake_data_path_resolution(tmp_path: Path) -> None:
    assert canonical_openfake_additional_manifest(tmp_path) == (
        tmp_path / "data/datasets/openfake/additional-900/manifest.jsonl"
    )
    assert canonical_openfake_additional_manifest().is_file()


def test_canonical_sid_set_data_path_resolution(tmp_path: Path) -> None:
    assert canonical_sid_set_manifest(tmp_path) == (
        tmp_path / "data/datasets/sid-set/candidate-1500/manifest.jsonl"
    )
    assert canonical_sid_set_manifest().is_file()


def test_openfake_annotation_path_resolution(tmp_path: Path) -> None:
    assert openfake_development_annotations(tmp_path) == (
        tmp_path / "annotations/openfake/development-v0/sensitivity_annotations.csv"
    )
    assert openfake_development_annotations().is_file()


def test_gold_silver_assignment_path_resolution(tmp_path: Path) -> None:
    assert gold_silver_assignment_path(tmp_path) == (
        tmp_path / "annotations/splits/gold_silver_assignment.csv"
    )
    assert gold_silver_assignment_path().is_file()
