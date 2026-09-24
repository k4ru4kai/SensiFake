"""Audit selected local images and incrementally join immutable human annotations.

The working manifest is curator-only. No output is fed into either Streamlit app.
All outputs are deterministic; source images, CSVs and manifests are read-only.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sensifake_annotation.core import ANNOTATION_FIELDS, _annotation_from_row

COLLECTIONS = (
    ("OpenFake", "openfake_pilot_600", "data/datasets/openfake/pilot-600/manifest.jsonl"),
    ("OpenFake", "openfake_additional_900", "data/datasets/openfake/additional-900/manifest.jsonl"),
    ("SID-Set", "sid_set_candidate_1500", "data/datasets/sid-set/candidate-1500/manifest.jsonl"),
)
DEFAULT_ANNOTATIONS = (
    "annotations/human-train-v0/SensiFake_annotations_401/sensitivity_annotations_401.csv"
)
RR_SELECTION = "data/datasets/RRDataset/selection_1500"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
FIELDS = (
    "image_id",
    "source_dataset",
    "component",
    "original_image_id",
    "original_id_status",
    "image_path",
    "file_status",
    "content_hash",
    "declared_content_hash",
    "normalized_label",
    "label_verification_status",
    "label_evidence_json",
    "label_hint",
    "label_hint_source",
    "source_metadata_json",
    "annotation_join_status",
    "annotation_record_id",
    "annotator_id",
    "dataset_role",
    "annotation_source",
    *(field for field in ANNOTATION_FIELDS if field != "content_hash"),
    "annotation_original_json",
)


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reference(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def inspect_image(path: Path) -> tuple[str, str]:
    try:
        with path.open("rb") as stream:
            content_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    except FileNotFoundError:
        return "", "missing"
    except OSError:
        return "", "unreadable"
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        return content_hash, "invalid_image"
    return content_hash, "readable"


def image_row(
    root: Path, path: Path, dataset: str, component: str, original_id: str, metadata: dict
) -> dict:
    location = reference(path, root)
    content_hash, status = inspect_image(path)
    return {
        **dict.fromkeys(FIELDS, ""),
        "image_id": digest(f"{dataset}:{location}".encode()),
        "source_dataset": dataset,
        "component": component,
        "original_image_id": original_id,
        "original_id_status": "source_metadata" if original_id else "not_recorded",
        "image_path": location,
        "file_status": status,
        "content_hash": content_hash,
        "normalized_label": "unknown",
        "label_verification_status": "unverified",
        "label_evidence_json": "[]",
        "source_metadata_json": canonical_json(metadata),
        "annotation_join_status": "unannotated",
    }


def resolve_class(row: dict, evidence: list[dict]) -> None:
    row["label_evidence_json"] = canonical_json(evidence)
    labels = {e["label"] for e in evidence if e["label"] in ("real", "fake")}
    if len(labels) == 1:
        row["normalized_label"] = next(iter(labels))
        row["label_verification_status"] = "verified"
    elif len(labels) > 1:
        row["normalized_label"] = "unknown"
        row["label_verification_status"] = "conflict"


def collect_images(
    root: Path, rr_root: Path, rr_evidence: list[dict]
) -> tuple[list[dict], list[dict]]:
    rows, issues = [], []
    evidence_by_hash = defaultdict(list)
    for entry in rr_evidence:
        if (
            len(entry.get("content_hash", "")) != 64
            or entry.get("normalized_label") not in ("real", "fake")
            or not entry.get("evidence_reference")
            or not entry.get("original_reference")
        ):
            raise ValueError(
                "RR evidence requires content_hash, normalized_label, original_reference, evidence_reference"
            )
        evidence_by_hash[entry["content_hash"]].append(
            {
                "label": entry["normalized_label"],
                "kind": "supplied_authoritative_metadata",
                "reference": entry["evidence_reference"],
                "original_reference": entry["original_reference"],
            }
        )
    for dataset, component, manifest in COLLECTIONS:
        source = root / manifest
        if not source.is_file():
            issues.append({"type": "missing_manifest", "path": manifest})
            continue
        referenced = set()
        for number, line in enumerate(source.read_text().splitlines(), 1):
            if not line.strip():
                continue
            metadata = json.loads(line)
            relative = Path(metadata["relative_image_path"])
            path = source.parent / relative
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not path.resolve().is_relative_to(source.parent.resolve())
            ):
                raise ValueError(f"Unsafe image reference in {manifest}:{number}")
            referenced.add(path)
            row = image_row(
                root, path, dataset, component, str(metadata.get("sample_id") or ""), metadata
            )
            declared = metadata.get("content_hash", "")
            row["declared_content_hash"] = declared
            if row["content_hash"] and row["content_hash"] != declared:
                row["file_status"] = "hash_mismatch"
            evidence = []
            normalized = metadata.get("normalized_label")
            if normalized in ("real", "fake"):
                evidence.append(
                    {
                        "label": normalized,
                        "kind": "collection_manifest",
                        "reference": f"{manifest}:{number}:normalized_label",
                    }
                )
            native = str(metadata.get("original_label", ""))
            decoded = {"0": "real", "1": "fake"}.get(native) if dataset == "SID-Set" else native
            if decoded in ("real", "fake"):
                evidence.append(
                    {
                        "label": decoded,
                        "kind": "source_label",
                        "reference": f"{manifest}:{number}:original_label",
                        "value": native,
                    }
                )
            resolve_class(row, evidence)
            # A label from a manifest whose hash does not match cannot identify these bytes.
            if row["file_status"] == "hash_mismatch":
                row.update(normalized_label="unknown", label_verification_status="hash_mismatch")
            rows.append(row)
        for path in sorted((source.parent / "images").rglob("*")):
            if (
                path.is_file()
                and path.suffix.lower() in IMAGE_EXTENSIONS
                and path not in referenced
            ):
                row = image_row(root, path, dataset, component, "", {})
                rows.append(row)
                issues.append(
                    {
                        "type": "image_not_in_manifest",
                        "image_id": row["image_id"],
                        "path": row["image_path"],
                    }
                )
    if not rr_root.is_dir():
        issues.append({"type": "missing_rr_selection", "path": reference(rr_root, root)})
    for path in sorted(rr_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        row = image_row(root, path, "RRDataset", "rrdataset_selection_1500", path.name, {})
        row["original_id_status"] = "local_filename_only"
        row["label_hint"] = {"real": "real", "ai": "fake"}.get(path.parent.name, "")
        row["label_hint_source"] = reference(path.parent, root) if row["label_hint"] else ""
        resolve_class(row, evidence_by_hash.get(row["content_hash"], []))
        rows.append(row)
    found_rr = {r["content_hash"] for r in rows if r["source_dataset"] == "RRDataset"}
    for content_hash in sorted(evidence_by_hash.keys() - found_rr):
        issues.append({"type": "unmatched_rr_label_evidence", "content_hash": content_hash})
    return rows, issues


def merge_annotations(
    existing: list[dict], inputs: list[tuple[str, str, list[dict]]]
) -> list[dict]:
    """Union immutable records. Changed decisions become separate conflict variants."""
    records = {}
    for entry in existing:
        if entry["annotation_record_id"] != digest(canonical_json(entry["original"]).encode()):
            raise ValueError("Annotation registry integrity check failed")
        records[entry["annotation_record_id"]] = entry
    for source, source_hash, source_rows in inputs:
        for line_number, original in enumerate(source_rows, 2):
            key = digest(canonical_json(original).encode())
            if key not in records:
                error = ""
                try:
                    _annotation_from_row(
                        {field: original[field] for field in ANNOTATION_FIELDS}, line_number
                    )
                    if not original.get("annotator_id"):
                        raise ValueError("Missing annotator_id")
                except (ValueError, KeyError, TypeError) as exc:
                    error = str(exc)
                records[key] = {
                    "annotation_record_id": key,
                    "source": source,
                    "source_sha256": source_hash,
                    "source_row": line_number,
                    "validation_error": error,
                    "original": original,
                }
    return sorted(records.values(), key=lambda r: r["annotation_record_id"])


def join_annotations(rows: list[dict], annotations: list[dict]) -> tuple[list[dict], list[dict]]:
    images_by_hash, annotations_by_hash = defaultdict(list), defaultdict(list)
    for row in rows:
        if row["content_hash"]:
            images_by_hash[row["content_hash"]].append(row)
    for entry in annotations:
        annotations_by_hash[entry["original"].get("content_hash", "")].append(entry)
    annotation_results, issues = [], []
    for content_hash, entries in sorted(annotations_by_hash.items()):
        candidates = images_by_hash.get(content_hash, [])
        status = "linked"
        if not candidates:
            status = "unmatched"
        elif len(candidates) > 1:
            status = "ambiguous_image"
        elif candidates[0]["file_status"] != "readable":
            status = "image_integrity_problem"
        elif any(e["validation_error"] for e in entries):
            status = "invalid_annotation"
        elif len(entries) > 1:
            status = "conflicting_annotations"
        # Check source identity/path as well as the byte hash when the export supplies them.
        if status == "linked":
            original, image = entries[0]["original"], candidates[0]
            if (
                original.get("component")
                and original["component"] != image["component"]
                or original.get("relative_image_path")
                and not image["image_path"].endswith("/" + original["relative_image_path"])
            ):
                status = "annotation_metadata_conflict"
        for entry in entries:
            annotation_results.append(
                {
                    "annotation_record_id": entry["annotation_record_id"],
                    "content_hash": content_hash,
                    "status": status,
                    "image_ids": [r["image_id"] for r in candidates],
                    "source": entry["source"],
                    "source_row": entry["source_row"],
                    "validation_error": entry["validation_error"],
                }
            )
        for image in candidates:
            image["annotation_join_status"] = status
        if status != "linked":
            continue
        entry, image = entries[0], candidates[0]
        original = entry["original"]
        for field in ANNOTATION_FIELDS:
            if field != "content_hash":
                image[field] = original[field]
        image.update(
            annotation_record_id=entry["annotation_record_id"],
            annotator_id=original["annotator_id"],
            dataset_role=original.get("dataset_role", ""),
            annotation_source=entry["source"],
            annotation_original_json=canonical_json(original),
        )
        supplied_label = original.get("normalized_label")
        if (
            supplied_label in ("real", "fake")
            and image["normalized_label"] in ("real", "fake")
            and supplied_label != image["normalized_label"]
        ):
            evidence = json.loads(image["label_evidence_json"])
            evidence.append(
                {
                    "kind": "annotation_export_metadata",
                    "label": supplied_label,
                    "reference": entry["source"],
                }
            )
            resolve_class(image, evidence)
            issues.append({"type": "annotation_label_conflict", "image_id": image["image_id"]})
    return annotation_results, issues


def audit(rows: list[dict], annotation_results: list[dict], issues: list[dict]) -> dict:
    hashes, image_ids, original_ids = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        image_ids[row["image_id"]].append(row["image_path"])
        if row["content_hash"]:
            hashes[row["content_hash"]].append(row)
        if row["original_image_id"]:
            original_ids[(row["source_dataset"], row["original_image_id"])].append(row["image_id"])
    for content_hash, images in hashes.items():
        verified = {r["normalized_label"] for r in images if r["normalized_label"] != "unknown"}
        if len(verified) > 1:
            issues.append(
                {
                    "type": "hash_label_conflict",
                    "content_hash": content_hash,
                    "image_ids": [r["image_id"] for r in images],
                }
            )
            for image in images:
                image.update(normalized_label="unknown", label_verification_status="conflict")
    counts = {}
    for dataset in ("OpenFake", "SID-Set", "RRDataset"):
        selected = [r for r in rows if r["source_dataset"] == dataset]
        counts[dataset] = {
            "selected_rows": len(selected),
            "unique_content_hashes": len(
                {r["content_hash"] for r in selected if r["content_hash"]}
            ),
            "file_status": dict(sorted(Counter(r["file_status"] for r in selected).items())),
            "labels": {
                label: sum(r["normalized_label"] == label for r in selected)
                for label in ("real", "fake", "unknown")
            },
            "label_verification": dict(
                sorted(Counter(r["label_verification_status"] for r in selected).items())
            ),
            "original_id_status": dict(
                sorted(Counter(r["original_id_status"] for r in selected).items())
            ),
            "annotation_join_status": dict(
                sorted(Counter(r["annotation_join_status"] for r in selected).items())
            ),
        }
    return {
        "sources": counts,
        "total_rows": len(rows),
        "unique_image_ids": len(image_ids),
        "unique_content_hashes": len(hashes),
        "duplicate_image_ids": {
            key: paths for key, paths in sorted(image_ids.items()) if len(paths) > 1
        },
        "duplicate_original_ids": [
            {"source_dataset": key[0], "original_image_id": key[1], "image_ids": ids}
            for key, ids in sorted(original_ids.items())
            if len(ids) > 1
        ],
        "duplicate_hashes": [
            {"content_hash": key, "image_paths": [r["image_path"] for r in images]}
            for key, images in sorted(hashes.items())
            if len(images) > 1
        ],
        "annotation_counts": dict(sorted(Counter(r["status"] for r in annotation_results).items())),
        "annotation_results": annotation_results,
        "label_problems": [
            {
                "image_id": r["image_id"],
                "image_path": r["image_path"],
                "status": r["label_verification_status"],
                "evidence": json.loads(r["label_evidence_json"]),
            }
            for r in rows
            if r["label_verification_status"] != "verified"
        ],
        "file_problems": [
            {
                "image_id": r["image_id"],
                "image_path": r["image_path"],
                "status": r["file_status"],
                "declared_content_hash": r["declared_content_hash"],
                "content_hash": r["content_hash"],
            }
            for r in rows
            if r["file_status"] != "readable"
        ],
        "issues": issues,
    }


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build(
    root: Path,
    output: Path,
    annotation_paths: list[Path],
    rr_root: Path,
    evidence_path: Path | None = None,
) -> dict:
    root, output = root.resolve(), output.resolve()
    # Derived output must never replace an input directory or any source files.
    if (
        any(output == path.parent.resolve() for path in annotation_paths)
        or output == rr_root.resolve()
    ):
        raise ValueError("Output directory must be separate from input directories")
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows, issues = collect_images(
            root, rr_root, read_csv(evidence_path) if evidence_path else []
        )
        registry = output / "human_annotations.jsonl"
        existing = (
            [json.loads(line) for line in registry.read_text().splitlines()]
            if registry.exists()
            else []
        )
        inputs = [
            (reference(p.resolve(), root), digest(p.read_bytes()), read_csv(p))
            for p in annotation_paths
        ]
        annotations = merge_annotations(existing, inputs)
        results, join_issues = join_annotations(rows, annotations)
        report = audit(rows, results, issues + join_issues)
        report["annotation_input_files"] = [
            {"path": p, "sha256": h, "rows": len(r)} for p, h, r in inputs
        ]
        report["rr_label_evidence"] = (
            {
                "path": reference(evidence_path.resolve(), root),
                "sha256": digest(evidence_path.read_bytes()),
            }
            if evidence_path
            else None
        )
        rows.sort(key=lambda row: (row["source_dataset"], row["image_path"]))
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        manifest_bytes = buffer.getvalue().encode()
        registry_bytes = ("".join(canonical_json(r) + "\n" for r in annotations)).encode()
        report["output_sha256"] = {
            "selected_images.csv": digest(manifest_bytes),
            "human_annotations.jsonl": digest(registry_bytes),
        }
        # The immutable registry is committed first; interrupted derived outputs are rebuilt next run.
        atomic_write(registry, registry_bytes)
        atomic_write(output / "selected_images.csv", manifest_bytes)
        atomic_write(
            output / "audit_report.json",
            (json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(),
        )
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--annotations",
        type=Path,
        action="append",
        help="Authoritative human export; repeat to add exports to the immutable registry",
    )
    parser.add_argument("--rr-root", type=Path, default=None)
    parser.add_argument(
        "--rr-label-evidence",
        type=Path,
        default=None,
        help="Optional curator-verified, hash-indexed original RR class evidence CSV",
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    try:
        report = build(
            root,
            args.output or root / "data/unified",
            args.annotations or [root / DEFAULT_ANNOTATIONS],
            args.rr_root or root / RR_SELECTION,
            args.rr_label_evidence,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"Manifest build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "sources": report["sources"],
                "annotations": report["annotation_counts"],
                "total_rows": report["total_rows"],
                "unique_hashes": report["unique_content_hashes"],
                "duplicate_hash_groups": len(report["duplicate_hashes"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
