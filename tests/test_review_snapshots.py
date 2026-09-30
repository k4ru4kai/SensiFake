"""Review handoffs use synthetic databases only; no production paths or fixed corpus size."""

import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import asdict

import pytest
from PIL import Image

from scripts.annotation import review_snapshots as handoff
from scripts.annotation.annotation_database import SharedStore
from scripts.annotation.annotation_schema import AnnotationError, annotation_from_values
from scripts.annotation.paths import REPOSITORY_ROOT
from scripts.tools.review_snapshots import main


def add_batch(store, name, count, start=0, author="Alice", annotated=True):
    images = []
    for index in range(start, start + count):
        output = io.BytesIO()
        Image.new("RGB", (2, 2), (index % 256, index // 256, 17)).save(output, format="PNG")
        data = output.getvalue()
        h = hashlib.sha256(data).hexdigest()
        image = {
            "content_hash": h,
            "image_bytes": data,
            "original_filename": f"{index}.png",
            "provenance": {"source_dataset": name, "normalized_label": "real"},
        }
        if annotated:
            image.update(
                annotator=author,
                annotation=asdict(
                    annotation_from_values(
                        content_hash=h,
                        blind_id=f"image-{index}",
                        public_relevance=0,
                        harm_urgency=0,
                        vulnerability=0,
                        sensitivity_rationale="",
                        annotation_confidence="high",
                        needs_review=False,
                        annotated_at="2020-01-01T00:00:00+00:00",
                    )
                ),
            )
        images.append(image)
    store.import_batches(
        [{"batch_id": name, "name": name, "dataset_role": "custom", "images": images}]
    )
    return [image["content_hash"] for image in images]


def finish(store, name="Bob", batch=None, correct=False, include_reviewed=False):
    lease = store.reserve(name, batch, kind="review", include_reviewed=include_reviewed)
    assert lease is not None
    store.complete(
        lease["token"],
        name,
        {
            "public_relevance": 2,
            "harm_urgency": 1,
            "vulnerability": 1,
            "sensitivity_rationale": "Observed context",
            "annotation_confidence": "high",
            "needs_review": False,
        },
        action="correct" if correct else "confirm",
        reason="Visible evidence" if correct else "",
    )
    return lease["content_hash"]


def dump(store):
    with store.connection() as db:
        return "\n".join(db.iterdump())


def mutate(path, statement, args=()):
    with sqlite3.connect(path) as db:
        db.execute(statement, args)


def exported(store, kind="current"):
    return list(csv.DictReader(io.StringIO(store.export_csv(kind).decode())))


@pytest.fixture
def master(tmp_path):
    store = SharedStore(tmp_path / "master.sqlite3")
    add_batch(store, "pending", 3)
    add_batch(store, "unannotated", 2, start=10, annotated=False)
    add_batch(store, "history", 1, start=20)
    finish(store, "Carol", "history")
    finish(store, "Dan", "history", correct=True, include_reviewed=True)
    return store


def issue(master, tmp_path):
    return handoff.create_snapshot(master.path, tmp_path / "outgoing")


def test_creation_lineage_full_state_and_history(master, tmp_path):
    original = exported(master)
    historical = exported(master, "history")
    path = issue(master, tmp_path)
    snapshot = SharedStore(path)
    assert exported(snapshot) == original
    assert exported(snapshot, "history") == historical
    manifest, current, new = handoff.read_snapshot(path)
    assert not new
    assert manifest["base_sha256"] == handoff.digest(manifest["base"])
    assert len(current["images"]) > len(current["annotations"])
    assert handoff.inspect_snapshot(path)["lineage_verified"] is False
    assert handoff.inspect_snapshot(path, master.path)["lineage_verified"] is True
    second = issue(master, tmp_path)
    other = handoff.inspect_snapshot(second)
    assert other["snapshot_id"] != manifest["snapshot_id"]
    assert other["base_sha256"] == manifest["base_sha256"]
    assert other["project_id"] == manifest["project_id"]
    assert handoff.inspect_snapshot(path)["snapshot_id"] == manifest["snapshot_id"]
    assert not list(path.parent.glob(".review-*"))


def test_partial_stop_resume_and_zero_work_return(master, tmp_path):
    path = issue(master, tmp_path)
    assert handoff.merge_snapshot(master.path, path)["new_reviews_imported"] == 0
    snapshot = SharedStore(path)
    first = finish(snapshot)
    lease = snapshot.reserve("Bob", kind="review")
    values = snapshot.decision(lease["content_hash"])["current"]
    snapshot.save_draft(lease["token"], "Bob", values)
    reopened = SharedStore(path)
    resumed = reopened.reserve(" bob ", kind="review")
    assert resumed["token"] == lease["token"]
    assert reopened.draft(resumed)["public_relevance"] == values["public_relevance"]
    reopened.complete(resumed["token"], "Bob")
    assert handoff.inspect_snapshot(path)["new_events"] == 2
    assert first != lease["content_hash"]
    result = handoff.merge_snapshot(master.path, path)
    assert result["new_reviews_imported"] == 2
    assert handoff.inspect_snapshot(path, master.path)["already_present"] == 2


def test_self_authored_skipped_and_rejected_at_completion(tmp_path):
    master = SharedStore(tmp_path / "m.sqlite3")
    own = add_batch(master, "own", 1, author="Bob")[0]
    other = add_batch(master, "other", 1, start=1)[0]
    path = issue(master, tmp_path)
    snapshot = SharedStore(path)
    assert finish(snapshot, " bob ") == other
    assert snapshot.reserve("Bob", kind="review") is None
    assert snapshot.decision(own)["reviews"] == []
    lease = snapshot.reserve("Carol", kind="review")
    mutate(
        path,
        "UPDATE reservations SET person_key='bob',person='Bob' WHERE token=?",
        (lease["token"],),
    )
    with pytest.raises(AnnotationError, match="own annotation"):
        snapshot.complete(lease["token"], "Bob")


def test_snapshot_write_guards_and_review_eligibility(master, tmp_path):
    snapshot = SharedStore(issue(master, tmp_path))
    for call in [
        lambda: snapshot.reserve("Bob"),
        lambda: snapshot.reserve("Bob", kind="review", include_reviewed=True),
        lambda: snapshot.set_open("pending", False),
        lambda: snapshot.import_batches([]),
    ]:
        with pytest.raises(AnnotationError):
            call()
    while snapshot.reserve("Bob", kind="review"):
        finish(snapshot)
    assert handoff.inspect_snapshot(snapshot.path)["unannotated"] == 2
    assert snapshot.progress()[0]["awaiting_review"] == 0
    assert snapshot.progress()[0]["unannotated"] == 2


def test_merge_preserves_originals_history_and_exports_and_is_idempotent(master, tmp_path):
    before = exported(master)
    history_before = exported(master, "history")
    path = issue(master, tmp_path)
    snapshot = SharedStore(path)
    h = finish(snapshot, correct=True)
    originals = {row["content_hash"]: row["original_annotation_json"] for row in before}
    result = handoff.merge_snapshot(master.path, path)
    assert result["new_reviews_imported"] == 1
    reopened = SharedStore(master.path)
    assert reopened.decision(h)["original"]["sensitivity_score"] == 0
    assert reopened.decision(h)["current"]["sensitivity_score"] == 4
    assert all(
        row["original_annotation_json"] == originals[row["content_hash"]]
        for row in exported(reopened)
    )
    assert all(row in exported(reopened, "history") for row in history_before)
    assert len(exported(reopened, "confirmed")) == len(
        {r["content_hash"] for r in exported(reopened, "history")}
    )
    before_retry = dump(master)
    assert handoff.merge_snapshot(master.path, path)["already_present_identical"] == 1
    assert dump(master) == before_retry
    fresh = SharedStore(issue(master, tmp_path))
    assert fresh.decision(h)["current"] == reopened.decision(h)["current"]
    assert fresh.reserve("Bob", "history", kind="review") is None


def test_stale_nonconflicting_merges_with_colliding_local_ids(tmp_path):
    master = SharedStore(tmp_path / "m.sqlite3")
    add_batch(master, "X", 1)
    add_batch(master, "Y", 1, start=1)
    a, b = issue(master, tmp_path), issue(master, tmp_path)
    x = finish(SharedStore(a), batch="X")
    y = finish(SharedStore(b), batch="Y")
    assert (
        handoff.read_snapshot(a)[2][0]["review_id"] == handoff.read_snapshot(b)[2][0]["review_id"]
    )
    handoff.merge_snapshot(master.path, a)
    assert handoff.merge_snapshot(master.path, b)["new_reviews_imported"] == 1
    assert (
        master.decision(x)["reviews"][0]["review_id"]
        != master.decision(y)["reviews"][0]["review_id"]
    )
    assert handoff.merge_snapshot(master.path, b)["already_present_identical"] == 1


def test_stale_conflict_rejects_entire_plan(master, tmp_path):
    a, b = issue(master, tmp_path), issue(master, tmp_path)
    h = finish(SharedStore(a))
    assert finish(SharedStore(b), correct=True) == h
    finish(SharedStore(b))
    handoff.merge_snapshot(master.path, a)
    before = dump(master)
    with pytest.raises(AnnotationError, match=h):
        handoff.merge_snapshot(master.path, b)
    assert dump(master) == before


def test_conflicting_stable_event_identity(master, tmp_path):
    path = issue(master, tmp_path)
    finish(SharedStore(path))
    handoff.merge_snapshot(master.path, path)
    event = handoff.read_snapshot(path)[2][0]
    mutate(path, "UPDATE reviews SET reason=? WHERE review_id=?", ("Different", event["review_id"]))
    before = dump(master)
    with pytest.raises(AnnotationError, match="event .* changed"):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


@pytest.mark.parametrize(
    "target", ["images", "annotations", "batch_images", "history", "manifest", "schema"]
)
def test_tampering_rejected_atomically(master, tmp_path, target):
    path = issue(master, tmp_path)
    if target == "images":
        mutate(path, "UPDATE images SET image_bytes=X'00'")
    elif target == "annotations":
        mutate(path, "UPDATE annotations SET annotator='Eve',annotator_key='eve'")
    elif target == "batch_images":
        mutate(path, "UPDATE batch_images SET provenance_json='{}'")
    elif target == "history":
        mutate(path, "DELETE FROM reviews WHERE review_id=(SELECT MAX(review_id) FROM reviews)")
    elif target == "schema":
        mutate(
            path, "CREATE TRIGGER sneaky AFTER INSERT ON reviews BEGIN DELETE FROM annotations; END"
        )
    else:
        with sqlite3.connect(path) as db:
            manifest = json.loads(db.execute("SELECT manifest FROM review_snapshot").fetchone()[0])
        manifest["project_id"] = "a" * 32
        mutate(path, "UPDATE review_snapshot SET manifest=?", (json.dumps(manifest),))
    before = dump(master)
    with pytest.raises(AnnotationError):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("reviewer", "Alice"),
        ("action", "invalid"),
        ("reason", ""),
        ("reviewed_at", "1999-01-01T00:00:00+00:00"),
        ("payload", "{}"),
    ],
)
def test_invalid_new_review_rejected(master, tmp_path, field, value):
    path = issue(master, tmp_path)
    finish(SharedStore(path), correct=True)
    event = handoff.read_snapshot(path)[2][0]
    mutate(path, f"UPDATE reviews SET {field}=? WHERE review_id=?", (value, event["review_id"]))
    before = dump(master)
    with pytest.raises(AnnotationError):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


