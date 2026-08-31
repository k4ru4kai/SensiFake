"""Deterministic Gold/Silver split assignment generation and validation."""

from __future__ import annotations

import csv
import json
import os
import random
import re
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .paths import (
    canonical_openfake_additional_manifest,
    canonical_openfake_pilot_manifest,
    canonical_sid_set_manifest,
    openfake_development_annotations,
)

ASSIGNMENT_FIELDS: tuple[str, ...] = (
    "content_hash",
    "source_dataset",
    "component",
    "normalized_label",
    "relative_image_path",
    "role",
    "split_seed",
)

ROLE_GOLD_DEVELOPMENT = "gold_development"
ROLE_GOLD_TEST = "gold_test"
ROLE_UNASSIGNED = "unassigned"
VALID_ROLES: frozenset[str] = frozenset({ROLE_GOLD_DEVELOPMENT, ROLE_GOLD_TEST, ROLE_UNASSIGNED})

COMPONENT_OPENFAKE_PILOT = "openfake_pilot_600"
COMPONENT_OPENFAKE_ADDITIONAL = "openfake_additional_900"
COMPONENT_SID_SET_CANDIDATE = "sid_set_candidate_1500"
VALID_COMPONENTS: frozenset[str] = frozenset(
    {
        COMPONENT_OPENFAKE_PILOT,
        COMPONENT_OPENFAKE_ADDITIONAL,
        COMPONENT_SID_SET_CANDIDATE,
    }
)

SOURCE_DATASET_OPENFAKE = "ComplexDataLab/OpenFake"
SOURCE_DATASET_SID_SET = "saberzl/SID_Set"
SOURCE_GROUP_OPENFAKE = "OpenFake"
SOURCE_GROUP_SID_SET = "SID-Set"
SOURCE_GROUP_MAP: dict[str, str] = {
    SOURCE_DATASET_OPENFAKE: SOURCE_GROUP_OPENFAKE,
    SOURCE_DATASET_SID_SET: SOURCE_GROUP_SID_SET,
}

STRATA_ORDER: tuple[tuple[str, str], ...] = (
    (SOURCE_GROUP_OPENFAKE, "real"),
    (SOURCE_GROUP_OPENFAKE, "fake"),
    (SOURCE_GROUP_SID_SET, "real"),
    (SOURCE_GROUP_SID_SET, "fake"),
)

EXPECTED_TOTAL_RECORDS = 3000
EXPECTED_ROLE_COUNTS: dict[str, int] = {
    ROLE_GOLD_DEVELOPMENT: 101,
    ROLE_GOLD_TEST: 200,
    ROLE_UNASSIGNED: 2699,
}
EXPECTED_STRATA_TEST_COUNTS: dict[tuple[str, str], int] = {
    (SOURCE_GROUP_OPENFAKE, "real"): 50,
    (SOURCE_GROUP_OPENFAKE, "fake"): 50,
    (SOURCE_GROUP_SID_SET, "real"): 50,
    (SOURCE_GROUP_SID_SET, "fake"): 50,
}
EXPECTED_COMPONENT_COUNTS: dict[str, int] = {
    COMPONENT_OPENFAKE_PILOT: 600,
    COMPONENT_OPENFAKE_ADDITIONAL: 900,
    COMPONENT_SID_SET_CANDIDATE: 1500,
}
EXPECTED_LABEL_COUNTS: dict[str, int] = {"real": 1500, "fake": 1500}
EXPECTED_SOURCE_COUNTS: dict[str, int] = {
    SOURCE_GROUP_OPENFAKE: 1500,
    SOURCE_GROUP_SID_SET: 1500,
}

CONTENT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AssignmentError(ValueError):
    """Base error for assignment generation or validation failures."""


class AssignmentConflictError(AssignmentError):
    """Raised when an existing assignment file conflicts with the computed assignment."""


class AssignmentValidationError(AssignmentError):
    """Raised when data fails pre- or post-assignment validation."""


