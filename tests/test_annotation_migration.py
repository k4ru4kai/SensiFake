"""One-way migration tests using only generated images and CSVs under tmp_path."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from PIL import Image

from scripts.annotation.annotation_database import SharedStore, identity
from scripts.annotation.annotation_schema import (
    ANNOTATION_FIELDS,
    annotation_from_values,
)
from scripts.legacy.human_train_assignment import COMPONENT_PATHS
from scripts.tools.migrate_annotations_to_sqlite import Inputs, MigrationError, main, migrate

SNAPSHOT_HEADER = (
    "content_hash", "blind_id", "component", "relative_image_path",
    "source_dataset", "normalized_label", "dataset_role", "annotator_id",
    *[field for field in ANNOTATION_FIELDS if field not in ("content_hash", "blind_id")],
)


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def edit_csv(path: Path, change) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = tuple(reader.fieldnames or ())
        rows = list(reader)
    change(rows)
    write_csv(path, rows, fields)


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "source-repository"
    component = "openfake_pilot_600"
    images_dir = root / COMPONENT_PATHS[component] / "images"
    images_dir.mkdir(parents=True)
    rows = []
    batches = {
        role: {"batch_id": f"legacy-{role}", "name": f"Legacy {role}",
               "dataset_role": role, "images": []}
        for role in ("gold_development", "human_train")
    }
    originals = {}
    image_paths = []
    for index in range(401):
        image = Image.new("RGB", (1, 1), (index % 256, index // 256, 7))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        relative = f"images/{content_hash}.png"
        image_path = images_dir / f"{content_hash}.png"
        image_path.write_bytes(image_bytes)
        image_paths.append(image_path)
        role = "gold_development" if index < 101 else "human_train"
        annotator = "sara" if index < 101 else "alice"
        annotation = asdict(annotation_from_values(
            content_hash=content_hash, blind_id=f"SF-{index:04d}",
            public_relevance=index % 3, harm_urgency=0, vulnerability=0,
            sensitivity_rationale="", annotation_confidence="high", needs_review=False,
            annotated_at="2026-08-25T12:00:00+00:00",
        ))
        originals[content_hash] = annotation
        metadata = {
            "component": component, "relative_image_path": relative,
            "source_dataset": "Synthetic/Test", "normalized_label": "unknown",
            "dataset_role": role, "annotator_id": annotator,
        }
        rows.append({**metadata, **annotation,
                     "needs_review": str(annotation["needs_review"]).lower()})
        batches[role]["images"].append({
            "content_hash": content_hash, "image_bytes": image_bytes,
            "original_filename": f"{component}/{relative}",
            "provenance": {**metadata, "label_source": "Synthetic/Test"},
            "annotation": annotation, "annotator": annotator,
        })
    annotations_path = tmp_path / "annotations.csv"
    write_csv(annotations_path, rows, SNAPSHOT_HEADER)

    source_store = SharedStore(tmp_path / "synthetic-source.sqlite3")
    source_store.import_batches(list(batches.values()))
    first_hash, second_hash = rows[0]["content_hash"], rows[1]["content_hash"]
    corrected = {**originals[first_hash], "public_relevance": 2,
                 "sensitivity_score": 2, "sensitivity_level": "medium"}
    reviewer_key, reviewer = identity("Bob")
    with source_store.connection(write=True) as db:
        for review_id, content_hash, action, reason, payload in (
            (1, first_hash, "confirm", "", originals[first_hash]),
            (2, first_hash, "correct", "visible context", corrected),
            (3, second_hash, "confirm", "", originals[second_hash]),
        ):
            db.execute(
                "INSERT INTO reviews(review_id,content_hash,reviewer_key,reviewer,"
                "reviewed_at,action,reason,payload) VALUES (?,?,?,?,?,?,?,?)",
                (review_id, content_hash, reviewer_key, reviewer,
                 f"2026-09-25T12:00:0{review_id}+00:00", action, reason,
                 json.dumps(payload)),
            )
    current = tmp_path / "current.csv"
    confirmed = tmp_path / "confirmed.csv"
    history = tmp_path / "history.csv"
    for kind, path in (("current", current), ("confirmed", confirmed),
                       ("history", history)):
        path.write_bytes(source_store.export_csv(kind))
    inputs = Inputs(
        annotations=annotations_path, review_current=current,
        review_confirmed=confirmed, review_history=history,
        output=tmp_path / "master/sensifake.sqlite3", repository_root=root,
    )
    return inputs, first_hash, second_hash, image_paths


def test_success_preserves_sources_and_review_chain(sources):
    inputs, first_hash, _, image_paths = sources
    audit = inputs.output.parent / "audit.json"
    inputs = replace(inputs, report_path=audit,
                     expected_annotations_sha256=hashlib.sha256(
                         inputs.annotations.read_bytes()).hexdigest())
    source_paths = [inputs.annotations, inputs.review_current, inputs.review_confirmed,
                    inputs.review_history, *image_paths]
    before = {path: path.read_bytes() for path in source_paths}
    report = migrate(inputs)
    assert report.counts["original_annotations"] == 401
    assert report.counts["unique_content_hashes"] == 401
    assert report.counts["review_events_imported"] == 3
    assert report.counts["unique_reviewed_images"] == 2
    assert report.counts["awaiting_review"] == 399
    assert report.counts["confirm_actions"] == 2
    assert report.counts["correct_actions"] == 1
    assert report.counts["images_with_multiple_reviews"] == 1
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert json.loads(audit.read_text())["input_sha256"][str(inputs.annotations)] == (
        hashlib.sha256(before[inputs.annotations]).hexdigest()
    )

    store = SharedStore(inputs.output)
    decision = store.decision(first_hash)
    assert [review["review_id"] for review in decision["reviews"]] == [1, 2]
    assert decision["original"]["public_relevance"] == 0
    assert decision["current"]["public_relevance"] == 2
    assert decision["original"]["sensitivity_score"] == 0
    assert decision["current"]["sensitivity_score"] == 2
    assert store.export_csv("current") == inputs.review_current.read_bytes()
    assert store.export_csv("confirmed") == inputs.review_confirmed.read_bytes()
    assert store.export_csv("history") == inputs.review_history.read_bytes()


def test_requires_exactly_401_unique_originals(sources):
    inputs, *_ = sources
    edit_csv(inputs.annotations, lambda rows: rows.pop())
    with pytest.raises(MigrationError, match="Exactly 401"):
        migrate(inputs)
    assert not inputs.output.exists()


@pytest.mark.parametrize("bad_hash", ["duplicate", "invalid"])
def test_rejects_duplicate_or_invalid_original_hash(sources, bad_hash):
    inputs, *_ = sources
    def change(rows):
        rows[1]["content_hash"] = rows[0]["content_hash"] if bad_hash == "duplicate" else "z" * 64
    edit_csv(inputs.annotations, change)
    with pytest.raises(MigrationError):
        migrate(inputs)
    assert not inputs.output.exists()


def test_rejects_unknown_review_hash(sources):
    inputs, *_ = sources
    edit_csv(inputs.review_history, lambda rows: rows[0].update(content_hash="f" * 64))
    with pytest.raises(MigrationError, match="unknown content_hash") as error:
        migrate(inputs)
    assert error.value.report.counts["unknown_hashes"] == 1
    assert not inputs.output.exists()


def test_rejects_conflicting_current_state_and_cleans_temporary_database(sources):
    inputs, *_ = sources
    edit_csv(inputs.review_current, lambda rows: rows[0].update(sensitivity_score="5"))
    with pytest.raises(MigrationError, match="Generated current export differs") as error:
        migrate(inputs)
    assert error.value.report.counts["current_state_conflicts"] == 1
    assert not inputs.output.exists()
    assert not list(inputs.output.parent.glob(".migration-*"))


def test_rejects_conflicting_confirmed_state(sources):
    inputs, *_ = sources
    edit_csv(inputs.review_confirmed, lambda rows: rows[0].update(reviewer="Other"))
    with pytest.raises(MigrationError, match="Generated confirmed export differs") as error:
        migrate(inputs)
    assert error.value.report.counts["confirmed_state_conflicts"] == 1
    assert not inputs.output.exists()


def test_rejects_invalid_review_chain_and_duplicate_history_id(sources):
    inputs, *_ = sources
    edit_csv(inputs.review_history, lambda rows: rows[1].update(review_id=rows[0]["review_id"]))
    with pytest.raises(MigrationError, match="review_id must be a unique") as error:
        migrate(inputs)
    assert error.value.report.counts["invalid_review_chains"] == 1
    assert not inputs.output.exists()


def test_existing_output_is_never_overwritten(sources):
    inputs, *_ = sources
    inputs.output.parent.mkdir(parents=True)
    inputs.output.write_bytes(b"existing database sentinel")
    with pytest.raises(MigrationError, match="already exists"):
        migrate(inputs)
    assert inputs.output.read_bytes() == b"existing database sentinel"


def test_optional_annotator_csv_audits_values_with_distinct_blind_id(sources, tmp_path):
    inputs, first_hash, *_ = sources
    with inputs.annotations.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    annotator_csv = tmp_path / "person.csv"
    write_csv(annotator_csv, [{**{field: row[field] for field in ANNOTATION_FIELDS},
                               "blind_id": "HT-personal-id"}], ANNOTATION_FIELDS)
    report = migrate(replace(inputs, annotator_csvs=(annotator_csv,)))
    assert report.counts["review_events_imported"] == 3
    assert first_hash in [r["content_hash"] for r in csv.DictReader(
        io.StringIO(annotator_csv.read_text()))]


def test_cli_prints_report_and_success(sources, capsys):
    inputs, *_ = sources
    assert main([
        "--annotations", str(inputs.annotations), "--review-current", str(inputs.review_current),
        "--review-confirmed", str(inputs.review_confirmed), "--review-history",
        str(inputs.review_history), "--repository-root", str(inputs.repository_root),
        "--output", str(inputs.output),
    ]) == 0
    output = capsys.readouterr().out
    assert "Original Annotations: 401" in output
    assert "Review Events Imported: 3" in output
    assert "Migration: SUCCESS" in output