def test_lineage_cannot_be_forged_with_recomputed_digest(master, tmp_path):
    path = issue(master, tmp_path)
    mutate(path, "UPDATE batches SET name='changed' WHERE batch_id='pending'")
    with sqlite3.connect(path) as db:
        manifest = json.loads(db.execute("SELECT manifest FROM review_snapshot").fetchone()[0])
    for batch in manifest["base"]["batches"]:
        if batch["batch_id"] == "pending":
            batch["name"] = "changed"
    manifest["base_sha256"] = handoff.digest(manifest["base"])
    mutate(path, "UPDATE review_snapshot SET manifest=?", (json.dumps(manifest),))
    assert handoff.inspect_snapshot(path)["lineage_verified"] is False
    with pytest.raises(AnnotationError, match="altered lineage"):
        handoff.merge_snapshot(master.path, path)


@pytest.mark.parametrize("count", [1, 7, 19])
def test_arbitrary_growth_and_later_batch_eligibility(tmp_path, count):
    master = SharedStore(tmp_path / "m.sqlite3")
    add_batch(master, "old", 1)
    old_hash = finish(master)
    stale = issue(master, tmp_path)
    old_decision = master.decision(old_hash)
    add_batch(master, "new", count, start=100)
    add_batch(master, "new-unannotated", count + 1, start=200, annotated=False)
    assert handoff.merge_snapshot(master.path, stale)["new_reviews_imported"] == 0
    fresh = SharedStore(issue(master, tmp_path))
    assert fresh.decision(old_hash) == old_decision
    assert fresh.reserve("Bob", "new-unannotated", kind="review") is None
    for _ in range(count):
        finish(fresh, batch="new")
    assert fresh.reserve("Bob", kind="review") is None
    assert handoff.merge_snapshot(master.path, fresh.path)["new_reviews_imported"] == count
    assert master.decision(old_hash) == old_decision
    assert master.progress()[0]["unannotated"] == count + 1


