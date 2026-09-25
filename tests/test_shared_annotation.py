"""End-to-end storage checks using real ZIP images and independent SQLite connections."""

import csv
import hashlib
import io
import json
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from PIL import Image

from scripts.annotation.import_batches import (
    SNAPSHOT,
    SNAPSHOT_SHA256,
    prepare_legacy,
    prepare_zip,
)
from scripts.annotation.annotation_schema import AnnotationError
from scripts.annotation.paths import REPOSITORY_ROOT
from scripts.annotation.annotation_database import EXPORT_FIELDS, SharedStore


def image_bytes(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(output, format="PNG")
    return output.getvalue()


def archive(files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, data in (files or {"one.png": image_bytes()}).items():
            zipped.writestr(name, data)
    output.seek(0)
    return output


def values(**overrides):
    result = {
        "public_relevance": 1,
        "harm_urgency": 2,
        "vulnerability": 1,
        "sensitivity_rationale": "Visible distress.",
        "annotation_confidence": "high",
        "needs_review": False,
    }
    result.update(overrides)
    return result


def export(store, kind="current", batch=None):
    return list(csv.DictReader(io.StringIO(store.export_csv(kind, batch).decode())))


@pytest.fixture
def store(tmp_path):
    result = SharedStore(tmp_path / "shared.sqlite3", reservation_seconds=60)
    result.import_batches(prepare_zip(archive(), "First"))
    return result


def test_concurrent_reservations_and_saves(tmp_path):
    path = tmp_path / "shared.sqlite3"
    first = SharedStore(path)
    first.import_batches(
        prepare_zip(
            archive({f"{c}.png": image_bytes(c) for c in ("red", "green", "blue")}), "Three"
        )
    )
    barrier = Barrier(3)

    def worker(name):
        store = SharedStore(path)
        barrier.wait()
        lease = store.reserve(name)
        store.complete(lease["token"], name, values())
        return lease["content_hash"]

    with ThreadPoolExecutor(max_workers=3) as executor:
        hashes = list(executor.map(worker, ("Sara", "Lorenzo", "Giovanni")))
    assert len(set(hashes)) == 3
    assert len(export(first)) == 3
    assert first.reserve("Fourth") is None


def test_one_image_cannot_be_reserved_twice(tmp_path):
    path = tmp_path / "shared.sqlite3"
    store = SharedStore(path)
    store.import_batches(prepare_zip(archive(), "One"))
    barrier = Barrier(3)

    def worker(name):
        connection = SharedStore(path)
        barrier.wait()
        return connection.reserve(name)

    with ThreadPoolExecutor(max_workers=3) as executor:
        leases = list(executor.map(worker, ("Sara", "Lorenzo", "Giovanni")))
    assert sum(lease is not None for lease in leases) == 1


def test_interrupted_session_draft_resume_and_expiry(store):
    lease = store.reserve("Sara", now=100)
    store.save_draft(lease["token"], "Sara", values(), now=110)
    reopened = SharedStore(store.path, reservation_seconds=60)
    resumed = reopened.reserve(" sara ", now=120)
    assert resumed["token"] == lease["token"]
    assert reopened.draft(resumed)["sensitivity_score"] == 4
    assert reopened.reserve("Lorenzo", now=150) is None
    replacement = reopened.reserve("Lorenzo", now=171)
    assert replacement["content_hash"] == lease["content_hash"]
    assert reopened.draft(replacement) is None
    with pytest.raises(AnnotationError, match="expired"):
        store.complete(lease["token"], "Sara", values(), now=172)
    with pytest.raises(AnnotationError, match="expired"):
        store.save_draft(lease["token"], "Sara", values(), now=172)
    reopened.release(replacement["token"], "Lorenzo")
    recovered = reopened.reserve("Sara", now=173)
    assert reopened.draft(recovered)["sensitivity_score"] == 4


def test_duplicate_imports_keep_provenance_and_single_queue(store):
    result = store.import_batches(
        prepare_zip(
            archive(
                {
                    "real_named.png": image_bytes(),
                    "copy.png": image_bytes(),
                    "metadata.json": json.dumps(
                        {"copy.png": {"source_dataset": "Example", "note": "A"}}
                    ),
                }
            ),
            "RR batch",
            "rrdataset",
        )
    )
    assert result["new_images"] == 0
    assert result["duplicate_images"] == 2
    assert len(result["duplicates"]) == 2
    lease = store.reserve("Sara")
    store.complete(lease["token"], "Sara", values())
    assert store.reserve("Lorenzo") is None
    rows = export(store)
    assert len(rows) == 3
    assert {r["normalized_label"] for r in rows} == {"unknown"}
    assert (
        json.loads(
            next(r for r in rows if r["original_filename"] == "copy.png")["provenance_json"]
        )["note"]
        == "A"
    )
    assert store.progress()[0]["total"] == 1
    with pytest.raises(AnnotationError, match="already exists"):
        store.import_batches(prepare_zip(archive(), "First"))
    assert len(store.batches()) == 2


@pytest.mark.parametrize(
    "path", ["../escape.png", "/absolute.png", "a/../b.png", "C:/x.png", "a\\b.png", "./x.png"]
)
def test_unsafe_archive_paths(path):
    with pytest.raises(AnnotationError, match="Unsafe"):
        prepare_zip(archive({path: image_bytes()}), "Unsafe")


def test_zip_symlink_and_unreadable_images():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        entry = zipfile.ZipInfo("link.png")
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(entry, "../target")
    output.seek(0)
    with pytest.raises(AnnotationError, match="links"):
        prepare_zip(output, "Links")
    with pytest.raises(AnnotationError, match="Unreadable"):
        prepare_zip(archive({"bad.png": b"broken"}), "Bad")


def test_invalid_metadata_and_authoritative_labels():
    with pytest.raises(AnnotationError, match="label_source"):
        prepare_zip(
            archive(
                {
                    "one.png": image_bytes(),
                    "metadata.json": json.dumps(
                        {
                            "one.png": {"normalized_label": "real"},
                        }
                    ),
                }
            ),
            "Bad",
        )
    batch = prepare_zip(
        archive(
            {
                "one.png": image_bytes(),
                "metadata.json": json.dumps(
                    {
                        "one.png": {
                            "normalized_label": "fake",
                            "label_source": "Dataset manifest",
                            "custom": 12,
                        },
                    }
                ),
            }
        ),
        "Good",
    )
    assert batch[0]["images"][0]["provenance"]["custom"] == 12


def test_reviews_are_append_only_and_self_review_is_blocked(store):
    lease = store.reserve("Sara")
    store.complete(lease["token"], "Sara", values())
    assert store.reserve(" SARA ", kind="review") is None
    review = store.reserve("Lorenzo", kind="review")
    assert store.reserve("Giovanni", kind="review") is None
    with pytest.raises(AnnotationError, match="reason"):
        store.complete(review["token"], "Lorenzo", values(public_relevance=0), action="correct")
    store.complete(
        review["token"],
        "Lorenzo",
        values(public_relevance=0),
        action="correct",
        reason="No visible public interest",
    )
    second = store.reserve("Giovanni", kind="review", include_reviewed=True)
    store.complete(second["token"], "Giovanni")
    decision = store.decision(lease["content_hash"])
    assert decision["original"]["sensitivity_score"] == 4
    assert decision["current"]["sensitivity_score"] == 3
    assert [r["action"] for r in decision["reviews"]] == ["correct", "confirm"]
    assert len(export(store, "history")) == 2
    assert export(store, "confirmed")[0]["reviewer"] == "Giovanni"
    assert export(store)[0]["annotator"] == "Sara"
    assert json.loads(export(store)[0]["original_annotation_json"])["sensitivity_score"] == 4


def test_incomplete_and_empty_exports_and_closed_batches(store):
    assert store.export_csv().decode().strip() == ",".join(EXPORT_FIELDS)
    store.import_batches(prepare_zip(archive({"blue.png": image_bytes("blue")}), "Second"))
    first_id = store.batches()[0]["batch_id"]
    lease = store.reserve("Sara", first_id)
    store.complete(lease["token"], "Sara", values(sensitivity_rationale=""))
    assert len(export(store)) == 1
    assert export(store, "confirmed") == []
    assert export(store, "history") == []
    store.set_open(first_id, False)
    assert store.reserve("Lorenzo", first_id, kind="review") is None
    assert len(export(store, batch=first_id)) == 1
    assert store.progress()[0]["unannotated"] == 1


def test_invalid_batch_rolls_back_all_memberships_and_images(store):
    batches = prepare_zip(archive({"blue.png": image_bytes("blue")}), "New")
    batches += prepare_zip(archive(), "First")
    with pytest.raises(AnnotationError):
        store.import_batches(batches)
    assert len(store.batches()) == 1
    assert store.progress()[0]["total"] == 1


def test_audited_legacy_snapshot_preserved_and_imported(tmp_path):
    if not (REPOSITORY_ROOT / SNAPSHOT).is_file():
        pytest.skip("Audited local data is not available in this checkout")
    source = REPOSITORY_ROOT / SNAPSHOT
    before = source.read_bytes()
    prepared = prepare_legacy(REPOSITORY_ROOT)
    assert [len(b["images"]) for b in prepared] == [101, 300]
    store = SharedStore(tmp_path / "legacy.sqlite3")
    store.import_batches(prepared)
    rows = export(store)
    assert len(rows) == 401
    assert {r["dataset_role"] for r in rows} == {"gold_development", "human_train"}
    assert sum(r["annotator"] == "sara" for r in rows) == 201
    assert export(store, "confirmed") == []
    expected = {r["content_hash"]: r for r in csv.DictReader(io.StringIO(before.decode()))}
    for row in rows:
        for field in (
            "public_relevance",
            "harm_urgency",
            "vulnerability",
            "sensitivity_score",
            "sensitivity_level",
            "sensitivity_rationale",
            "annotation_confidence",
            "annotated_at",
        ):
            assert row[field] == expected[row["content_hash"]][field]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SNAPSHOT_SHA256
    assert source.read_bytes() == before


def test_streamlit_entrypoint_requires_name_and_renders(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SENSIFAKE_STORAGE", str(tmp_path / "app.sqlite3"))
    monkeypatch.setattr("sys.argv", ["scripts/annotation/app.py"])
    app = AppTest.from_file(str(REPOSITORY_ROOT / "scripts/annotation/app.py")).run()
    assert not app.exception
    assert "Enter your name" in app.info[0].value
    app.text_input[0].set_value("Sara").run()
    assert not app.exception
    assert any(button.label == "Resume or reserve an image" for button in app.button)


def test_streamlit_starts_without_storage_configuration(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from scripts.annotation import paths

    monkeypatch.delenv("SENSIFAKE_STORAGE", raising=False)
    monkeypatch.setattr(paths, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["scripts/annotation/app.py"])
    app = AppTest.from_file(str(REPOSITORY_ROOT / "scripts/annotation/app.py")).run()
    assert not app.exception
    assert app.text_input[0].label == "Your name"
    app.text_input[0].set_value("Lorenzo").run()
    assert not app.exception
    assert any(button.label == "Resume or reserve an image" for button in app.button)
    assert (tmp_path / "annotations" / "shared" / "sensifake.sqlite3").is_file()


def test_streamlit_annotation_and_review_flow(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    storage = tmp_path / "app.sqlite3"
    store = SharedStore(storage)
    store.import_batches(prepare_zip(archive(), "One"))
    monkeypatch.setenv("SENSIFAKE_STORAGE", str(storage))
    monkeypatch.setattr("sys.argv", ["scripts/annotation/app.py"])
    app = AppTest.from_file(str(REPOSITORY_ROOT / "scripts/annotation/app.py")).run()
    app.text_input[0].set_value("Sara").run()
    next(b for b in app.button if b.label == "Resume or reserve an image").click().run()
    assert not app.exception
    next(r for r in app.radio if r.label == "Public relevance · 0–2").set_value(2).run()
    next(s for s in app.selectbox if s.label == "Annotation confidence").set_value("low").run()
    assert next(c for c in app.checkbox if c.label == "Needs review").value
    next(b for b in app.button if b.label == "Save completed annotation").click().run()
    assert not app.exception
    assert export(store)[0]["sensitivity_score"] == "2"
    app.text_input[0].set_value("Lorenzo").run()
    app.sidebar.radio[0].set_value("Review").run()
    next(b for b in app.button if b.label == "Resume or reserve an image").click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "Save review").click().run()
    assert not app.exception
    assert export(store, "confirmed")[0]["reviewer"] == "Lorenzo"
    app.sidebar.radio[0].set_value("Progress and exports").run()
    assert not app.exception