@dataclass(frozen=True)
class AssignmentRecord:
    """A canonical assignment record for a single image."""

    content_hash: str
    source_dataset: str
    component: str
    normalized_label: str
    relative_image_path: str
    role: str
    split_seed: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def source_group_for_dataset(source_dataset: str) -> str:
    """Map source_dataset identifier to source group (OpenFake or SID-Set)."""
    group = SOURCE_GROUP_MAP.get(source_dataset)
    if group is None:
        raise AssignmentValidationError(
            f"unknown source_dataset: {source_dataset!r}, expected one of {list(SOURCE_GROUP_MAP.keys())}"
        )
    return group


def load_manifest_records(manifest_path: Path, component: str) -> list[dict[str, Any]]:
    """Load JSONL manifest records and validate required fields."""
    resolved_path = manifest_path.resolve()
    if not resolved_path.is_file():
        raise AssignmentValidationError(f"manifest file is missing: {resolved_path}")
    if component not in VALID_COMPONENTS:
        raise AssignmentValidationError(
            f"invalid component {component!r}, expected one of {sorted(VALID_COMPONENTS)}"
        )

    records: list[dict[str, Any]] = []
    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                row = json.loads(stripped)
                if not isinstance(row, dict):
                    raise AssignmentValidationError(
                        f"manifest row {line_number} in {resolved_path} is not a JSON object"
                    )
                content_hash = row.get("content_hash")
                source_dataset = row.get("source_dataset")
                normalized_label = row.get("normalized_label")
                relative_image_path = row.get("relative_image_path")

                if not isinstance(content_hash, str) or not CONTENT_HASH_PATTERN.match(
                    content_hash
                ):
                    raise AssignmentValidationError(
                        f"manifest row {line_number} in {resolved_path} has invalid content_hash: {content_hash!r}"
                    )
                if not isinstance(source_dataset, str) or source_dataset not in SOURCE_GROUP_MAP:
                    raise AssignmentValidationError(
                        f"manifest row {line_number} in {resolved_path} has invalid source_dataset: {source_dataset!r}"
                    )
                if normalized_label not in ("real", "fake"):
                    raise AssignmentValidationError(
                        f"manifest row {line_number} in {resolved_path} has invalid normalized_label: {normalized_label!r}"
                    )
                if not isinstance(relative_image_path, str) or not relative_image_path:
                    raise AssignmentValidationError(
                        f"manifest row {line_number} in {resolved_path} has invalid relative_image_path"
                    )

                record = dict(row)
                record["component"] = component
                records.append(record)
    except (OSError, json.JSONDecodeError) as exc:
        raise AssignmentValidationError(
            f"could not load manifest from {resolved_path}: {exc}"
        ) from exc

    return records


def load_development_hashes(annotations_path: Path) -> set[str]:
    """Load and validate the 101 existing human development annotation hashes."""
    resolved_path = annotations_path.resolve()
    if not resolved_path.is_file():
        raise AssignmentValidationError(f"annotations file is missing: {resolved_path}")

    hashes: set[str] = set()
    try:
        with resolved_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "content_hash" not in reader.fieldnames:
                raise AssignmentValidationError(
                    f"annotations file {resolved_path} lacks 'content_hash' column"
                )
            for row_number, row in enumerate(reader, start=2):
                content_hash = (row.get("content_hash") or "").strip()
                if not CONTENT_HASH_PATTERN.match(content_hash):
                    raise AssignmentValidationError(
                        f"invalid content_hash at row {row_number} in {resolved_path}: {content_hash!r}"
                    )
                if content_hash in hashes:
                    raise AssignmentValidationError(
                        f"duplicate content_hash at row {row_number} in {resolved_path}: {content_hash!r}"
                    )
                hashes.add(content_hash)
    except OSError as exc:
        raise AssignmentValidationError(
            f"could not read annotations from {resolved_path}: {exc}"
        ) from exc

    if len(hashes) != EXPECTED_ROLE_COUNTS[ROLE_GOLD_DEVELOPMENT]:
        raise AssignmentValidationError(
            f"expected exactly {EXPECTED_ROLE_COUNTS[ROLE_GOLD_DEVELOPMENT]} development annotations, found {len(hashes)}"
        )
    return hashes


