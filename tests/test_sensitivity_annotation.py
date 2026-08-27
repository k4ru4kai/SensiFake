"""Focused tests for blinded sensitivity scoring and durable autosave."""

import csv
from pathlib import Path

import pytest

from sensifake_annotation import (
    ANNOTATION_FIELDS,
    AnnotationError,
    BlindedSample,
    DuplicateAnnotationError,
    OverwriteConfirmationRequired,
    annotation_from_values,
    calculate_score,
    load_annotations,
    resume_index,
    save_annotation,
    sensitivity_level,
)


def make_annotation(content_hash: str, blind_id: str, **overrides: object):
    values = {
        "content_hash": content_hash,
        "blind_id": blind_id,
        "public_relevance": 1,
        "harm_urgency": 1,
        "vulnerability": 0,
        "sensitivity_rationale": "Visible public-context cue.",
        "annotation_confidence": "high",
        "needs_review": False,
        "annotation_round": 1,
        "annotated_at": "2026-08-25T12:00:00Z",
    }
    values.update(overrides)
    return annotation_from_values(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("dimensions", "score", "level"),
    [
        ((0, 0, 0), 0, "low"),
        ((1, 0, 0), 1, "low"),
        ((1, 1, 0), 2, "medium"),
        ((1, 1, 1), 3, "medium"),
        ((2, 1, 1), 4, "high"),
        ((2, 2, 1), 5, "high"),
    ],
)
def test_score_and_level_mapping(
    dimensions: tuple[int, int, int],
    score: int,
    level: str,
) -> None:
    assert calculate_score(*dimensions) == score
    assert sensitivity_level(score) == level


@pytest.mark.parametrize("dimensions", [(-1, 0, 0), (3, 0, 0), (0, 3, 0), (0, 0, 2)])
def test_score_ranges_are_enforced(dimensions: tuple[int, int, int]) -> None:
    with pytest.raises(AnnotationError):
        calculate_score(*dimensions)


def test_empty_rationale_is_valid_and_preserved_in_csv(tmp_path: Path) -> None:
    output = tmp_path / "sensitivity_annotations.csv"
    annotation = make_annotation(
        "hash-a",
        "SF-0001",
        sensitivity_rationale="",
    )

    assert save_annotation(output, annotation) == "created"
    assert load_annotations(output)[0].sensitivity_rationale == ""
    with output.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert "sensitivity_rationale" in row
    assert row["sensitivity_rationale"] == ""


def test_optional_rationale_has_only_a_maximum_length() -> None:
    assert (
        make_annotation(
            "hash-a",
            "SF-0001",
            sensitivity_rationale="x",
        ).sensitivity_rationale
        == "x"
    )

    with pytest.raises(AnnotationError, match="at most 280"):
        make_annotation(
            "hash-a",
            "SF-0001",
            sensitivity_rationale="x" * 281,
        )


def test_autosave_and_resume_preserve_one_row_per_sample(tmp_path: Path) -> None:
    output = tmp_path / "annotations" / "sensitivity_annotations.csv"
    samples = [
        BlindedSample("hash-a", tmp_path / "a.jpg", "SF-0001"),
        BlindedSample("hash-b", tmp_path / "b.jpg", "SF-0002"),
    ]

    assert save_annotation(output, make_annotation("hash-a", "SF-0001")) == "created"

    loaded = load_annotations(output)
    assert len(loaded) == 1
    assert loaded[0].sensitivity_score == 2
    assert loaded[0].sensitivity_level == "medium"
    assert resume_index(samples, loaded) == 1

    assert save_annotation(output, make_annotation("hash-b", "SF-0002")) == "created"
    assert len(load_annotations(output)) == 2
    assert resume_index(samples, load_annotations(output)) == 0


def test_nonempty_annotation_requires_explicit_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "sensitivity_annotations.csv"
    original = make_annotation("hash-a", "SF-0001")
    changed = make_annotation(
        "hash-a",
        "SF-0001",
        public_relevance=2,
        sensitivity_rationale="Clear broad public relevance.",
        annotated_at="2026-08-25T12:01:00Z",
    )
    save_annotation(output, original)

    with pytest.raises(OverwriteConfirmationRequired):
        save_annotation(output, changed)

    assert load_annotations(output) == [original]
    assert save_annotation(output, changed, confirm_overwrite=True) == "updated"
    assert load_annotations(output) == [changed]


def test_duplicate_rows_are_rejected_on_resume(tmp_path: Path) -> None:
    output = tmp_path / "sensitivity_annotations.csv"
    row = {
        key: ("true" if value is True else "false" if value is False else value)
        for key, value in make_annotation("hash-a", "SF-0001").__dict__.items()
    }
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerow(row)
        writer.writerow(row)

    with pytest.raises(DuplicateAnnotationError):
        load_annotations(output)
