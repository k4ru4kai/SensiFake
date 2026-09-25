"""Freeze 300 distinct RRDataset images for blinded manual annotation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.annotation.import_batches import MAX_BATCH_BYTES, validate_image

PEOPLE = ("giovanni", "lorenzo", "sara")
STRATA = tuple((person, label) for person in PEOPLE for label in ("real", "fake"))


def rank(seed: int, purpose: str, content_hash: str) -> str:
    return hashlib.sha256(f"{seed}:{purpose}:{content_hash}".encode()).hexdigest()


def select_rows(rows: list[dict], seed: int = 42, per_stratum: int = 50):
    """Balance original local groups, without treating their folder labels as verified."""
    candidates = defaultdict(list)
    annotated = {
        r["content_hash"] for r in rows if r.get("annotation_join_status") != "unannotated"
    }
    excluded = []
    for row in rows:
        if row["source_dataset"] != "RRDataset":
            continue
        if (
            row["file_status"] != "readable"
            or row["content_hash"] in annotated
            or row["label_verification_status"] in ("conflict", "hash_mismatch")
        ):
            excluded.append(
                {"image_path": row["image_path"], "reason": "integrity_or_annotation_status"}
            )
            continue
        path = Path(row["image_path"])
        person = path.parent.parent.name
        hint = {"real": "real", "ai": "fake"}.get(path.parent.name)
        if person not in PEOPLE or hint is None:
            raise ValueError(f"Unrecognized selection directory: {path}")
        if row["normalized_label"] not in ("unknown", hint):
            excluded.append(
                {"image_path": row["image_path"], "reason": "label_disagrees_with_directory"}
            )
            continue
        candidates[row["content_hash"]].append((person, hint, row))
    pools = defaultdict(list)
    duplicates = []
    for content_hash, entries in sorted(candidates.items()):
        if len({label for _, label, _ in entries}) > 1:
            excluded.append(
                {"content_hash": content_hash, "reason": "conflicting_directory_labels"}
            )
            continue
        entries.sort(key=lambda entry: entry[2]["image_path"])
        person, label, row = entries[0]
        if len(entries) > 1:
            duplicates.append(
                {
                    "content_hash": content_hash,
                    "retained_reference": row["image_path"],
                    "other_references": [e[2]["image_path"] for e in entries[1:]],
                }
            )
        pools[(person, label)].append(row)
    selected = []
    for stratum in STRATA:
        pool = sorted(pools[stratum], key=lambda row: rank(seed, "selection", row["content_hash"]))
        if len(pool) < per_stratum:
            raise ValueError(
                f"Insufficient unique candidates in {stratum}: {len(pool)} < {per_stratum}"
            )
        for row in pool[:per_stratum]:
            selected.append(
                {**row, "selection_group": stratum[0], "selection_label_hint": stratum[1]}
            )
    selected.sort(key=lambda row: rank(seed, "blind-order", row["content_hash"]))
    for number, row in enumerate(selected, 1):
        row["selection_order"] = str(number)
        row["archive_filename"] = (
            f"images/{row['content_hash']}{Path(row['image_path']).suffix.lower()}"
        )
    return selected, {
        "seed": seed,
        "per_stratum": per_stratum,
        "selection_basis": "local directory hints, not verified authenticity or sensitivity",
        "eligible_unique_hashes": sum(map(len, pools.values())),
        "pool_counts": {f"{p}/{label}": len(pools[(p, label)]) for p, label in STRATA},
        "duplicate_references": duplicates,
        "excluded": excluded,
    }


def zip_entry(archive: zipfile.ZipFile, name: str, data: bytes):
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, data)


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create_batch(
    manifest: Path, output: Path, root: Path = REPO_ROOT, seed: int = 42, per_stratum: int = 50
) -> dict:
    with manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    selected, report = select_rows(rows, seed, per_stratum)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".rr-selection-") as temporary:
        staging = Path(temporary)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(selected[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)
        (staging / "selected_images.csv").write_text(buffer.getvalue(), encoding="utf-8")
        metadata, total_bytes = {}, 0
        with zipfile.ZipFile(staging / "annotation_batch.zip", "w") as archive:
            for row in selected:
                relative = Path(row["image_path"])
                path = (root / relative).resolve()
                if relative.is_absolute() or not path.is_relative_to(root.resolve()):
                    raise ValueError(f"Unsafe image path: {relative}")
                data = path.read_bytes()
                if validate_image(data, row["image_path"]) != row["content_hash"]:
                    raise ValueError(f"Image changed since audit: {path}")
                total_bytes += len(data)
                if total_bytes > MAX_BATCH_BYTES:
                    raise ValueError("Batch exceeds the shared annotator's uncompressed ZIP limit")
                name = row["archive_filename"]
                zip_entry(archive, name, data)
                provenance = {
                    "source_dataset": "RRDataset",
                    "original_image_id": row["original_image_id"],
                    "original_filename": path.name,
                    "original_relative_path": row["image_path"],
                    "content_hash": row["content_hash"],
                    "normalized_label": row["normalized_label"],
                    "label_verification_status": row["label_verification_status"],
                    "label_evidence_json": row["label_evidence_json"],
                    "selection_label_hint": row["selection_label_hint"],
                    "selection_group": row["selection_group"],
                    "selection_seed": seed,
                    "selection_role": "candidate_rr_300_manual_annotation",
                }
                if row["normalized_label"] != "unknown":
                    provenance["label_source"] = row["label_evidence_json"]
                metadata[name] = provenance
            metadata_bytes = json.dumps(
                metadata, sort_keys=True, ensure_ascii=False, indent=2
            ).encode()
            if total_bytes + len(metadata_bytes) > MAX_BATCH_BYTES:
                raise ValueError("Batch including metadata exceeds upload limits")
            zip_entry(archive, "metadata.json", metadata_bytes)
        report.update(
            selected_images=len(selected),
            unique_hashes=len({r["content_hash"] for r in selected}),
            selected_strata=dict(
                sorted(
                    Counter(
                        f"{r['selection_group']}/{r['selection_label_hint']}" for r in selected
                    ).items()
                )
            ),
            verified_labels=dict(sorted(Counter(r["normalized_label"] for r in selected).items())),
            input_manifest_sha256=file_hash(manifest),
            selected_manifest_sha256=file_hash(staging / "selected_images.csv"),
            zip_sha256=file_hash(staging / "annotation_batch.zip"),
            zip_bytes=(staging / "annotation_batch.zip").stat().st_size,
        )
        (staging / "selection_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        # Refuse to replace an existing, different selection; preserve batches already being annotated.
        for path in staging.iterdir():
            destination = output / path.name
            if destination.exists() and file_hash(destination) != file_hash(path):
                raise ValueError(
                    f"Existing selection differs: {destination}. Choose a new output directory."
                )
        output.mkdir(parents=True, exist_ok=True)
        for path in staging.iterdir():
            if not (output / path.name).exists():
                os.link(path, output / path.name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=REPO_ROOT / "data/unified/selected_images.csv"
    )
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "data/rrdataset-300-v1")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    print(json.dumps(create_batch(args.manifest, args.output, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()
