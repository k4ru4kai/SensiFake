"""Create, inspect, and merge portable review snapshots."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.annotation.annotation_schema import AnnotationError
from scripts.annotation.paths import REPOSITORY_ROOT
from scripts.annotation.review_snapshots import create_snapshot, inspect_snapshot, merge_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    master = REPOSITORY_ROOT / "annotations/master/sensifake.sqlite3"
    create = commands.add_parser("create", help="Register and create a full review snapshot")
    create.add_argument("--master", type=Path, default=master)
    create.add_argument(
        "--output-dir", type=Path, default=REPOSITORY_ROOT / "annotations/packages/outgoing"
    )
    inspect = commands.add_parser(
        "inspect", help="Validate a snapshot; add --master to verify lineage and plan"
    )
    inspect.add_argument("snapshot", type=Path)
    inspect.add_argument("--master", type=Path)
    merge = commands.add_parser("merge", help="Atomically import legitimate new review events")
    merge.add_argument("snapshot", type=Path)
    merge.add_argument("--master", type=Path, default=master)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = {"snapshot": str(create_snapshot(args.master, args.output_dir))}
        elif args.command == "inspect":
            result = inspect_snapshot(args.snapshot, args.master)
        else:
            result = merge_snapshot(args.master, args.snapshot)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (AnnotationError, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f"Review handoff failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