def test_failed_postwrite_validation_rolls_back(master, tmp_path, monkeypatch):
    path = issue(master, tmp_path)
    finish(SharedStore(path))
    before = dump(master)
    original_state = handoff.state

    def fail_after_insert(db, snapshot=False):
        result = original_state(db, snapshot)
        if not snapshot and db.execute("SELECT COUNT(*) FROM review_imports").fetchone()[0]:
            raise AnnotationError("injected validation failure")
        return result

    monkeypatch.setattr(handoff, "state", fail_after_insert)
    with pytest.raises(AnnotationError, match="injected"):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


def test_incremental_returns_of_same_snapshot(master, tmp_path):
    path = issue(master, tmp_path)
    finish(SharedStore(path))
    handoff.merge_snapshot(master.path, path)
    finish(SharedStore(path))
    result = handoff.merge_snapshot(master.path, path)
    assert result["already_present_identical"] == result["new_reviews_imported"] == 1


def test_cli_and_readonly_inspection(master, tmp_path, capsys):
    assert (
        main(["create", "--master", str(master.path), "--output-dir", str(tmp_path / "out")]) == 0
    )
    path = json.loads(capsys.readouterr().out)["snapshot"]
    before = dump(master)
    assert main(["inspect", path, "--master", str(master.path)]) == 0
    assert json.loads(capsys.readouterr().out)["to_import"] == 0
    assert dump(master) == before
    assert main(["merge", path, "--master", str(master.path)]) == 0
    assert json.loads(capsys.readouterr().out)["new_reviews_imported"] == 0


