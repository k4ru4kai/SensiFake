"""Deterministic, immutable human-training assignments and blinded task loading."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .gold_silver_assignment import ASSIGNMENT_FIELDS, load_assignment_csv
from scripts.annotation.annotation_schema import AnnotationError, BlindedSample
from scripts.annotation.paths import REPOSITORY_ROOT, gold_silver_assignment_path

DEFAULT_OUTPUT = REPOSITORY_ROOT / "annotations/splits/human_train_assignment.csv"
DEFAULT_INPUT = gold_silver_assignment_path()
DEFAULT_TASKS = REPOSITORY_ROOT / "annotations/tasks/human-train-v0"
MASTER_FIELDS = (
    *ASSIGNMENT_FIELDS,
    "assignment_role",
    "annotator_id",
    "annotation_order",
    "human_train_seed",
)
TASK_FIELDS = ("blind_id", "content_hash", "component", "relative_image_path", "annotation_order")
STRATA = tuple(
    (source, label)
    for source in ("ComplexDataLab/OpenFake", "saberzl/SID_Set")
    for label in ("real", "fake")
)
COMPONENT_PATHS = {
    "openfake_pilot_600": "data/datasets/openfake/pilot-600",
    "openfake_additional_900": "data/datasets/openfake/additional-900",
    "sid_set_candidate_1500": "data/datasets/sid-set/candidate-1500",
}


def validate_annotator(annotator: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", annotator):
        raise AnnotationError("Invalid annotator ID: use 1–64 ASCII letters, digits, _ or -.")
    return annotator


def _rank(seed: int, purpose: str, content_hash: str) -> str:
    return hashlib.sha256(f"{seed}:{purpose}:{content_hash}".encode()).hexdigest()


def build_human_train_assignment(
    annotators: Sequence[str],
    *,
    input_path: Path = DEFAULT_INPUT,
    seed: int = 42,
) -> list[dict[str, str]]:
    """Sample by SHA-256 ranking; input and annotator argument order do not affect output."""
    if len(annotators) != 3 or len({item.casefold() for item in annotators}) != 3:
        raise AnnotationError("Exactly three distinct annotator IDs are required.")
    ids = sorted(validate_annotator(item) for item in annotators)
    # Reuse canonical validation, including unique hashes and frozen Gold/Silver counts.
    records = load_assignment_csv(input_path)
    assigned: dict[str, list[dict[str, str]]] = {item: [] for item in ids}
    for source, label in STRATA:
        candidates = [
            r
            for r in records
            if r.role == "unassigned" and (r.source_dataset, r.normalized_label) == (source, label)
        ]
        candidates.sort(key=lambda r: (_rank(seed, "selection", r.content_hash), r.content_hash))
        if len(candidates) < 75:
            raise AnnotationError(
                f"Insufficient unassigned images for {source} / {label}: "
                f"{len(candidates)}; need 75."
            )
        for index, annotator in enumerate(ids):
            for record in candidates[index * 25 : (index + 1) * 25]:
                row = {field: str(getattr(record, field)) for field in ASSIGNMENT_FIELDS}
                row.update(
                    assignment_role="human_train",
                    annotator_id=annotator,
                    human_train_seed=str(seed),
                )
                assigned[annotator].append(row)
    result = []
    for annotator, rows in assigned.items():
        rows.sort(
            key=lambda row: (
                _rank(seed, f"order:{annotator}", row["content_hash"]),
                row["content_hash"],
            )
        )
        for order, row in enumerate(rows, 1):
            row["annotation_order"] = str(order)
            result.append(row)
    return result


def serialize_csv(rows: Sequence[dict[str, str]], fields: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def assignment_files(
    rows: list[dict[str, str]],
    *,
    output: Path = DEFAULT_OUTPUT,
    tasks_dir: Path = DEFAULT_TASKS,
) -> dict[Path, bytes]:
    files = {output: serialize_csv(rows, MASTER_FIELDS)}
    for annotator in sorted({row["annotator_id"] for row in rows}):
        validate_annotator(annotator)
        task = []
        for row in sorted(
            (r for r in rows if r["annotator_id"] == annotator),
            key=lambda r: int(r["annotation_order"]),
        ):
            item = {field: row[field] for field in TASK_FIELDS if field != "blind_id"}
            item["blind_id"] = (
                "HT-"
                + hashlib.sha256(f"human-train-v0:{row['content_hash']}".encode()).hexdigest()[:20]
            )
            task.append(item)
        target = tasks_dir / f"{annotator}.csv"
        if target.resolve() in {path.resolve() for path in files}:
            raise AnnotationError("Master and task output paths must be distinct.")
        files[target] = serialize_csv(task, TASK_FIELDS)
    return files


def write_assignment_files(files: dict[Path, bytes], *, input_path: Path) -> str:
    """Preflight every file; publish complete files without replacing existing targets."""
    for path, payload in files.items():
        if path.resolve() == input_path.resolve() or (
            path.exists() and input_path.exists() and path.samefile(input_path)
        ):
            raise AnnotationError("Output must not overwrite the original Gold/Silver CSV.")
        if path.is_symlink():
            raise AnnotationError(f"Refusing symlink output: {path}")
        if path.exists() and path.read_bytes() != payload:
            raise AnnotationError(f"Existing output differs: {path}; refusing to overwrite.")
    created = False
    for path, payload in files.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                os.link(temporary, path)
                created = True
            finally:
                temporary.unlink(missing_ok=True)
    return "created" if created else "unchanged"


def _contained_path(root: Path, relative: Path) -> Path:
    path = root / relative
    if path.resolve() != root.resolve() / relative:
        raise AnnotationError(f"Unsafe path or symlink: {path}")
    return path


def list_annotators(repository_root: Path = REPOSITORY_ROOT) -> list[str]:
    directory = repository_root / "annotations/tasks/human-train-v0"
    return sorted(validate_annotator(path.stem) for path in directory.glob("*.csv"))


def human_train_annotation_path(annotator: str, repository_root: Path = REPOSITORY_ROOT) -> Path:
    validate_annotator(annotator)
    return _contained_path(
        repository_root, Path(f"annotations/human-train-v0/{annotator}/sensitivity_annotations.csv")
    )


def load_human_train_task(
    annotator: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> list[BlindedSample]:
    validate_annotator(annotator)
    task = _contained_path(
        repository_root, Path(f"annotations/tasks/human-train-v0/{annotator}.csv")
    )
    if not task.is_file():
        raise AnnotationError(
            f"No task file for annotator '{annotator}': {task}. "
            "Ask the maintainer or use --list-annotators."
        )
    with task.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(TASK_FIELDS):
            raise AnnotationError(f"Invalid blinded task columns: {task}")
        rows = list(reader)
    try:
        rows.sort(key=lambda row: int(row["annotation_order"]))
        if (
            len(rows) != 100
            or [int(r["annotation_order"]) for r in rows] != list(range(1, 101))
            or any(not r["content_hash"] or not r["blind_id"] for r in rows)
            or len({r["content_hash"] for r in rows}) != 100
            or len({r["blind_id"] for r in rows}) != 100
        ):
            raise ValueError("expected 100 unique images and blind IDs, ordered 1–100")
        samples = []
        for row in rows:
            relative = Path(row["relative_image_path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("image path must be relative without traversal")
            image = _contained_path(
                repository_root, Path(COMPONENT_PATHS[row["component"]]) / relative
            )
            if not image.is_file():
                raise AnnotationError(f"Task image missing for annotator '{annotator}': {image}")
            samples.append(BlindedSample(row["content_hash"], image, row["blind_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AnnotationError(f"Invalid task file {task}: {exc}") from exc
    return samples