def build_gold_silver_assignment(
    *,
    pilot_manifest_path: Path | None = None,
    additional_manifest_path: Path | None = None,
    sid_set_manifest_path: Path | None = None,
    development_annotations_path: Path | None = None,
    seed: int = 42,
) -> tuple[AssignmentRecord, ...]:
    """Deterministically construct and validate the 3,000-image Gold/Silver assignment."""
    pilot_manifest = pilot_manifest_path or canonical_openfake_pilot_manifest()
    additional_manifest = additional_manifest_path or canonical_openfake_additional_manifest()
    sid_set_manifest = sid_set_manifest_path or canonical_sid_set_manifest()
    dev_annotations = development_annotations_path or openfake_development_annotations()

    pilot_records = load_manifest_records(pilot_manifest, COMPONENT_OPENFAKE_PILOT)
    additional_records = load_manifest_records(additional_manifest, COMPONENT_OPENFAKE_ADDITIONAL)
    sid_records = load_manifest_records(sid_set_manifest, COMPONENT_SID_SET_CANDIDATE)
    dev_hashes = load_development_hashes(dev_annotations)

    # 1. Validate component-level record counts
    if len(pilot_records) != EXPECTED_COMPONENT_COUNTS[COMPONENT_OPENFAKE_PILOT]:
        raise AssignmentValidationError(
            f"pilot manifest has {len(pilot_records)} records, expected {EXPECTED_COMPONENT_COUNTS[COMPONENT_OPENFAKE_PILOT]}"
        )
    if len(additional_records) != EXPECTED_COMPONENT_COUNTS[COMPONENT_OPENFAKE_ADDITIONAL]:
        raise AssignmentValidationError(
            f"additional manifest has {len(additional_records)} records, expected {EXPECTED_COMPONENT_COUNTS[COMPONENT_OPENFAKE_ADDITIONAL]}"
        )
    if len(sid_records) != EXPECTED_COMPONENT_COUNTS[COMPONENT_SID_SET_CANDIDATE]:
        raise AssignmentValidationError(
            f"sid-set manifest has {len(sid_records)} records, expected {EXPECTED_COMPONENT_COUNTS[COMPONENT_SID_SET_CANDIDATE]}"
        )

    all_raw_records = pilot_records + additional_records + sid_records
    if len(all_raw_records) != EXPECTED_TOTAL_RECORDS:
        raise AssignmentValidationError(
            f"total manifest records {len(all_raw_records)} != {EXPECTED_TOTAL_RECORDS}"
        )

    # 2. Validate global uniqueness of content hashes
    all_hashes = [r["content_hash"] for r in all_raw_records]
    unique_hashes = set(all_hashes)
    if len(unique_hashes) != EXPECTED_TOTAL_RECORDS:
        raise AssignmentValidationError(
            f"duplicate content hashes detected: {len(all_hashes)} records, {len(unique_hashes)} unique hashes"
        )

    # 3. Validate label balance and source distribution
    label_counts = Counter(r["normalized_label"] for r in all_raw_records)
    if label_counts != EXPECTED_LABEL_COUNTS:
        raise AssignmentValidationError(
            f"manifest labels unbalanced: {dict(label_counts)}, expected {EXPECTED_LABEL_COUNTS}"
        )

    source_counts = Counter(source_group_for_dataset(r["source_dataset"]) for r in all_raw_records)
    if source_counts != EXPECTED_SOURCE_COUNTS:
        raise AssignmentValidationError(
            f"manifest sources unbalanced: {dict(source_counts)}, expected {EXPECTED_SOURCE_COUNTS}"
        )

    # 4. Validate that all 101 dev hashes exist in the pilot manifest
    pilot_hash_set = {r["content_hash"] for r in pilot_records}
    missing_dev = dev_hashes - pilot_hash_set
    if missing_dev:
        raise AssignmentValidationError(
            f"{len(missing_dev)} development hashes are not present in the OpenFake pilot manifest"
        )

    # 5. Deterministic stratified selection for gold_test
    # Strata candidate pool: records not in gold_development
    strata_candidates: dict[tuple[str, str], list[str]] = {stratum: [] for stratum in STRATA_ORDER}
    for record in all_raw_records:
        h = record["content_hash"]
        if h in dev_hashes:
            continue
        group = source_group_for_dataset(record["source_dataset"])
        label = record["normalized_label"]
        strata_candidates[(group, label)].append(h)

    rng = random.Random(seed)
    gold_test_hashes: set[str] = set()
    for stratum in STRATA_ORDER:
        candidates = sorted(strata_candidates[stratum])
        target_count = EXPECTED_STRATA_TEST_COUNTS[stratum]
        if len(candidates) < target_count:
            raise AssignmentValidationError(
                f"insufficient candidates for stratum {stratum}: available {len(candidates)}, required {target_count}"
            )
        sampled = rng.sample(candidates, target_count)
        gold_test_hashes.update(sampled)

    if len(gold_test_hashes) != EXPECTED_ROLE_COUNTS[ROLE_GOLD_TEST]:
        raise AssignmentValidationError(
            f"gold_test set size {len(gold_test_hashes)} != {EXPECTED_ROLE_COUNTS[ROLE_GOLD_TEST]}"
        )

    if gold_test_hashes & dev_hashes:
        raise AssignmentValidationError("gold_test selection overlaps with gold_development hashes")

    # 6. Construct assignment records
    assignment_records: list[AssignmentRecord] = []
    for r in all_raw_records:
        h = r["content_hash"]
        if h in dev_hashes:
            role = ROLE_GOLD_DEVELOPMENT
        elif h in gold_test_hashes:
            role = ROLE_GOLD_TEST
        else:
            role = ROLE_UNASSIGNED

        assignment_records.append(
            AssignmentRecord(
                content_hash=h,
                source_dataset=r["source_dataset"],
                component=r["component"],
                normalized_label=r["normalized_label"],
                relative_image_path=r["relative_image_path"],
                role=role,
                split_seed=seed,
            )
        )

    # 7. Sort canonically by content_hash
    assignment_records.sort(key=lambda rec: rec.content_hash)
    result_tuple = tuple(assignment_records)

    # 8. Post-validation
    validate_assignment_records(result_tuple, dev_hashes=dev_hashes, seed=seed)

    return result_tuple


