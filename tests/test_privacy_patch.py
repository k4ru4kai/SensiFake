"""Privacy derivative contracts without publishing original attribution mappings."""
import csv
import datetime
import hashlib
import json
import re
from pathlib import Path

from scripts.annotation.annotation_schema import load_annotations

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "docs/privacy_patch_manifest.json").read_text())


def read(path):
    with (ROOT / path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def fingerprint(rows, columns):
    payload = [columns, [[row[key] for key in columns] for row in rows]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def test_every_derivative_retains_schema_order_and_scientific_projection():
    assert len(MANIFEST["records"]) == 10
    for entry in MANIFEST["records"]:
        path = ROOT / entry["candidate_path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["candidate_sha256"]
        rows = read(entry["candidate_path"])
        assert len(rows) == entry["rows"]
        assert list(rows[0]) == entry["columns"]
        assert fingerprint(rows, entry["preserved_columns"]) == entry["preserved_columns_sha256"]


def test_low_files_and_neutral_task_bodies_are_byte_identical():
    entries = MANIFEST["records"]
    assert sum(entry["risk"] == "LOW" for entry in entries) == 3
    identical = [entry for entry in entries if entry["byte_identical"]]
    assert len(identical) == 6
    assert all(entry["source_sha256"] == entry["candidate_sha256"] for entry in identical)


def test_rater_groups_and_task_order_still_correspond():
    master = read("annotations/splits/human_train_assignment.csv")
    codes = {row["annotator_id"] for row in master}
    assert len(master) == 300 and len(codes) == 3
    assert all(re.fullmatch(r"reviewer-\d{3}", code) for code in codes)
    for code in codes:
        task = read(f"annotations/tasks/human-train-v0/{code}.csv")
        group = sorted((row for row in master if row["annotator_id"] == code),
                       key=lambda row: int(row["annotation_order"]))
        assert len(group) == len(task) == 100
        assert [row["content_hash"] for row in task] == [row["content_hash"] for row in group]
        assert [row["annotation_order"] for row in task] == [row["annotation_order"] for row in group]
    assignments = read("annotations/packages/outgoing/model_review_batch_01/review_assignment.csv")
    assert len(assignments) == 600
    assert {row["annotator"] for row in assignments} == codes
    assert all(row["annotator"] in row["batch_id"] for row in assignments)


def test_minimized_annotations_still_parse_with_existing_schema():
    path = "annotations/openfake/development-v0/sensitivity_annotations.csv"
    rows = read(path)
    assert len(load_annotations(ROOT / path)) == len(rows) == 101
    assert all(row["sensitivity_rationale"] == "" for row in rows)
    for row in rows:
        stamp = datetime.datetime.fromisoformat(row["annotated_at"])
        assert stamp.tzinfo is not None
        assert (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) == (0, 0, 0, 0)


def test_result_aliases_preserve_hash_backed_scientific_rows():
    rows = read("notebooks/final output/sensifake_complete_sensitivity.csv")
    assert len(rows) == 4499
    assert len({row["content_hash"] for row in rows}) == 4499
    populated = [row for row in rows if row["adjudicator"]]
    assert len(populated) == 41
    assert all(re.fullmatch(r"reviewer-\d{3}", row["adjudicator"]) for row in populated)
    assert sum(any(re.fullmatch(r"reviewer-\d{3}", part) for path in
                   json.loads(row["source_paths_json"]) for part in path.split("/"))
               for row in rows) == 1499
    for row in populated:
        stamp = datetime.datetime.fromisoformat(row["adjudicated_at"])
        assert (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) == (0, 0, 0, 0)


def test_manifest_does_not_publish_a_name_mapping_or_anonymity_claim():
    assert MANIFEST["identity_mapping_published"] is False
    assert "not anonymous" in MANIFEST["status"]
    assert all("source_public_path" not in entry for entry in MANIFEST["records"])
