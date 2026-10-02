"""The model-review ZIP remains blind until the initial human label is durable."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from scripts.annotation.annotation_database import SharedStore
from scripts.annotation.annotation_schema import AnnotationError
from scripts.annotation.import_batches import prepare_zip
from scripts.selection.build_model_review_batches import distribute, proportional_sample


def image_bytes(color: str = "blue") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(output, format="PNG")
    return output.getvalue()


def review_zip(
    *, mismatch: bool = False, optional_fields: bool = True, assigned: str | None = None
) -> tuple[io.BytesIO, str]:
    image = image_bytes()
    content_hash = hashlib.sha256(image).hexdigest()
    filename = f"images/{content_hash}.png"
    manifest = {
        filename: {
            "review_type": "model_review",
            "image_id": content_hash,
            "content_hash": "0" * 64 if mismatch else content_hash,
            "image_path": filename,
            "source_dataset": "Example",
            "source_label": "real",
            "normalized_label": "real",
            "label_source": "example_verified",
            "model_prediction": "medium",
            "confidence": "0.6",
            "prob_low": "0.3",
            "prob_medium": "0.6",
            "prob_high": "0.1",
            "model_version": "test-v1",
        }
    }
    if not optional_fields:
        for field in ("confidence", "prob_low", "prob_medium", "prob_high", "model_version"):
            manifest[filename].pop(field)
    if assigned:
        manifest[filename]["assigned_annotator"] = assigned
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(filename, image)
        archive.writestr("metadata.json", json.dumps(manifest))
    output.seek(0)
    return output, content_hash


def test_review_zip_maps_prediction_by_verified_hash_and_old_zip_still_works():
    archive, content_hash = review_zip()
    batch = prepare_zip(archive, "Review batch")[0]
    assert batch["dataset_role"] == "model_review"
    assert batch["images"][0]["content_hash"] == content_hash
    assert batch["images"][0]["provenance"]["model_prediction"] == "medium"
    with pytest.raises(AnnotationError, match="hash mismatch"):
        prepare_zip(review_zip(mismatch=True)[0], "Wrong mapping")
    assert (
        prepare_zip(review_zip(optional_fields=False)[0], "No optional fields")[0]["images"][0][
            "provenance"
        ]["model_prediction"]
        == "medium"
    )

    old = io.BytesIO()
    with zipfile.ZipFile(old, "w") as zipped:
        zipped.writestr("plain.png", image_bytes("red"))
    old.seek(0)
    assert prepare_zip(old, "Old ZIP")[0]["dataset_role"] == "custom"


def test_initial_is_immutable_and_resume_and_export_preserve_both_decisions(tmp_path):
    archive, content_hash = review_zip(assigned="Sara")
    store = SharedStore(tmp_path / "existing_store.sqlite3")
    batch = prepare_zip(archive, "Review batch")[0]
    store.import_batches([batch])
    with pytest.raises(AnnotationError, match="already belongs"):
        store.import_batches([prepare_zip(review_zip()[0], "Duplicate review batch")[0]])
    assert store.reserve("Sara", kind="annotation") is None
    assert store.reserve("Lorenzo", kind="model_review") is None
    lease = store.reserve("Sara", kind="model_review")
    assert lease["content_hash"] == content_hash
    with pytest.raises(AnnotationError, match="initial human label"):
        store.complete_model_review(lease["token"], "Sara", "high")

    store.save_model_review_draft(lease["token"], "Sara", initial="low")
    with pytest.raises(AnnotationError, match="cannot change"):
        store.save_model_review_draft(lease["token"], "Sara", initial="high")
    reopened = SharedStore(store.path)
    resumed = reopened.reserve("Sara", kind="model_review")
    assert resumed["token"] == lease["token"]
    assert reopened.draft(resumed)["human_initial_label"] == "low"
    reopened.save_model_review_draft(lease["token"], "Sara", final="medium")
    reopened.complete_model_review(lease["token"], "Sara", "medium")
    assert reopened.reserve("Sara", kind="model_review") is None

    rows = list(csv.DictReader(io.StringIO(reopened.export_csv("model_review").decode())))
    assert len(rows) == 1
    assert rows[0]["image_id"] == content_hash
    assert rows[0]["image_path"].endswith(f"{content_hash}.png")
    assert rows[0]["source_dataset"] == "Example" and rows[0]["source_label"] == "real"
    assert rows[0]["human_initial_label"] == "low"
    assert rows[0]["model_prediction"] == "medium"
    assert rows[0]["human_final_label"] == "medium"
    assert rows[0]["agreement_initial"] == "false"
    assert rows[0]["agreement_final"] == "true"
    assert rows[0]["model_confidence"] == "0.6"
    assert rows[0]["model_version"] == "test-v1"
    assert rows[0]["annotator"] == "Sara" and rows[0]["annotated_at"]
    assert list(csv.DictReader(io.StringIO(reopened.export_csv().decode()))) == []


def test_representative_and_targeted_parts_are_disjoint_and_exact():
    import random

    rows = [
        {
            "content_hash": f"{i:064x}",
            "source_dataset": "A" if i % 2 else "B",
            "source_label": "real" if i % 3 else "fake",
            "predicted_sensitivity_level": ("low", "medium", "high")[i % 3],
            "confidence_value": 0.4 + (i % 4) * 0.15,
        }
        for i in range(90)
    ]
    rng = random.Random(42)
    representative = proportional_sample(rows, 36, rng)
    parts = distribute(representative, ["sara", "lorenzo", "giovanni"], 12, rng, grouped=True)
    assert all(len(part) == 12 for part in parts.values())
    assert len({row["content_hash"] for part in parts.values() for row in part}) == 36


def test_streamlit_blind_reveal_and_next(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    archive, _ = review_zip()
    storage = tmp_path / "app.sqlite3"
    store = SharedStore(storage)
    store.import_batches(prepare_zip(archive, "My review batch"))
    monkeypatch.setenv("SENSIFAKE_STORAGE", str(storage))
    monkeypatch.setattr(sys, "argv", ["scripts/annotation/app.py"])
    app_path = Path(__file__).resolve().parents[1] / "scripts/annotation/app.py"
    app = AppTest.from_file(str(app_path)).run()
    app.text_input[0].set_value("Sara").run()
    app.sidebar.radio[0].set_value("Model review").run()
    next(
        button for button in app.button if button.label == "Resume or reserve an image"
    ).click().run()
    assert not app.exception and len(app.get("image")) == 1
    before = " ".join(element.value for element in app.markdown)
    assert "Model prediction: **medium**" not in before

    next(button for button in app.button if button.label == "1 Low").click().run()
    assert not app.exception
    after = " ".join(element.value for element in app.markdown)
    assert "Model prediction: **medium**" in after
    assert "DISAGREEMENT" in after
    next(radio for radio in app.radio if radio.label == "Final sensitivity").set_value(
        "medium"
    ).run()
    next(button for button in app.button if button.label == "Confirm and next").click().run()
    assert not app.exception
    rows = list(csv.DictReader(io.StringIO(store.export_csv("model_review").decode())))
    assert len(rows) == 1
    assert (rows[0]["human_initial_label"], rows[0]["human_final_label"]) == ("low", "medium")