def validate_assignment_records(
    records: Sequence[AssignmentRecord],
    *,
    dev_hashes: set[str] | None = None,
    seed: int | None = None,
) -> None:
    """Thoroughly validate an assignment sequence against all protocol constraints."""
    if len(records) != EXPECTED_TOTAL_RECORDS:
        raise AssignmentValidationError(
            f"assignment has {len(records)} records, expected {EXPECTED_TOTAL_RECORDS}"
        )

    hashes = [r.content_hash for r in records]
    unique_hashes = set(hashes)
    if len(unique_hashes) != EXPECTED_TOTAL_RECORDS:
        raise AssignmentValidationError(
            f"assignment contains duplicate content_hashes: {len(hashes)} records, {len(unique_hashes)} unique"
        )

    # Check valid values
    for index, r in enumerate(records, start=1):
        if not CONTENT_HASH_PATTERN.match(r.content_hash):
            raise AssignmentValidationError(
                f"record {index} has invalid content_hash: {r.content_hash!r}"
            )
        if r.source_dataset not in SOURCE_GROUP_MAP:
            raise AssignmentValidationError(
                f"record {index} has invalid source_dataset: {r.source_dataset!r}"
            )
        if r.component not in VALID_COMPONENTS:
            raise AssignmentValidationError(
                f"record {index} has invalid component: {r.component!r}"
            )
        if r.normalized_label not in ("real", "fake"):
            raise AssignmentValidationError(
                f"record {index} has invalid normalized_label: {r.normalized_label!r}"
            )
        if not r.relative_image_path:
            raise AssignmentValidationError(f"record {index} has empty relative_image_path")
        if r.role not in VALID_ROLES:
            raise AssignmentValidationError(f"record {index} has invalid role: {r.role!r}")
        if seed is not None and r.split_seed != seed:
            raise AssignmentValidationError(
                f"record {index} has split_seed {r.split_seed}, expected {seed}"
            )

    # Role counts
    role_counts = Counter(r.role for r in records)
    if role_counts != EXPECTED_ROLE_COUNTS:
        raise AssignmentValidationError(
            f"role counts {dict(role_counts)} do not match expected {EXPECTED_ROLE_COUNTS}"
        )

    # Strata breakdown for gold_test
    gold_test_records = [r for r in records if r.role == ROLE_GOLD_TEST]
    test_strata_counts = Counter(
        (source_group_for_dataset(r.source_dataset), r.normalized_label) for r in gold_test_records
    )
    if test_strata_counts != EXPECTED_STRATA_TEST_COUNTS:
        raise AssignmentValidationError(
            f"gold_test strata {dict(test_strata_counts)} != {EXPECTED_STRATA_TEST_COUNTS}"
        )

    # Dev hashes validation
    dev_records = [r for r in records if r.role == ROLE_GOLD_DEVELOPMENT]
    dev_record_hashes = {r.content_hash for r in dev_records}
    if dev_hashes is not None and dev_record_hashes != dev_hashes:
        raise AssignmentValidationError(
            "gold_development records do not match the expected development annotation hashes"
        )

    # Verify zero overlap between dev and test
    test_record_hashes = {r.content_hash for r in gold_test_records}
    if dev_record_hashes & test_record_hashes:
        raise AssignmentValidationError(
            "overlap detected between gold_development and gold_test records"
        )

    # Check overall label and source distribution
    label_counts = Counter(r.normalized_label for r in records)
    if label_counts != EXPECTED_LABEL_COUNTS:
        raise AssignmentValidationError(
            f"overall label counts {dict(label_counts)} != {EXPECTED_LABEL_COUNTS}"
        )

    source_counts = Counter(source_group_for_dataset(r.source_dataset) for r in records)
    if source_counts != EXPECTED_SOURCE_COUNTS:
        raise AssignmentValidationError(
            f"overall source counts {dict(source_counts)} != {EXPECTED_SOURCE_COUNTS}"
        )