def test_app_snapshot_mode_and_reopen(master, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    path = issue(master, tmp_path)
    monkeypatch.setattr("sys.argv", ["app.py", "--storage", str(path)])
    app = AppTest.from_file(str(REPOSITORY_ROOT / "scripts/annotation/app.py")).run()
    assert not app.exception
    assert app.sidebar.radio[0].options == ["Review", "Progress and exports"]
    app.text_input[0].set_value("Bob").run()
    assert not any(c.label == "Include previously reviewed images" for c in app.checkbox)
    next(b for b in app.button if b.label == "Resume or reserve an image").click().run()
    next(b for b in app.button if b.label == "Save review").click().run()
    assert not app.exception
    reopened = AppTest.from_file(str(REPOSITORY_ROOT / "scripts/annotation/app.py")).run()
    reopened.text_input[0].set_value("Bob").run()
    assert not reopened.exception
    next(b for b in reopened.button if b.label == "Resume or reserve an image").click().run()
    assert not reopened.exception
    assert handoff.inspect_snapshot(path)["new_events"] == 1


def test_renamed_return_copy_and_multiple_memberships(master, tmp_path):
    from scripts.annotation.annotation_packages import snapshot_offline

    # Same image content in an additional batch shares its original and review state.
    add_batch(master, "alias", 1, annotated=False)
    path = issue(master, tmp_path)
    local = SharedStore(path)
    finish(local)
    returned = tmp_path / "arbitrary-return-name.sqlite3"
    snapshot_offline(path, returned)
    assert (
        handoff.inspect_snapshot(returned)["snapshot_id"]
        == handoff.inspect_snapshot(path)["snapshot_id"]
    )
    assert handoff.merge_snapshot(master.path, returned)["new_reviews_imported"] == 1
    assert exported(master) == exported(local)
    assert exported(master, "history") == exported(local, "history")


def test_master_original_changed_after_issue_is_conflict(master, tmp_path):
    path = issue(master, tmp_path)
    h = finish(SharedStore(path))
    with master.connection(write=True) as db:
        db.execute(
            "UPDATE annotations SET annotator='Eve',annotator_key='eve' WHERE content_hash=?", (h,)
        )
    before = dump(master)
    with pytest.raises(AnnotationError, match="Master base annotations changed"):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


def test_master_review_after_inspection_and_active_reservation(master, tmp_path):
    path = issue(master, tmp_path)
    h = finish(SharedStore(path))
    assert handoff.inspect_snapshot(path, master.path)["to_import"] == 1
    lease = master.reserve("Eve", kind="review")
    assert lease["content_hash"] == h
    with pytest.raises(AnnotationError, match="active master review reservation"):
        handoff.merge_snapshot(master.path, path)
    master.complete(lease["token"], "Eve")
    before = dump(master)
    with pytest.raises(AnnotationError, match="competing review"):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


def test_unannotated_injected_review_rejected(master, tmp_path):
    path = issue(master, tmp_path)
    finish(SharedStore(path))
    with master.connection() as db:
        h = db.execute(
            "SELECT content_hash FROM images WHERE content_hash NOT IN (SELECT content_hash FROM annotations)"
        ).fetchone()[0]
    event = handoff.read_snapshot(path)[2][0]
    mutate(path, "UPDATE reviews SET content_hash=? WHERE review_id=?", (h, event["review_id"]))
    before = dump(master)
    with pytest.raises(AnnotationError, match="foreign keys"):
        handoff.merge_snapshot(master.path, path)
    assert dump(master) == before


def test_later_annotation_of_existing_unannotated_image(master, tmp_path):
    old = issue(master, tmp_path)
    lease = master.reserve("Alice", "unannotated")
    master.complete(
        lease["token"],
        "Alice",
        {
            "public_relevance": 0,
            "harm_urgency": 0,
            "vulnerability": 0,
            "annotation_confidence": "high",
            "needs_review": False,
        },
    )
    assert handoff.merge_snapshot(master.path, old)["new_reviews_imported"] == 0
    fresh = SharedStore(issue(master, tmp_path))
    assert finish(fresh, "Bob", "unannotated") == lease["content_hash"]
    assert fresh.reserve("Bob", "unannotated", kind="review") is None
    assert handoff.merge_snapshot(master.path, fresh.path)["new_reviews_imported"] == 1


def test_failed_create_leaves_no_receipt_or_published_snapshot(master, tmp_path, monkeypatch):
    before = dump(master)

    def fail(_path, master=None):
        raise AnnotationError("injected snapshot validation failure")

    monkeypatch.setattr(handoff, "inspect_snapshot", fail)
    with pytest.raises(AnnotationError, match="injected"):
        issue(master, tmp_path)
    assert dump(master) == before
    assert not list((tmp_path / "outgoing").iterdir())
