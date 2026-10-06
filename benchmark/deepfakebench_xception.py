"""Evaluate annotated SensiFake images with DeepfakeBench's Effort detector.

The script imports DeepfakeBench instead of copying its model code. It keeps the
SensiFake manifest as the source of truth for image paths, labels, and sensitivity.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ("low", "medium", "high")


def repository_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"{description} not found: {path}. "
            "Clone DeepfakeBench and pass paths from that checkout."
        )


def require_directory(path: Path, description: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{description} not found: {path}")


def annotated_rows(manifest: Path, root: Path = ROOT) -> list[dict[str, Any]]:
    """Return the complete, evaluable human-annotated population."""
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = []
    for row in rows:
        if (
            row.get("file_status") == "readable"
            and row.get("annotation_join_status") == "linked"
            and row.get("label_verification_status") == "verified"
            and row.get("normalized_label") in ("real", "fake")
            and row.get("sensitivity_level") in LEVELS
        ):
            image_path = (root / row["image_path"]).resolve()
            if not image_path.is_file():
                raise FileNotFoundError(f"Image referenced by manifest is missing: {image_path}")
            selected.append({**row, "resolved_image_path": image_path})
    if not selected:
        raise ValueError("No readable, linked, verified annotated images were found")
    return selected


def automatic_rows(csv_path: Path, root: Path = ROOT) -> list[dict[str, Any]]:
    """Load automatic sensitivity predictions and verified source labels."""
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = []
    for row in rows:
        if row.get("real_fake_label_name") in ("real", "fake"):
            sensitivity_level = row.get("final_sensitivity_label")
            image_path = (root / row["source_original_path"]).resolve()
            if sensitivity_level in LEVELS and image_path.is_file():
                selected.append({
                    "content_hash": row["sha256"],
                    "image_path": row["source_original_path"],
                    "sensitivity_level": sensitivity_level,
                    "normalized_label": row["real_fake_label_name"],
                    "resolved_image_path": image_path,
                })
            continue
        sensitivity_level = (
            row.get("adjudicated_sensitivity_level")
            or row.get("sensitivity_level")
            or row.get("predicted_sensitivity_level")
        )
        if (
            row.get("source_label") in ("real", "fake")
            and sensitivity_level in LEVELS
        ):
            source_paths = json.loads(row["source_paths_json"])
            if not source_paths:
                continue
            image_path = (root / source_paths[0]).resolve()
            if not image_path.is_file():
                continue
            selected.append({
                "content_hash": row["content_hash"],
                "image_path": source_paths[0],
                "sensitivity_level": sensitivity_level,
                "normalized_label": row["source_label"],
                "resolved_image_path": image_path,
            })
    if not selected:
        raise ValueError("No valid automatic sensitivity predictions were found")
    return selected


def binary_metrics(labels: list[int], probabilities: list[float]) -> dict[str, Any]:
    """Compute metrics without requiring scikit-learn in the host project."""
    if len(labels) != len(probabilities) or not labels:
        raise ValueError("labels and probabilities must be non-empty and equally sized")
    predicted = [int(probability >= 0.5) for probability in probabilities]
    tn = sum(label == 0 and prediction == 0 for label, prediction in zip(labels, predicted))
    fp = sum(label == 0 and prediction == 1 for label, prediction in zip(labels, predicted))
    fn = sum(label == 1 and prediction == 0 for label, prediction in zip(labels, predicted))
    tp = sum(label == 1 and prediction == 1 for label, prediction in zip(labels, predicted))
    positive = sum(labels)
    negative = len(labels) - positive
    true_positive_rate = tp / positive if positive else None
    true_negative_rate = tn / negative if negative else None
    auc = None
    if positive and negative:
        ordered = sorted(zip(probabilities, labels), key=lambda item: item[0])
        rank_sum = sum(index for index, (_, label) in enumerate(ordered, 1) if label)
        auc = (rank_sum - positive * (positive + 1) / 2) / (positive * negative)
    return {
        "count": len(labels),
        "real": negative,
        "fake": positive,
        "accuracy": (tp + tn) / len(labels),
        "balanced_accuracy": (
            (true_positive_rate + true_negative_rate) / 2
            if true_positive_rate is not None and true_negative_rate is not None
            else None
        ),
        "precision_fake": tp / (tp + fp) if tp + fp else None,
        "recall_fake": true_positive_rate,
        "f1_fake": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "roc_auc": auc,
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plot_level(output: Path, level: str, metrics: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt

    level_dir = output / level
    level_dir.mkdir(parents=True, exist_ok=True)
    confusion = metrics["confusion_matrix"]
    figure, axis = plt.subplots(figsize=(5, 4))
    matrix = [[confusion["tn"], confusion["fp"]], [confusion["fn"], confusion["tp"]]]
    image = axis.imshow(matrix, cmap="Blues")
    axis.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["real", "fake"],
             yticklabels=["real", "fake"], xlabel="Predicted", ylabel="Annotated",
             title=f"Effort confusion matrix: {level}")
    for row_index in range(2):
        for column_index in range(2):
            axis.text(column_index, row_index, matrix[row_index][column_index], ha="center", va="center")
    figure.colorbar(image, ax=axis)
    figure.tight_layout()
    figure.savefig(level_dir / "confusion_matrix.png", dpi=160)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(6, 4))
    for label, color in ((0, "#2563eb"), (1, "#dc2626")):
        values = sorted(row["probability_fake"] for row in rows if row["label"] == label)
        if values:
            axis.plot(range(1, len(values) + 1), values, ".", color=color,
                      label="fake" if label else "real")
    axis.set(xlabel="Samples sorted by fake probability", ylabel="P(fake)", title=f"Effort scores: {level}")
    axis.legend()
    figure.tight_layout()
    figure.savefig(level_dir / "probabilities.png", dpi=160)
    plt.close(figure)


def load_effort_model(args: argparse.Namespace, config: dict[str, Any]):
    """Load Effort and redirect its hardcoded CLIP path to the CLI path."""
    deepfakebench = args.deepfakebench.resolve()
    training = deepfakebench / "training"
    require_directory(training / "detectors", "DeepfakeBench training package")
    require_directory(args.effort_model, "Effort Hugging Face CLIP model directory")
    landmark_model = deepfakebench / "preprocessing/dlib_tools/shape_predictor_81_face_landmarks.dat"
    if not landmark_model.is_file():
        raise FileNotFoundError(
            f"DeepfakeBench landmark model not found: {landmark_model}. "
            "Download it from https://github.com/SCLBD/DeepfakeBench/releases/download/"
            "v1.0.0/shape_predictor_81_face_landmarks.dat"
        )
    sys.path.insert(0, str(training))
    previous_cwd = Path.cwd()
    os.chdir(deepfakebench)
    try:
        import torch
        from transformers import CLIPModel

        original_from_pretrained = CLIPModel.from_pretrained

        def redirected_from_pretrained(cls, model_name_or_path, *positional, **keyword):
            return original_from_pretrained(args.effort_model, *positional, **keyword)

        CLIPModel.from_pretrained = classmethod(redirected_from_pretrained)
        from detectors import DETECTOR

        model = DETECTOR["effort"](config)
        checkpoint = torch.load(args.weights, map_location="cpu")
        if isinstance(checkpoint, dict):
            for key in ("state_dict", "model_state_dict", "model", "net"):
                if key in checkpoint and isinstance(checkpoint[key], dict):
                    checkpoint = checkpoint[key]
                    break
        checkpoint = {key.removeprefix("module."): value for key, value in checkpoint.items()}
        incompatible = model.load_state_dict(checkpoint, strict=False)
        if len(incompatible.missing_keys) > 4:
            raise RuntimeError(
                "Effort checkpoint did not match the model; missing keys include "
                f"{incompatible.missing_keys[:5]}"
            )
        device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
        return model.to(device).eval(), torch, device
    finally:
        os.chdir(previous_cwd)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    args.annotations = repository_path(args.annotations)
    args.deepfakebench = repository_path(args.deepfakebench)
    args.detector_config = repository_path(args.detector_config)
    args.effort_model = repository_path(args.effort_model)
    args.weights = repository_path(args.weights)
    args.output = repository_path(args.output)
    require_file(args.annotations, "SensiFake annotation CSV")
    require_file(args.detector_config, "DeepfakeBench Effort detector config")
    require_directory(args.effort_model, "Effort Hugging Face CLIP model directory")
    if not args.weights.is_file():
        raise FileNotFoundError(
            f"Effort detector checkpoint not found: {args.weights}. "
            "DeepfakeBench v1.0.1 does not publish an Effort checkpoint; "
            "do not substitute xception_best.pth. Provide a compatible Effort "
            "checkpoint or train Effort first."
        )
    import numpy as np
    import yaml

    with args.annotations.open(encoding="utf-8", newline="") as stream:
        fields = set(csv.DictReader(stream).fieldnames or ())
    rows = automatic_rows(args.annotations) if (
        {"predicted_sensitivity_level", "real_fake_label_name"} & fields
    ) else annotated_rows(args.annotations)
    with args.detector_config.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    model, torch, device = load_effort_model(args, config)
    mean = torch.tensor(args.mean, dtype=torch.float32).view(3, 1, 1)
    std = torch.tensor(args.std, dtype=torch.float32).view(3, 1, 1)
    predictions = []
    with torch.no_grad():
        for start in range(0, len(rows), args.batch_size):
            batch_rows = rows[start:start + args.batch_size]
            images = []
            for row in batch_rows:
                from PIL import Image
                with Image.open(row["resolved_image_path"]) as image:
                    image = image.convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
                    images.append(np.asarray(image, dtype=np.float32) / 255.0)
            tensor = torch.from_numpy(np.stack(images)).permute(0, 3, 1, 2)
            tensor = ((tensor - mean) / std).to(device)
            output = model({"image": tensor, "label": torch.zeros(len(images), dtype=torch.long, device=device)}, inference=True)
            probabilities = output["prob"].detach().cpu().tolist()
            for row, probability in zip(batch_rows, probabilities):
                predictions.append({"content_hash": row["content_hash"], "image_path": row["image_path"],
                                    "sensitivity_level": row["sensitivity_level"],
                                    "label": int(row["normalized_label"] == "fake"),
                                    "probability_fake": probability})

    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "predictions.csv", predictions)
    (args.output / "predictions.json").write_text(
        json.dumps(predictions, indent=2) + "\n", encoding="utf-8"
    )
    metrics = {"all": binary_metrics([r["label"] for r in predictions], [r["probability_fake"] for r in predictions])}
    for level in LEVELS:
        level_rows = [row for row in predictions if row["sensitivity_level"] == level]
        if not level_rows:
            raise ValueError(f"No annotated images in sensitivity level {level}")
        metrics[level] = binary_metrics([r["label"] for r in level_rows], [r["probability_fake"] for r in level_rows])
        write_csv(args.output / level / "predictions.csv", level_rows)
        (args.output / level / "metrics.json").write_text(json.dumps(metrics[level], indent=2) + "\n", encoding="utf-8")
        plot_level(args.output, level, metrics[level], level_rows)
    metrics["selection_counts"] = dict(Counter(row["sensitivity_level"] for row in predictions))
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=ROOT / "annotations/human-train-v0/automatic_annotation/sensifake_complete_sensitivity.csv")
    parser.add_argument("--deepfakebench", type=Path, required=True, help="DeepfakeBench checkout")
    parser.add_argument("--detector-config", type=Path, default=ROOT / "external/DeepfakeBench/training/config/detector/effort.yaml")
    parser.add_argument("--effort-model", type=Path, required=True, help="Local openai/clip-vit-large-patch14 directory")
    parser.add_argument("--weights", type=Path, required=True, help="DeepfakeBench Effort detector checkpoint")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark/results/deepfakebench-effort")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--mean", type=float, nargs=3, default=(0.48145466, 0.4578275, 0.40821073))
    parser.add_argument("--std", type=float, nargs=3, default=(0.26862954, 0.26130258, 0.27577711))
    parser.add_argument("--device", choices=("cpu", "cuda"), default=None)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(evaluate(parse_args()), indent=2))