"""Selection balance, unique identities, frozen reruns and annotator import compatibility."""

import csv
import hashlib
import io
import json

import pytest
from PIL import Image

from scripts.datasets.select_rrdataset_batch import STRATA, create_batch, select_rows
from scripts.annotation.import_batches import prepare_zip


def pool(tmp_path):
    rows = []
    for number, (person, label) in enumerate(STRATA):
        for index in range(2):
            relative = f"rr/{person}/{'ai' if label == 'fake' else 'real'}/{index}.png"
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), (number * 30, index * 100, 20)).save(buffer, "PNG")
            path.write_bytes(buffer.getvalue())
            rows.append(
                {
                    "source_dataset": "RRDataset",
                    "image_path": relative,
                    "content_hash": hashlib.sha256(buffer.getvalue()).hexdigest(),
                    "file_status": "readable",
                    "annotation_join_status": "unannotated",
                    "normalized_label": "unknown",
                    "label_verification_status": "unverified",
                    "label_evidence_json": "[]",
                    "original_image_id": path.name,
                }
            )
    return rows


def test_balanced_distinct_and_independent_of_input_order(tmp_path):
    rows = pool(tmp_path)
    rows.append({**rows[0], "image_path": "rr/giovanni/real/copy.png"})
    first, report = select_rows(rows, per_stratum=1)
    second, _ = select_rows(list(reversed(rows)), per_stratum=1)
    assert first == second
    assert len(first) == len({r["content_hash"] for r in first}) == 6
    assert {(r["selection_group"], r["selection_label_hint"]) for r in first} == set(STRATA)
    assert all(r["normalized_label"] == "unknown" for r in first)
    assert len(report["duplicate_references"]) == 1


def test_does_not_fill_quotas_with_already_annotated_images(tmp_path):
    rows = pool(tmp_path)
    rows[0]["annotation_join_status"] = "linked"
    with pytest.raises(ValueError, match="Insufficient"):
        select_rows(rows, per_stratum=2)


def test_deterministic_zip_and_safe_frozen_rerun(tmp_path):
    rows = pool(tmp_path)
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "output"
    first = create_batch(manifest, output, root=tmp_path, per_stratum=1)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    second = create_batch(manifest, output, root=tmp_path, per_stratum=1)
    assert first == second
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    batch = prepare_zip(output / "annotation_batch.zip", "RR 300", "rrdataset")[0]
    assert len(batch["images"]) == 6
    assert all(r["provenance"]["normalized_label"] == "unknown" for r in batch["images"])
    assert all(r["original_filename"].startswith("images/") for r in batch["images"])
    with pytest.raises(ValueError, match="Existing selection differs"):
        create_batch(manifest, output, root=tmp_path, seed=123, per_stratum=1)
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}
    assert json.loads((output / "selection_report.json").read_text())["unique_hashes"] == 6
