#!/usr/bin/env python3
"""Maintainer-only, one-time human-training assignment generation."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sensifake_annotation.human_train_assignment import (
    DEFAULT_OUTPUT,
    DEFAULT_TASKS,
    assignment_files,
    build_human_train_assignment,
    write_assignment_files,
)
from sensifake_annotation.paths import gold_silver_assignment_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run once as maintainer: assign 300 unassigned images to exactly three "
        "annotators (100 each), writing an immutable master and three blinded tasks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--annotators",
        nargs=3,
        required=True,
        metavar=("ID1", "ID2", "ID3"),
        help="Three distinct IDs: ASCII letters/digits, underscores or hyphens.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=gold_silver_assignment_path(),
        help="Existing Gold/Silver assignment; never modified.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Master CSV.")
    parser.add_argument(
        "--tasks-dir", type=Path, default=DEFAULT_TASKS, help="Blinded task directory."
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic selection/order seed.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts, all planned assignments and SHA-256; write nothing.",
    )
    args = parser.parse_args(argv)
    try:
        rows = build_human_train_assignment(args.annotators, input_path=args.input, seed=args.seed)
        files = assignment_files(rows, output=args.output, tasks_dir=args.tasks_dir)
        status = "dry-run" if args.dry_run else write_assignment_files(files, input_path=args.input)
    except (ValueError, OSError) as exc:
        print(f"Human-train assignment error: {exc}", file=sys.stderr)
        return 1
    print(
        f"Status: {status}; seed: {args.seed}; images: {len(rows)}; unique hashes: "
        f"{len({r['content_hash'] for r in rows})}"
    )
    for strata, count in sorted(
        Counter((r["source_dataset"], r["normalized_label"]) for r in rows).items()
    ):
        print(f"{strata}: {count}")
    for annotator in sorted(args.annotators):
        selected = [r for r in rows if r["annotator_id"] == annotator]
        print(
            f"{annotator}: {len(selected)} images; "
            + str(dict(Counter((r["source_dataset"], r["normalized_label"]) for r in selected)))
        )
    for path, payload in files.items():
        print(f"SHA-256 {path}: {hashlib.sha256(payload).hexdigest()}")
    if args.dry_run:
        print(files[args.output].decode(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
