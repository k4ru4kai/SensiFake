import csv
import json
from pathlib import Path

from PIL import Image

from benchmark.deepfakebench_xception import (
    annotated_rows,
    automatic_rows,
    binary_metrics,
    grouped_metrics,
)


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def test_annotated_rows_excludes_unverified_and_unannotated_samples(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    Image.new("RGB", (2, 2), "white").save(image)
    fields = {
        "image_path": "image.png",
        "file_status": "readable",
        "annotation_join_status": "linked",
        "label_verification_status": "verified",
        "normalized_label": "fake",
        "sensitivity_level": "high",
        "content_hash": "hash",
    }
    write_manifest(
        tmp_path / "manifest.csv",
        [
            fields,
            {**fields, "annotation_join_status": "unannotated"},
            {**fields, "label_verification_status": "conflict"},
        ],
    )

    selected = annotated_rows(tmp_path / "manifest.csv", tmp_path)

    assert len(selected) == 1
    assert selected[0]["sensitivity_level"] == "high"
    assert selected[0]["resolved_image_path"] == image.resolve()


def test_binary_metrics_uses_fake_as_positive_class() -> None:
    metrics = binary_metrics([0, 0, 1, 1], [0.1, 0.8, 0.2, 0.9])

    assert metrics["accuracy"] == 0.5
    assert metrics["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert metrics["roc_auc"] == 0.75


def test_grouped_metrics_reports_each_source_dataset() -> None:
    rows = [
        {"source_dataset": "dataset-a", "label": 0, "probability_fake": 0.1},
        {"source_dataset": "dataset-a", "label": 1, "probability_fake": 0.9},
        {"source_dataset": "dataset-b", "label": 0, "probability_fake": 0.8},
        {"source_dataset": "dataset-b", "label": 1, "probability_fake": 0.2},
    ]

    metrics = grouped_metrics(rows, "source_dataset")

    assert list(metrics) == ["dataset-a", "dataset-b"]
    assert metrics["dataset-a"]["f1_fake"] == 1.0
    assert metrics["dataset-b"]["f1_fake"] == 0.0


def test_automatic_rows_uses_source_label_and_predicted_level(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(image)
    csv_path = tmp_path / "automatic.csv"
    write_manifest(
        csv_path,
        [{
            "content_hash": "hash",
            "source_dataset": "example/dataset",
            "source_label": "fake",
            "source_paths_json": json.dumps(["source.png"]),
            "predicted_sensitivity_level": "medium",
        }],
    )

    selected = automatic_rows(csv_path, tmp_path)

    assert selected[0]["normalized_label"] == "fake"
    assert selected[0]["source_dataset"] == "example/dataset"
    assert selected[0]["sensitivity_level"] == "medium"
    assert selected[0]["resolved_image_path"] == image.resolve()