def serialize_assignment_csv(records: Sequence[AssignmentRecord]) -> str:
    """Serialize assignment records to a standard CSV string."""
    rows: list[str] = [",".join(ASSIGNMENT_FIELDS)]
    for r in records:
        rows.append(
            f"{r.content_hash},{r.source_dataset},{r.component},{r.normalized_label},{r.relative_image_path},{r.role},{r.split_seed}"
        )
    return "\n".join(rows) + "\n"


def load_assignment_csv(path: Path) -> list[AssignmentRecord]:
    """Load, validate, and return assignment records from a CSV file."""
    resolved_path = path.resolve()
    if not resolved_path.is_file():
        raise AssignmentValidationError(f"assignment CSV file is missing: {resolved_path}")

    records: list[AssignmentRecord] = []
    try:
        with resolved_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != ASSIGNMENT_FIELDS:
                raise AssignmentValidationError(
                    f"assignment CSV header in {resolved_path} does not match required schema: {reader.fieldnames}"
                )
            for row_number, row in enumerate(reader, start=2):
                try:
                    record = AssignmentRecord(
                        content_hash=row["content_hash"],
                        source_dataset=row["source_dataset"],
                        component=row["component"],
                        normalized_label=row["normalized_label"],
                        relative_image_path=row["relative_image_path"],
                        role=row["role"],
                        split_seed=int(row["split_seed"]),
                    )
                except (KeyError, ValueError) as exc:
                    raise AssignmentValidationError(
                        f"invalid row {row_number} in {resolved_path}: {exc}"
                    ) from exc
                records.append(record)
    except OSError as exc:
        raise AssignmentValidationError(
            f"could not read assignment CSV at {resolved_path}: {exc}"
        ) from exc

    validate_assignment_records(records)
    return records


def write_gold_silver_assignment(
    output_path: Path,
    records: Sequence[AssignmentRecord],
) -> str:
    """Atomically write assignment records or verify identical content if already present.

    Returns:
        'created' if a new file was written.
        'verified_identical' if the existing file matched byte-for-byte.

    Raises:
        AssignmentConflictError if an existing file differs from the generated records.
    """
    serialized = serialize_assignment_csv(records)
    target_path = output_path.resolve()

    if target_path.exists():
        try:
            existing_content = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AssignmentValidationError(
                f"could not read existing assignment file at {target_path}: {exc}"
            ) from exc

        if existing_content == serialized:
            return "verified_identical"

        raise AssignmentConflictError(
            f"existing assignment file at {target_path} differs from the computed deterministic assignment; refusing to overwrite"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_file = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_file, target_path)
        temp_file = None
    finally:
        if temp_file is not None:
            temp_file.unlink(missing_ok=True)

    return "created"
