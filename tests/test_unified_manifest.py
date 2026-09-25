"""Critical joins, conflicts and incremental reruns; fixtures never use real annotations."""

import csv
import io
import json
from pathlib import Path

from PIL import Image

from scripts.datasets.build_unified_manifest import (
    COLLECTIONS,
    FIELDS,
    RR_SELECTION,
    audit,
    build,
    digest,
    join_annotations,
    merge_annotations,
    resolve_class,
)


def annotation(content_hash, **overrides):
    return {
        "content_hash": content_hash,
        "blind_id": "SF-0001",
        "public_relevance": "1",
        "harm_urgency": "2",
        "vulnerability": "1",
        "sensitivity_score": "4",
        "sensitivity_level": "high",
        "sensitivity_rationale": "",
        "annotation_confidence": "medium",
        "needs_review": "true",
        "annotation_round": "1",
        "annotated_at": "2026-08-25T12:00:00Z",
        "annotator_id": "sara",
        "dataset_role": "gold_development",
        **overrides,
    }


def image_row(content_hash, path="one.png", **overrides):
    return {
        **dict.fromkeys(FIELDS, ""),
        "content_hash": content_hash,
        "image_id": digest(path.encode()),
        "image_path": path,
        "file_status": "readable",
        "normalized_label": "unknown",
        "label_verification_status": "unverified",
        "label_evidence_json": "[]",
        "annotation_join_status": "unannotated",
        **overrides,
    }


def registry(rows, existing=None):
    return merge_annotations(existing or [], [("source.csv", "source-sha", rows)])


def test_exact_join_preserves_original_strings_and_does_not_score_unannotated():
    original = annotation("a" * 64)
    rows = [image_row("a" * 64), image_row("b" * 64, "two.png")]
    results, _ = join_annotations(rows, registry([original]))
    assert results[0]["status"] == "linked"
    for field in original:
        if field in rows[0]:
            assert rows[0][field] == original[field]
    assert rows[1]["sensitivity_score"] == ""
    assert rows[1]["annotation_join_status"] == "unannotated"


def test_unmatched_ambiguous_and_modified_annotations_are_all_retained():
    first = annotation("a" * 64)
    changed = annotation("a" * 64, sensitivity_rationale="Changed decision")
    annotations = registry([changed, annotation("b" * 64)], registry([first]))
    rows = [image_row("a" * 64)]
    results, _ = join_annotations(rows, annotations)
    assert {r["status"] for r in results} == {"unmatched", "conflicting_annotations"}
    assert len(annotations) == 3
    assert rows[0]["sensitivity_score"] == ""
    ambiguous = [image_row("a" * 64), image_row("a" * 64, "copy.png")]
    results, _ = join_annotations(ambiguous, registry([first]))
    assert results[0]["status"] == "ambiguous_image"
    assert all(row["sensitivity_score"] == "" for row in ambiguous)


def test_invalid_annotation_and_metadata_mismatch_remain_in_report():
    rows = [image_row("a" * 64, component="actual")]
    results, _ = join_annotations(rows, registry([annotation("a" * 64, component="other")]))
    assert results[0]["status"] == "annotation_metadata_conflict"
    results, _ = join_annotations(rows, registry([annotation("a" * 64, sensitivity_score="5")]))
    assert results[0]["status"] == "invalid_annotation"
    assert results[0]["validation_error"]


def test_label_conflicts_never_choose_one_label():
    row = image_row("a" * 64)
    resolve_class(
        row, [{"label": "real", "reference": "one"}, {"label": "fake", "reference": "two"}]
    )
    assert row["normalized_label"] == "unknown"
    assert row["label_verification_status"] == "conflict"
    rows = [
        image_row("a" * 64, normalized_label="real"),
        image_row("a" * 64, "two.png", normalized_label="fake"),
    ]
    report = audit(rows, [], [])
    assert all(r["normalized_label"] == "unknown" for r in rows)
    assert report["issues"][0]["type"] == "hash_label_conflict"


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_pipeline_repeated_execution_is_identical_and_incremental(tmp_path):
    image = io.BytesIO()
    Image.new("RGB", (10, 10), "blue").save(image, "PNG")
    data = image.getvalue()
    content_hash = digest(data)
    source_bytes = {}
    for index, (_, _, manifest) in enumerate(COLLECTIONS):
        path = tmp_path / manifest
        path.parent.mkdir(parents=True)
        path.write_text("")
        if index == 0:
            (path.parent / "one.png").write_bytes(data)
            path.write_text(
                json.dumps(
                    {
                        "relative_image_path": "one.png",
                        "content_hash": content_hash,
                        "normalized_label": "real",
                        "original_label": "real",
                    }
                )
                + "\n"
            )
        source_bytes[path] = path.read_bytes()
    rr = tmp_path / RR_SELECTION / "sara" / "ai"
    rr.mkdir(parents=True)
    Image.new("RGB", (10, 10), "red").save(rr / "real_named.png")
    human = tmp_path / "human.csv"
    write_csv(human, [annotation(content_hash)])
    source_bytes[human] = human.read_bytes()
    output = tmp_path / "derived"
    first = build(tmp_path, output, [human], tmp_path / RR_SELECTION)
    payloads = {
        p.name: p.read_bytes() for p in output.iterdir() if p.suffix in (".json", ".jsonl", ".csv")
    }
    second = build(tmp_path, output, [human], tmp_path / RR_SELECTION)
    assert first == second
    assert payloads == {name: (output / name).read_bytes() for name in payloads}
    assert first["annotation_counts"] == {"linked": 1}
    assert first["sources"]["RRDataset"]["labels"]["unknown"] == 1
    for path, before in source_bytes.items():
        assert path.read_bytes() == before
    additional = tmp_path / "additional.csv"
    write_csv(additional, [annotation("b" * 64)])
    third = build(tmp_path, output, [additional], tmp_path / RR_SELECTION)
    assert third["annotation_counts"] == {"linked": 1, "unmatched": 1}
    saved = [
        json.loads(line) for line in (output / "human_annotations.jsonl").read_text().splitlines()
    ]
    assert len(saved) == 2
    assert any(entry["original"] == annotation(content_hash) for entry in saved)
