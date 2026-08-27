"""Repository path resolution shared by the annotation app and tests."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def canonical_openfake_manifest(repository_root: Path = REPOSITORY_ROOT) -> Path:
    """Return the canonical OpenFake pilot manifest path."""
    return repository_root / "data/datasets/openfake/pilot-600/manifest.jsonl"


def openfake_development_annotations(repository_root: Path = REPOSITORY_ROOT) -> Path:
    """Return the writable OpenFake development-v0 annotation CSV path."""
    return (
        repository_root
        / "annotations/openfake/development-v0/sensitivity_annotations.csv"
    )
