"""Focused tests for canonical Gold/Silver split assignment and verification."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from scripts.legacy.gold_silver_assignment import (
    COMPONENT_OPENFAKE_ADDITIONAL,
    COMPONENT_OPENFAKE_PILOT,
    COMPONENT_SID_SET_CANDIDATE,
    ROLE_GOLD_DEVELOPMENT,
    ROLE_GOLD_TEST,
    ROLE_UNASSIGNED,
    SOURCE_DATASET_OPENFAKE,
    AssignmentConflictError,
    AssignmentRecord,
    AssignmentValidationError,
    build_gold_silver_assignment,
    load_assignment_csv,
    load_development_hashes,
    source_group_for_dataset,
    validate_assignment_records,
    write_gold_silver_assignment,
)
from scripts.annotation.paths import (
    gold_silver_assignment_path,
    openfake_development_annotations,
)

CANONICAL_SPLIT_SHA256 = "7710f0347708ca604a0b90e5a7ba9531f0778fcf055c3c525e9b5ebba9793b02"


def compute_file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def test_canonical_assignment_file_on_disk_matches_expected_sha256() -> None:
    path = gold_silver_assignment_path()
    assert path.is_file()
    assert compute_file_sha256(path) == CANONICAL_SPLIT_SHA256


def test_deterministic_selection_for_seed_42() -> None:
    first = build_gold_silver_assignment(seed=42)
    second = build_gold_silver_assignment(seed=42)
    assert first == second

    # Different seed yields different gold_test set but identical gold_development
    different_seed = build_gold_silver_assignment(seed=43)
    first_test_hashes = {r.content_hash for r in first if r.role == ROLE_GOLD_TEST}
    diff_test_hashes = {r.content_hash for r in different_seed if r.role == ROLE_GOLD_TEST}
    assert first_test_hashes != diff_test_hashes

    first_dev_hashes = {r.content_hash for r in first if r.role == ROLE_GOLD_DEVELOPMENT}
    diff_dev_hashes = {r.content_hash for r in different_seed if r.role == ROLE_GOLD_DEVELOPMENT}
    assert first_dev_hashes == diff_dev_hashes


def test_exact_role_counts() -> None:
    records = build_gold_silver_assignment(seed=42)
    assert len(records) == 3000
    counts = Counter(r.role for r in records)
    assert counts[ROLE_GOLD_DEVELOPMENT] == 101
    assert counts[ROLE_GOLD_TEST] == 200
    assert counts[ROLE_UNASSIGNED] == 2699
    assert sum(counts.values()) == 3000


def test_exact_gold_test_source_label_strata() -> None:
    records = build_gold_silver_assignment(seed=42)
    test_records = [r for r in records if r.role == ROLE_GOLD_TEST]
    assert len(test_records) == 200

    strata = Counter(
        (source_group_for_dataset(r.source_dataset), r.normalized_label) for r in test_records
    )
    assert strata[("OpenFake", "real")] == 50
    assert strata[("OpenFake", "fake")] == 50
    assert strata[("SID-Set", "real")] == 50
    assert strata[("SID-Set", "fake")] == 50


def test_development_hashes_excluded_from_test() -> None:
    records = build_gold_silver_assignment(seed=42)
    dev_records = [r for r in records if r.role == ROLE_GOLD_DEVELOPMENT]
    test_records = [r for r in records if r.role == ROLE_GOLD_TEST]

    dev_hashes = {r.content_hash for r in dev_records}
    test_hashes = {r.content_hash for r in test_records}

    assert len(dev_hashes) == 101
    assert len(test_hashes) == 200
    assert dev_hashes.isdisjoint(test_hashes)

    expected_dev_hashes = load_development_hashes(openfake_development_annotations())
    assert dev_hashes == expected_dev_hashes

    # All gold_development records must come from pilot-600
    assert all(r.component == COMPONENT_OPENFAKE_PILOT for r in dev_records)
    assert all(r.source_dataset == SOURCE_DATASET_OPENFAKE for r in dev_records)


def test_no_duplicate_content_hash() -> None:
    records = build_gold_silver_assignment(seed=42)
    hashes = [r.content_hash for r in records]
    assert len(hashes) == 3000
    assert len(set(hashes)) == 3000


def test_all_3000_records_represented() -> None:
    records = build_gold_silver_assignment(seed=42)
    comp_counts = Counter(r.component for r in records)
    assert comp_counts[COMPONENT_OPENFAKE_PILOT] == 600
    assert comp_counts[COMPONENT_OPENFAKE_ADDITIONAL] == 900
    assert comp_counts[COMPONENT_SID_SET_CANDIDATE] == 1500

    label_counts = Counter(r.normalized_label for r in records)
    assert label_counts["real"] == 1500
    assert label_counts["fake"] == 1500

    source_counts = Counter(source_group_for_dataset(r.source_dataset) for r in records)
    assert source_counts["OpenFake"] == 1500
    assert source_counts["SID-Set"] == 1500

    assert all(r.split_seed == 42 for r in records)


def test_relative_image_paths_exist_on_disk() -> None:
    records = build_gold_silver_assignment(seed=42)
    repo_root = gold_silver_assignment_path().parent.parent.parent

    component_roots = {
        COMPONENT_OPENFAKE_PILOT: repo_root / "data/datasets/openfake/pilot-600",
        COMPONENT_OPENFAKE_ADDITIONAL: repo_root / "data/datasets/openfake/additional-900",
        COMPONENT_SID_SET_CANDIDATE: repo_root / "data/datasets/sid-set/candidate-1500",
    }

    for r in records:
        component_dir = component_roots[r.component]
        image_file = component_dir / r.relative_image_path
        assert image_file.is_file(), f"Missing image file: {image_file}"


def test_rerun_idempotency_behavior(tmp_path: Path) -> None:
    records = build_gold_silver_assignment(seed=42)
    target_csv = tmp_path / "gold_silver_assignment.csv"

    # First write -> created
    action1 = write_gold_silver_assignment(target_csv, records)
    assert action1 == "created"
    assert target_csv.is_file()
    initial_content = target_csv.read_text(encoding="utf-8")

    # Second write with same data -> verified_identical
    action2 = write_gold_silver_assignment(target_csv, records)
    assert action2 == "verified_identical"
    assert target_csv.read_text(encoding="utf-8") == initial_content


def test_conflicting_existing_assignment_is_rejected(tmp_path: Path) -> None:
    records = build_gold_silver_assignment(seed=42)
    target_csv = tmp_path / "gold_silver_assignment.csv"
    write_gold_silver_assignment(target_csv, records)

    # Modify the existing file to create a conflict
    corrupted_content = target_csv.read_text(encoding="utf-8").replace("gold_test", "unassigned", 1)
    target_csv.write_text(corrupted_content, encoding="utf-8")

    with pytest.raises(
        AssignmentConflictError, match="differs from the computed deterministic assignment"
    ):
        write_gold_silver_assignment(target_csv, records)

    # Verify content was not overwritten
    assert target_csv.read_text(encoding="utf-8") == corrupted_content


def test_load_assignment_csv_roundtrip(tmp_path: Path) -> None:
    records = build_gold_silver_assignment(seed=42)
    target_csv = tmp_path / "assignment.csv"
    write_gold_silver_assignment(target_csv, records)

    loaded = load_assignment_csv(target_csv)
    assert loaded == list(records)


def test_validation_rejects_corrupted_records() -> None:
    records = list(build_gold_silver_assignment(seed=42))

    # Test count mismatch (<3000)
    with pytest.raises(AssignmentValidationError, match="assignment has 2999 records"):
        validate_assignment_records(records[:-1])

    # Test duplicate hash
    duplicated = [records[0]] + records[1:-1] + [records[0]]
    with pytest.raises(AssignmentValidationError, match="duplicate content_hashes"):
        validate_assignment_records(duplicated)

    # Test invalid role
    invalid_role_record = AssignmentRecord(
        content_hash=records[0].content_hash,
        source_dataset=records[0].source_dataset,
        component=records[0].component,
        normalized_label=records[0].normalized_label,
        relative_image_path=records[0].relative_image_path,
        role="invalid_role",
        split_seed=42,
    )
    with pytest.raises(AssignmentValidationError, match="invalid role"):
        validate_assignment_records([invalid_role_record] + records[1:])


def test_cli_script_execution(tmp_path: Path) -> None:
    target_csv = tmp_path / "splits" / "gold_silver_assignment.csv"
    cmd = [
        sys.executable,
        "scripts/legacy/build_gold_silver_assignment.py",
        "--output",
        str(target_csv),
        "--seed",
        "42",
    ]

    # 1. First run creates the assignment
    proc1 = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc1.returncode == 0
    assert "CREATED" in proc1.stdout
    assert target_csv.is_file()
    assert compute_file_sha256(target_csv) == CANONICAL_SPLIT_SHA256

    # 2. Second run is idempotent
    proc2 = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc2.returncode == 0
    assert "VERIFIED_IDENTICAL" in proc2.stdout

    # 3. Conflicting run fails with exit code 1
    target_csv.write_text("corrupted content", encoding="utf-8")
    proc3 = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc3.returncode == 1
    assert "Assignment conflict" in proc3.stderr
