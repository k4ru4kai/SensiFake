"""Offline packages remain disjoint and preserve the names entered in the app."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from PIL import Image

from sensifake_annotation.batch_import import prepare_zip
from sensifake_annotation.core import AnnotationError
from sensifake_annotation.offline import merge_offline, prepare_offline, snapshot_offline
from sensifake_annotation.shared_store import SharedStore


def sample_archive() -> io.BytesIO:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for index in range(6):
            image = io.BytesIO()
            Image.new("RGB", (12, 12), (index * 30, 0, 0)).save(image, format="PNG")
            archive.writestr(f"{index}.png", image.getvalue())
    result.seek(0)
    return result


def values() -> dict:
    return {
        "public_relevance": 1,
        "harm_urgency": 2,
        "vulnerability": 0,
        "sensitivity_rationale": "Visible content.",
        "annotation_confidence": "medium",
        "needs_review": False,
    }


def test_offline_packages_merge_names_entered_by_annotators(tmp_path):
    master_path = tmp_path / "master.sqlite3"
    master = SharedStore(master_path)
    master.import_batches(prepare_zip(sample_archive(), "To split"))
    output = tmp_path / "offline"
    manifest = prepare_offline(master_path, "To split", 3, output)
    assert [len(entry["hashes"]) for entry in manifest["packages"]] == [2, 2, 2]
    assert len({hash_value for entry in manifest["packages"] for hash_value in entry["hashes"]}) == 6
    assert "name" not in json.loads((output / "assignment.json").read_text())["packages"][0]

    returned = []
    for index, name in enumerate(("Sara", "Lorenzo", "Giovanni"), 1):
        package = output / f"annotator-{index:02d}.sqlite3"
        local = SharedStore(package)
        lease = local.reserve(name)
        local.complete(lease["token"], name, values())
        snapshot = tmp_path / f"returned-{index:02d}.sqlite3"
        snapshot_offline(package, snapshot)
        returned.append(snapshot)

    assert merge_offline(master_path, output / "assignment.json", returned) == 3
    assert merge_offline(master_path, output / "assignment.json", returned) == 0
    with master.connection() as db:
        assert {row[0] for row in db.execute("SELECT annotator FROM annotations")} == {
            "Sara", "Lorenzo", "Giovanni"
        }


def test_offline_merge_rejects_conflict_without_partial_import(tmp_path):
    master_path = tmp_path / "master.sqlite3"
    master = SharedStore(master_path)
    master.import_batches(prepare_zip(sample_archive(), "To split"))
    output = tmp_path / "offline"
    prepare_offline(master_path, "To split", 2, output)
    first = SharedStore(output / "annotator-01.sqlite3")
    second = SharedStore(output / "annotator-02.sqlite3")
    for package in (first, second):
        lease = package.reserve("Any name")
        package.complete(lease["token"], "Any name", values())
    with first.connection() as db:
        conflict_hash = db.execute("SELECT content_hash FROM annotations").fetchone()[0]
    with master.connection(write=True) as db:
        db.execute(
            "INSERT INTO annotations VALUES (?,?,?,?)",
            (conflict_hash, "someone", "Someone", json.dumps({"different": True})),
        )
    with pytest.raises(AnnotationError, match="Conflicting annotation"):
        merge_offline(
            master_path,
            output / "assignment.json",
            [first.path, second.path],
        )
    with master.connection() as db:
        assert db.execute("SELECT count(*) FROM annotations").fetchone()[0] == 1
