"""Validate explicit annotation exports and build a new SharedStore database."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.annotation.annotation_database import (
    EXPORT_FIELDS,
    RUBRIC_FIELDS,
    SharedStore,
    identity,
)
from scripts.annotation.annotation_schema import (
    ANNOTATION_FIELDS,
    AnnotationError,
    _annotation_from_row,
    load_annotations,
)
from scripts.annotation.import_batches import safe_archive_path, validate_image
from scripts.legacy.human_train_assignment import COMPONENT_PATHS

ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIELDS = (*ANNOTATION_FIELDS, "component", "relative_image_path", "source_dataset",
                 "normalized_label", "dataset_role", "annotator_id")
COUNTS = (
    "original_annotations", "unique_content_hashes", "review_events_imported",
    "unique_reviewed_images", "awaiting_review", "confirm_actions", "correct_actions",
    "images_with_multiple_reviews", "unknown_hashes", "missing_annotations",
    "current_state_conflicts", "confirmed_state_conflicts", "invalid_review_chains",
)


@dataclass(frozen=True)
class Inputs:
    annotations: Path
    review_current: Path
    review_confirmed: Path
    review_history: Path
    output: Path = ROOT / "annotations/master/sensifake.sqlite3"
    repository_root: Path = ROOT
    annotator_csvs: tuple[Path, ...] = ()
    expected_annotations_sha256: str | None = None
    report_path: Path | None = None


@dataclass
class MigrationReport:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNTS, 0))
    input_sha256: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {**self.counts, "input_sha256": self.input_sha256}


class MigrationError(RuntimeError):
    def __init__(self, message: str, report: MigrationReport):
        super().__init__(message)
        self.report = report


def _fail(report: MigrationReport, message: str, category: str | None = None,
          count: int = 1) -> None:
    if category:
        report.counts[category] += count
    raise MigrationError(message, report)


def _csv_rows(path: Path, report: MigrationReport, required: tuple[str, ...],
              *, exact_header: bool = False) -> list[dict[str, str]]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        header = tuple(reader.fieldnames or ())
        if len(header) != len(set(header)) or (
            header != required if exact_header else not set(required).issubset(header)
        ):
            _fail(report, f"Unexpected CSV header in {path}: {header}")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            _fail(report, f"Malformed CSV row in {path}")
        report.input_sha256[str(path)] = hashlib.sha256(raw).hexdigest()
        return rows
    except (OSError, UnicodeError, csv.Error) as exc:
        _fail(report, f"Cannot read CSV {path}: {exc}")


def _originals(inputs: Inputs, report: MigrationReport) -> tuple[list[dict], dict[str, dict]]:
    rows = _csv_rows(inputs.annotations, report, SOURCE_FIELDS)
    report.counts["original_annotations"] = len(rows)
    hashes = [row["content_hash"] for row in rows]
    report.counts["unique_content_hashes"] = len(set(hashes))
    if len(rows) != 401 or len(set(hashes)) != 401:
        _fail(report, "Exactly 401 rows with 401 unique original content_hash values are required")
    if inputs.expected_annotations_sha256 and (
        report.input_sha256[str(inputs.annotations)].lower()
        != inputs.expected_annotations_sha256.lower()
    ):
        _fail(report, "Original annotation CSV SHA-256 differs from the expected audit hash")

    batches = {
        role: {"batch_id": f"legacy-{role}", "name": f"Legacy {role}",
               "dataset_role": role, "images": []}
        for role in ("gold_development", "human_train")
    }
    originals = {}
    for number, row in enumerate(rows, 2):
        try:
            annotation = asdict(_annotation_from_row(row, number))
            content_hash = row["content_hash"]
            role = row["dataset_role"]
            if role not in batches:
                raise AnnotationError(f"Unknown dataset_role: {role}")
            identity(row["annotator_id"])
            if not row["source_dataset"] or row["normalized_label"] not in (
                "real", "fake", "unknown"
            ):
                raise AnnotationError("Invalid source_dataset or normalized_label")
            component = row["component"]
            if component not in COMPONENT_PATHS:
                raise AnnotationError(f"Unknown component: {component}")
            relative = safe_archive_path(row["relative_image_path"])
            component_root = (inputs.repository_root / COMPONENT_PATHS[component]).resolve()
            image_path = (component_root / relative).resolve()
            if not image_path.is_relative_to(component_root):
                raise AnnotationError("Image path escapes its component directory")
            image_bytes = image_path.read_bytes()
            if validate_image(image_bytes, relative) != content_hash:
                raise AnnotationError(f"Image bytes do not match content_hash: {content_hash}")
        except (AnnotationError, OSError, ValueError, KeyError) as exc:
            _fail(report, f"Original row {number}: {exc}")
        provenance = {key: value for key, value in row.items() if key not in ANNOTATION_FIELDS}
        provenance["label_source"] = row["source_dataset"]
        batches[role]["images"].append({
            "content_hash": content_hash, "image_bytes": image_bytes,
            "original_filename": f"{component}/{relative}", "provenance": provenance,
            "annotation": annotation, "annotator": row["annotator_id"],
        })
        originals[content_hash] = {"annotation": annotation, "annotator": row["annotator_id"]}
    if [len(batches[role]["images"]) for role in batches] != [101, 300]:
        _fail(report, "Original dataset roles must contain 101 gold_development and 300 human_train")
    return list(batches.values()), originals


def _annotator_audit(inputs: Inputs, originals: dict[str, dict], report: MigrationReport) -> None:
    seen = set()
    for path in inputs.annotator_csvs:
        _csv_rows(path, report, ANNOTATION_FIELDS, exact_header=True)
        try:
            annotations = load_annotations(path)
        except AnnotationError as exc:
            _fail(report, f"Invalid annotator CSV {path}: {exc}")
        for annotation in annotations:
            content_hash = annotation.content_hash
            if content_hash in seen or content_hash not in originals:
                _fail(report, f"Duplicate or unknown annotator CSV hash: {content_hash}")
            seen.add(content_hash)
            expected = originals[content_hash]["annotation"]
            # Task-specific blind IDs differ from the consolidated snapshot IDs.
            if any(getattr(annotation, key) != expected[key]
                   for key in ANNOTATION_FIELDS if key != "blind_id"):
                _fail(report, f"Annotator CSV disagrees with original: {content_hash}")


def _json_object(value: str, report: MigrationReport, description: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        _fail(report, f"Invalid JSON in {description}: {exc}")
    if not isinstance(parsed, dict):
        _fail(report, f"Expected a JSON object in {description}")
    return parsed


def _parse_time(value: str, report: MigrationReport, description: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed
    except ValueError as exc:
        _fail(report, f"Invalid reviewed_at in {description}: {exc}", "invalid_review_chains")


def _review_sources(inputs: Inputs, originals: dict[str, dict], report: MigrationReport
                    ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    current = _csv_rows(inputs.review_current, report, EXPORT_FIELDS, exact_header=True)
    confirmed = _csv_rows(inputs.review_confirmed, report, EXPORT_FIELDS, exact_header=True)
    history = _csv_rows(inputs.review_history, report, EXPORT_FIELDS, exact_header=True)
    report.counts["review_events_imported"] = len(history)
    reviewed_hashes = {row["content_hash"] for row in history}
    report.counts["unique_reviewed_images"] = len(reviewed_hashes)
    report.counts["awaiting_review"] = 401 - len(reviewed_hashes)
    report.counts["confirm_actions"] = sum(r["review_action"] == "confirm" for r in history)
    report.counts["correct_actions"] = sum(r["review_action"] == "correct" for r in history)
    counts = Counter(row["content_hash"] for row in history)
    report.counts["images_with_multiple_reviews"] = sum(n > 1 for n in counts.values())
    unknown = ({row["content_hash"] for row in (*current, *confirmed, *history)}
               - originals.keys())
    if unknown:
        _fail(report, f"Review exports contain unknown content_hash values: {sorted(unknown)[:5]}",
              "unknown_hashes", len(unknown))
    missing = originals.keys() - {row["content_hash"] for row in current}
    if missing:
        _fail(report, f"Current export omits {len(missing)} original annotations",
              "missing_annotations", len(missing))
    if len(current) != 401 or len({r["content_hash"] for r in current}) != 401:
        _fail(report, "Current export must contain one row for every original annotation",
              "current_state_conflicts")
    if len(confirmed) != len(reviewed_hashes) or (
        {r["content_hash"] for r in confirmed} != reviewed_hashes
    ):
        _fail(report, "Confirmed export membership differs from review history",
              "confirmed_state_conflicts")
    if len({r["content_hash"] for r in confirmed}) != len(confirmed):
        _fail(report, "Confirmed export contains duplicate image rows",
              "confirmed_state_conflicts")
    for source_name, rows in (("current", current), ("confirmed", confirmed),
                              ("history", history)):
        for number, row in enumerate(rows, 2):
            content_hash = row["content_hash"]
            expected = originals[content_hash]
            original_json = _json_object(row["original_annotation_json"], report,
                                         f"{source_name} row {number}")
            if original_json != expected["annotation"] or row["annotator"] != expected["annotator"]:
                _fail(report, f"{source_name} row {number} disagrees with original annotation",
                      "invalid_review_chains" if source_name == "history"
                      else f"{source_name}_state_conflicts")

    events = []
    ids = set()
    by_hash = defaultdict(list)
    for number, row in enumerate(history, 2):
        try:
            review_id = int(row["review_id"])
            if review_id <= 0 or review_id in ids or str(review_id) != row["review_id"]:
                raise ValueError("review_id must be a unique positive integer")
            ids.add(review_id)
            action = row["review_action"]
            if action not in ("confirm", "correct") or row["status"] != "confirmed":
                raise ValueError("invalid review action or status")
            reviewer_key, reviewer = identity(row["reviewer"])
            if reviewer != row["reviewer"] or reviewer_key == identity(
                originals[row["content_hash"]]["annotator"]
            )[0]:
                raise ValueError("invalid reviewer identity or self-review")
            if action == "correct" and not row["review_reason"].strip():
                raise ValueError("correction requires a reason")
            reviewed_at = _parse_time(row["reviewed_at"], report, f"history row {number}")
            payload = asdict(_annotation_from_row(row, number))
        except (AnnotationError, ValueError) as exc:
            _fail(report, f"Invalid history row {number}: {exc}", "invalid_review_chains")
        event = {"review_id": review_id, "content_hash": row["content_hash"],
                 "reviewer_key": reviewer_key, "reviewer": reviewer,
                 "reviewed_at": row["reviewed_at"], "action": action,
                 "reason": row["review_reason"], "payload": payload,
                 "parsed_at": reviewed_at}
        events.append(event)
        by_hash[row["content_hash"]].append(event)
    for content_hash, chain in by_hash.items():
        previous = originals[content_hash]["annotation"]
        previous_time = None
        for event in sorted(chain, key=lambda e: e["review_id"]):
            payload = event["payload"]
            if previous_time is not None and event["parsed_at"] < previous_time:
                _fail(report, f"Review timestamps run backward for {content_hash}",
                      "invalid_review_chains")
            previous_time = event["parsed_at"]
            if event["action"] == "confirm":
                expected = previous
            else:
                expected = {**previous, **{key: payload[key] for key in RUBRIC_FIELDS}}
            if payload != expected:
                _fail(report, f"Invalid {event['action']} review chain for {content_hash}",
                      "invalid_review_chains")
            previous = payload
    return current, confirmed, history, sorted(events, key=lambda e: e["review_id"])


def _comparable(row: dict, report: MigrationReport) -> dict:
    result = dict(row)
    for key in ("provenance_json", "original_annotation_json"):
        result[key] = _json_object(row[key], report, key)
    return result


def _compare_export(store: SharedStore, kind: str, expected: list[dict],
                    report: MigrationReport) -> None:
    actual = list(csv.DictReader(io.StringIO(store.export_csv(kind).decode("utf-8"))))
    if kind == "history":
        key = lambda row: row["review_id"]
        category = "invalid_review_chains"
    else:
        key = lambda row: row["content_hash"]
        category = f"{kind}_state_conflicts"
    expected_by_key = {key(row): _comparable(row, report) for row in expected}
    actual_by_key = {key(row): _comparable(row, report) for row in actual}
    conflicts = len(expected) - len(expected_by_key)
    conflicts += len(actual) - len(actual_by_key)
    conflicts += len(expected_by_key.keys() ^ actual_by_key.keys())
    conflicts += sum(expected_by_key[k] != actual_by_key[k]
                     for k in expected_by_key.keys() & actual_by_key.keys())
    if conflicts:
        _fail(report, f"Generated {kind} export differs from supplied {kind} CSV "
              f"({conflicts} conflicting rows/keys)", category, conflicts)


def _validate_database(store: SharedStore, expected_count: int, report: MigrationReport) -> None:
    with store.connection() as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            _fail(report, "Generated SQLite database failed integrity_check")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            _fail(report, "Generated SQLite database has foreign key violations")
        for table, count in (("images", 401), ("annotations", 401),
                             ("reviews", expected_count)):
            actual = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if actual != count:
                _fail(report, f"Generated {table} count is {actual}, expected {count}")


def _checkpoint(temp_path: Path, report: MigrationReport) -> None:
    with closing(sqlite3.connect(temp_path)) as db:
        if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
            _fail(report, "Temporary database WAL checkpoint was busy")
        if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
            _fail(report, "Could not finalize temporary database journal")
    with temp_path.open("rb") as handle:
        os.fsync(handle.fileno())
    with closing(sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            _fail(report, "Final temporary database failed integrity_check")


def migrate(inputs: Inputs) -> MigrationReport:
    report = MigrationReport()
    output = inputs.output.resolve()
    if output.exists() or inputs.output.is_symlink():
        _fail(report, f"Output database already exists: {inputs.output}")
    if inputs.report_path and (inputs.report_path.exists() or inputs.report_path.is_symlink()):
        _fail(report, f"Audit report already exists: {inputs.report_path}")
    batches, originals = _originals(inputs, report)
    _annotator_audit(inputs, originals, report)
    current, confirmed, history, events = _review_sources(inputs, originals, report)

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    report_temp = None
    published = False
    succeeded = False
    try:
        with tempfile.NamedTemporaryFile(prefix=".migration-", suffix=".sqlite3",
                                         dir=output.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        store = SharedStore(temp_path)
        store.import_batches(batches)
        with store.connection(write=True) as db:
            for event in events:
                db.execute(
                    "INSERT INTO reviews(review_id,content_hash,reviewer_key,reviewer,"
                    "reviewed_at,action,reason,payload) VALUES (?,?,?,?,?,?,?,?)",
                    (event["review_id"], event["content_hash"], event["reviewer_key"],
                     event["reviewer"], event["reviewed_at"], event["action"],
                     event["reason"], json.dumps(event["payload"])),
                )
        _validate_database(store, len(events), report)
        for kind, rows in (("history", history), ("current", current),
                           ("confirmed", confirmed)):
            _compare_export(store, kind, rows, report)
        _checkpoint(temp_path, report)
        if inputs.report_path:
            inputs.report_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".migration-report-", suffix=".json",
                                             dir=inputs.report_path.parent, delete=False,
                                             mode="w", encoding="utf-8") as handle:
                report_temp = Path(handle.name)
                json.dump(report.as_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        os.link(temp_path, output)  # Atomic no-clobber publication on the same filesystem.
        published = True
        if report_temp:
            os.link(report_temp, inputs.report_path)
        succeeded = True
        return report
    except (OSError, AnnotationError, sqlite3.Error) as exc:
        raise MigrationError(f"Could not publish validated migration: {exc}", report) from exc
    finally:
        if published and not succeeded:
            output.unlink(missing_ok=True)
        for path in (temp_path, report_temp):
            if path:
                path.unlink(missing_ok=True)
        if temp_path:
            for suffix in ("-wal", "-shm"):
                Path(str(temp_path) + suffix).unlink(missing_ok=True)


def _print_report(report: MigrationReport) -> None:
    for key in COUNTS:
        print(f"{key.replace('_', ' ').title()}: {report.counts[key]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--review-current", type=Path, required=True)
    parser.add_argument("--review-confirmed", type=Path, required=True)
    parser.add_argument("--review-history", type=Path, required=True)
    parser.add_argument("--annotator-csv", type=Path, action="append", default=[])
    parser.add_argument("--repository-root", type=Path, default=ROOT,
                        help="Root used to resolve source image component paths")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "annotations/master/sensifake.sqlite3")
    parser.add_argument("--expected-annotations-sha256")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    inputs = Inputs(args.annotations, args.review_current, args.review_confirmed,
                    args.review_history, args.output, args.repository_root,
                    tuple(args.annotator_csv), args.expected_annotations_sha256, args.report)
    try:
        report = migrate(inputs)
    except MigrationError as exc:
        _print_report(exc.report)
        print(f"Migration: FAILED — {exc}", file=sys.stderr)
        return 1
    _print_report(report)
    print("Migration: SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
