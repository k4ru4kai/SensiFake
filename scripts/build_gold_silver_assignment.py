#!/usr/bin/env python3
"""Build deterministic canonical Gold/Silver split assignment file."""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sensifake_annotation import (
    ROLE_GOLD_DEVELOPMENT,
    ROLE_GOLD_TEST,
    ROLE_UNASSIGNED,
    AssignmentConflictError,
    AssignmentError,
    build_gold_silver_assignment,
    canonical_openfake_additional_manifest,
    canonical_openfake_pilot_manifest,
    canonical_sid_set_manifest,
    gold_silver_assignment_path,
    openfake_development_annotations,
    source_group_for_dataset,
    write_gold_silver_assignment,
)

LOGGER = logging.getLogger("sensifake.splits")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Construct deterministic canonical Gold/Silver split assignment file."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic randomization seed for Gold test selection (default: 42).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=gold_silver_assignment_path(),
        help="Target CSV output path (default: annotations/splits/gold_silver_assignment.csv).",
    )
    parser.add_argument(
        "--pilot-manifest",
        type=Path,
        default=canonical_openfake_pilot_manifest(),
        help="Path to OpenFake pilot manifest (default: data/datasets/openfake/pilot-600/manifest.jsonl).",
    )
    parser.add_argument(
        "--additional-manifest",
        type=Path,
        default=canonical_openfake_additional_manifest(),
        help="Path to OpenFake additional-900 manifest (default: data/datasets/openfake/additional-900/manifest.jsonl).",
    )
    parser.add_argument(
        "--sid-set-manifest",
        type=Path,
        default=canonical_sid_set_manifest(),
        help="Path to SID-Set candidate-1500 manifest (default: data/datasets/sid-set/candidate-1500/manifest.jsonl).",
    )
    parser.add_argument(
        "--development-annotations",
        type=Path,
        default=openfake_development_annotations(),
        help="Path to existing development sensitivity annotations CSV.",
    )
    return parser.parse_args(argv)


def compute_file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_arguments(argv)

    try:
        records = build_gold_silver_assignment(
            pilot_manifest_path=args.pilot_manifest,
            additional_manifest_path=args.additional_manifest,
            sid_set_manifest_path=args.sid_set_manifest,
            development_annotations_path=args.development_annotations,
            seed=args.seed,
        )
        action = write_gold_silver_assignment(args.output, records)
    except AssignmentConflictError as exc:
        LOGGER.error("Assignment conflict: %s", exc)
        return 1
    except AssignmentError as exc:
        LOGGER.error("Assignment failed validation: %s", exc)
        return 1
    except Exception:
        LOGGER.exception("Unexpected error during assignment construction")
        return 1

    file_sha256 = compute_file_sha256(args.output)
    role_counts = Counter(r.role for r in records)
    test_records = [r for r in records if r.role == ROLE_GOLD_TEST]
    test_strata = Counter(
        (source_group_for_dataset(r.source_dataset), r.normalized_label) for r in test_records
    )

    print("==================================================")
    print(f"Gold/Silver Assignment Status: {action.upper()}")
    print(f"Output File: {args.output}")
    print(f"SHA-256: {file_sha256}")
    print(f"Split Seed: {args.seed}")
    print("--------------------------------------------------")
    print(f"Total Records: {len(records)}")
    print(f"  - {ROLE_GOLD_DEVELOPMENT}: {role_counts[ROLE_GOLD_DEVELOPMENT]}")
    print(f"  - {ROLE_GOLD_TEST}: {role_counts[ROLE_GOLD_TEST]}")
    print(f"  - {ROLE_UNASSIGNED}: {role_counts[ROLE_UNASSIGNED]}")
    print("--------------------------------------------------")
    print("Gold Test Strata Breakdown:")
    print(f"  - OpenFake real: {test_strata[('OpenFake', 'real')]}")
    print(f"  - OpenFake fake: {test_strata[('OpenFake', 'fake')]}")
    print(f"  - SID-Set real: {test_strata[('SID-Set', 'real')]}")
    print(f"  - SID-Set fake: {test_strata[('SID-Set', 'fake')]}")
    print("==================================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
