"""Presentation-ready Streamlit application for blinded SensiFake annotation."""

from __future__ import annotations

import argparse
import csv
import io
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from sensifake_annotation import (
    Annotation,
    AnnotationError,
    ManifestError,
    OverwriteConfirmationRequired,
    annotation_from_values,
    calculate_score,
    canonical_openfake_manifest,
    deterministic_order,
    load_annotations,
    load_manifest,
    openfake_development_annotations,
    prepare_reannotation_sample,
    resume_index,
    save_annotation,
    sensitivity_level,
)
from sensifake_annotation.human_train_assignment import (
    human_train_annotation_path,
    list_annotators,
    load_human_train_task,
)

DEFAULT_MANIFEST = canonical_openfake_manifest()
DEFAULT_ANNOTATIONS = openfake_development_annotations()
SEED = 42
CALIBRATION_SIZE = 30
DEMO_SIZE = 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SensiFake manual annotation sessions")
    parser.add_argument(
        "--mode", choices=("annotation", "presentation", "human-train"), default="annotation"
    )
    parser.add_argument("--annotator", help="Assigned human-training annotator ID")
    parser.add_argument(
        "--list-annotators",
        action="store_true",
        help="List available human-training task IDs without starting Streamlit",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--frozen-annotations", type=Path)
    parser.add_argument("--calibration", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--annotation-round", type=int, default=1)
    args = parser.parse_args(argv)
    if args.mode == "human-train" and not args.list_annotators:
        if not args.annotator:
            parser.error("--mode human-train requires --annotator ANNOTATOR_ID")
        if (
            args.manifest != DEFAULT_MANIFEST
            or args.annotations != DEFAULT_ANNOTATIONS
            or args.frozen_annotations
            or args.calibration
            or args.demo
            or args.annotation_round != 1
        ):
            parser.error(
                "human-train uses only the assigned task and personal output; "
                "manifest/output overrides, demo, calibration and other rounds are disabled"
            )
        try:
            args.annotations = human_train_annotation_path(args.annotator)
        except AnnotationError as exc:
            parser.error(str(exc))
    return args


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def reannotation_csv(samples: list[Any]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=("blind_id", "annotation_round"))
    writer.writeheader()
    writer.writerows({"blind_id": sample.blind_id, "annotation_round": 2} for sample in samples)
    return output.getvalue().encode("utf-8")


def annotation_frame(annotations: list[Annotation], annotation_round: int) -> pd.DataFrame:
    rows = [
        asdict(annotation)
        for annotation in annotations
        if annotation.annotation_round == annotation_round
    ]
    return pd.DataFrame(rows)


def style_page() -> None:
    st.set_page_config(
        page_title="SensiFake Sensitivity Lab",
        page_icon="◉",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_protocol() -> None:
    st.subheader("Sensitivity annotation protocol")
    st.info(
        "Score only what is observable in the image. Do not infer authenticity, provenance, "
        "intent, or hidden context. The three dimensions sum to a reproducible 0–5 score.",
        icon=":material/visibility:",
    )
    columns = st.columns(3)
    with columns[0]:
        st.markdown("#### Public relevance · 0–2")
        st.markdown(
            "**0** — no evident public-interest relevance  \n"
            "**1** — limited or contextual public relevance  \n"
            "**2** — clear, broad public-interest relevance"
        )
    with columns[1]:
        st.markdown("#### Harm urgency · 0–2")
        st.markdown(
            "**0** — no observable urgent harm  \n"
            "**1** — plausible or moderate harm concern  \n"
            "**2** — severe or time-critical harm concern"
        )
    with columns[2]:
        st.markdown("#### Vulnerability · 0–1")
        st.markdown(
            "**0** — no observable vulnerability cue  \n"
            "**1** — a person or context visibly warrants added protection"
        )
    st.markdown("#### Formula and level")
    st.code(
        "sensitivity_score = public_relevance + harm_urgency + vulnerability\n"
        "0–1 → low    2–3 → medium    4–5 → high",
        language=None,
    )
    st.caption(
        "Rationales are optional. Use a short observable rationale when a case is ambiguous, "
        "low-confidence, or needs review. Low-confidence cases enter review by default; the "
        "annotator may edit that flag deliberately."
    )


def demo_annotations() -> list[Annotation]:
    return list(st.session_state.setdefault("demo_annotations", []))


def persist_demo(annotation: Annotation, confirm_overwrite: bool) -> str:
    annotations = demo_annotations()
    matching = next(
        (index for index, existing in enumerate(annotations) if existing.key == annotation.key),
        None,
    )
    if matching is None:
        annotations.append(annotation)
        action = "created"
    else:
        existing_values = asdict(annotations[matching])
        new_values = asdict(annotation)
        existing_values.pop("annotated_at")
        new_values.pop("annotated_at")
        if existing_values == new_values:
            return "unchanged"
        if not confirm_overwrite:
            raise OverwriteConfirmationRequired(
                "confirm overwrite before replacing this demo annotation"
            )
        annotations[matching] = annotation
        action = "updated"
    st.session_state["demo_annotations"] = annotations
    return action


def render_annotator(
    *,
    samples: list[Any],
    annotations: list[Annotation],
    annotation_path: Path,
    annotation_round: int,
    demo: bool,
    review_only: bool,
    annotator_id: str | None = None,
) -> None:
    round_annotations = {
        annotation.content_hash: annotation
        for annotation in annotations
        if annotation.annotation_round == annotation_round
    }
    queue = samples
    if review_only:
        queue = [
            sample
            for sample in samples
            if sample.content_hash in round_annotations
            and round_annotations[sample.content_hash].needs_review
        ]
    if not queue:
        st.info("No images currently match the review filter.")
        return

    state_key = (
        f"{annotation_path}_current_sample_r{annotation_round}_{len(samples)}_{int(review_only)}"
    )
    valid_hashes = {sample.content_hash for sample in queue}
    if st.session_state.get(state_key) not in valid_hashes:
        initial = resume_index(queue, annotations, annotation_round=annotation_round)
        st.session_state[state_key] = queue[initial].content_hash
    index = next(
        position
        for position, sample in enumerate(queue)
        if sample.content_hash == st.session_state[state_key]
    )
    sample = queue[index]
    existing = round_annotations.get(sample.content_hash)

    completed = sum(sample.content_hash in round_annotations for sample in samples)
    progress_columns = st.columns((2, 1, 1))
    progress_columns[0].progress(
        completed / len(samples),
        text=f"{completed} of {len(samples)} annotated",
    )
    progress_columns[1].metric("Queue position", f"{index + 1} / {len(queue)}")
    progress_columns[2].metric("Blind ID", sample.blind_id)

    image_column, form_column = st.columns((1.15, 1), gap="large")
    with image_column:
        try:
            image_bytes = sample.image_path.read_bytes()
        except OSError:
            st.error("This blinded image could not be read. Stop and contact the dataset curator.")
            return
        st.image(image_bytes, width="stretch")
        st.caption("Blinded sample — provenance and authenticity are withheld.")

    prefix = f"r{annotation_round}_{sample.blind_id}"
    defaults = existing or annotation_from_values(
        content_hash=sample.content_hash,
        blind_id=sample.blind_id,
        public_relevance=0,
        harm_urgency=0,
        vulnerability=0,
        sensitivity_rationale="",
        annotation_confidence="medium",
        needs_review=False,
        annotation_round=annotation_round,
    )
    confidence_key = f"confidence_{prefix}"
    review_key = f"review_{prefix}"
    if confidence_key not in st.session_state:
        st.session_state[confidence_key] = defaults.annotation_confidence
    if review_key not in st.session_state:
        st.session_state[review_key] = defaults.needs_review

    def default_low_confidence_review() -> None:
        if st.session_state[confidence_key] == "low":
            st.session_state[review_key] = True

    with form_column:
        if existing:
            st.info("Saved annotation loaded. Changes require explicit overwrite confirmation.")
        public_relevance = st.radio(
            "Public relevance",
            options=(0, 1, 2),
            index=defaults.public_relevance,
            horizontal=True,
            key=f"public_{prefix}",
        )
        harm_urgency = st.radio(
            "Harm urgency",
            options=(0, 1, 2),
            index=defaults.harm_urgency,
            horizontal=True,
            key=f"harm_{prefix}",
        )
        vulnerability = st.radio(
            "Vulnerability",
            options=(0, 1),
            index=defaults.vulnerability,
            horizontal=True,
            key=f"vulnerability_{prefix}",
        )
        score = calculate_score(public_relevance, harm_urgency, vulnerability)
        score_columns = st.columns(2)
        score_columns[0].metric("Sensitivity score", f"{score} / 5")
        score_columns[1].metric("Sensitivity level", sensitivity_level(score).title())
        rationale = st.text_area(
            "Optional observable rationale",
            value="" if existing is None else existing.sensitivity_rationale,
            max_chars=280,
            placeholder="Optionally describe visible cues (up to 280 characters).",
            key=f"rationale_{prefix}",
        )
        confidence = st.selectbox(
            "Annotation confidence",
            options=("high", "medium", "low"),
            key=confidence_key,
            on_change=default_low_confidence_review,
        )
        needs_review = st.checkbox(
            "Needs review",
            key=review_key,
            help="Automatically selected when confidence changes to low; manually editable.",
        )
        confirm = False
        if existing:
            confirm = st.checkbox(
                "I explicitly confirm overwriting this saved annotation",
                key=f"confirm_{prefix}",
            )

    navigation = st.columns((1, 1, 1))
    previous = navigation[0].button(
        "← Previous",
        disabled=index == 0,
        width="stretch",
    )
    save = navigation[1].button("Save", type="primary", width="stretch")
    next_image = navigation[2].button(
        "Next →",
        disabled=index == len(queue) - 1,
        width="stretch",
    )

    if previous or save or next_image:
        try:
            # Recheck the fixed destination at every write, including symlink protection.
            if annotator_id is not None and annotation_path != human_train_annotation_path(
                annotator_id
            ):
                raise AnnotationError("Cannot write another annotator's CSV.")
            annotation = annotation_from_values(
                content_hash=sample.content_hash,
                blind_id=sample.blind_id,
                public_relevance=public_relevance,
                harm_urgency=harm_urgency,
                vulnerability=vulnerability,
                sensitivity_rationale=rationale,
                annotation_confidence=confidence,
                needs_review=needs_review,
                annotation_round=annotation_round,
            )
            action = (
                persist_demo(annotation, confirm)
                if demo
                else save_annotation(
                    annotation_path,
                    annotation,
                    confirm_overwrite=confirm,
                )
            )
        except AnnotationError as exc:
            st.error(str(exc))
            return
        st.toast(f"Annotation {action}; autosave complete.")
        if previous:
            st.session_state[state_key] = queue[index - 1].content_hash
        elif next_image:
            st.session_state[state_key] = queue[index + 1].content_hash
        st.rerun()


def render_quality_control(
    samples: list[Any],
    annotations: list[Annotation],
    annotation_round: int,
) -> None:
    frame = annotation_frame(annotations, annotation_round)
    annotated_hashes = set(frame["content_hash"]) if not frame.empty else set()
    metrics = st.columns(4)
    metrics[0].metric("Annotated", len(annotated_hashes))
    metrics[1].metric("Missing", len(samples) - len(annotated_hashes))
    metrics[2].metric(
        "Low confidence",
        0 if frame.empty else int((frame["annotation_confidence"] == "low").sum()),
    )
    metrics[3].metric(
        "Needs review",
        0 if frame.empty else int(frame["needs_review"].sum()),
    )

    st.markdown("#### Review queue")
    if frame.empty:
        st.info("No annotations have been saved for this round.")
    else:
        safe_columns = [
            "blind_id",
            "sensitivity_score",
            "sensitivity_level",
            "annotation_confidence",
            "needs_review",
            "annotated_at",
        ]
        st.dataframe(
            frame.loc[frame["needs_review"], safe_columns],
            hide_index=True,
            width="stretch",
        )

    st.markdown("#### Blind 20% re-annotation preparation")
    reannotation = prepare_reannotation_sample(samples, fraction=0.20, seed=SEED)
    st.write(
        f"A deterministic seed-{SEED} sample contains **{len(reannotation)}** of "
        f"**{len(samples)}** images. Its export contains only blind IDs and round number."
    )
    st.download_button(
        "Export blind re-annotation sample",
        data=reannotation_csv(reannotation),
        file_name="sensitivity_reannotation_round2_sample.csv",
        mime="text/csv",
    )


def render_safe_dashboard(annotations: list[Annotation], annotation_round: int) -> None:
    st.info(
        "First-round blinding is active. Authenticity and source composition are withheld. "
        "Use presentation mode only after annotations are completed or frozen."
    )
    frame = annotation_frame(annotations, annotation_round)
    if frame.empty:
        st.write("No annotation summaries are available yet.")
        return
    sensitivity = (
        frame.groupby("sensitivity_level", as_index=False).size().rename(columns={"size": "count"})
    )
    confidence = (
        frame.groupby("annotation_confidence", as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    columns = st.columns(2)
    columns[0].bar_chart(sensitivity, x="sensitivity_level", y="count")
    columns[1].bar_chart(confidence, x="annotation_confidence", y="count")
    st.download_button(
        "Export blinded dashboard summaries",
        data=csv_bytes(
            pd.concat(
                {
                    "sensitivity": sensitivity.set_index("sensitivity_level"),
                    "confidence": confidence.set_index("annotation_confidence"),
                }
            ).reset_index(names=["table", "category"])
        ),
        file_name="blinded_annotation_summary.csv",
        mime="text/csv",
    )


def presentation_annotations(
    *,
    live_path: Path,
    frozen_path: Path | None,
    samples: list[Any],
    annotation_round: int,
) -> tuple[list[Annotation], str]:
    if frozen_path is not None:
        annotations = load_annotations(frozen_path)
        return annotations, f"Frozen snapshot: {frozen_path.resolve()}"
    annotations = load_annotations(live_path)
    completed = {
        annotation.content_hash
        for annotation in annotations
        if annotation.annotation_round == annotation_round
    }
    expected = {sample.content_hash for sample in samples}
    if completed != expected:
        raise AnnotationError(
            "presentation mode requires a complete annotation round or --frozen-annotations"
        )
    return annotations, f"Completed round: {live_path.resolve()}"


def render_presentation_dashboard(
    *,
    dataset: Any,
    samples: list[Any],
    annotations: list[Annotation],
    annotation_round: int,
) -> None:
    rows: list[dict[str, Any]] = []
    sample_hashes = {sample.content_hash for sample in samples}
    for annotation in annotations:
        if annotation.annotation_round != annotation_round:
            continue
        if annotation.content_hash not in sample_hashes:
            raise AnnotationError("report annotations contain a sample outside the manifest")
        metadata = dataset.report_metadata[annotation.content_hash]
        rows.append(
            {
                **asdict(annotation),
                "authenticity": metadata.authenticity,
                "source_dataset": metadata.source_dataset,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("The selected report snapshot contains no annotations for this round.")
        return

    sensitivity = (
        frame.groupby("sensitivity_level", as_index=False).size().rename(columns={"size": "count"})
    )
    cells = pd.crosstab(frame["authenticity"], frame["sensitivity_level"])
    sources = (
        frame.groupby("source_dataset", as_index=False).size().rename(columns={"size": "count"})
    )
    confidence = (
        frame.groupby("annotation_confidence", as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )

    metrics = st.columns(4)
    metrics[0].metric("Reported images", len(frame))
    metrics[1].metric("Mean sensitivity", f"{frame['sensitivity_score'].mean():.2f}")
    metrics[2].metric("High sensitivity", int((frame["sensitivity_level"] == "high").sum()))
    metrics[3].metric("Needs review", int(frame["needs_review"].sum()))

    charts = st.columns(2)
    with charts[0]:
        st.markdown("#### Sensitivity distribution")
        st.bar_chart(sensitivity, x="sensitivity_level", y="count")
        st.dataframe(sensitivity, hide_index=True, width="stretch")
    with charts[1]:
        st.markdown("#### Annotation confidence")
        st.bar_chart(confidence, x="annotation_confidence", y="count")
        st.dataframe(confidence, hide_index=True, width="stretch")

    st.markdown("#### Authenticity × sensitivity cells")
    st.dataframe(cells, width="stretch")
    st.markdown("#### Source composition")
    st.bar_chart(sources, x="source_dataset", y="count")
    st.dataframe(sources, hide_index=True, width="stretch")

    export = pd.concat(
        {
            "sensitivity_distribution": sensitivity.set_index("sensitivity_level"),
            "annotation_confidence": confidence.set_index("annotation_confidence"),
            "source_composition": sources.set_index("source_dataset"),
        }
    ).reset_index(names=["table", "category"])
    st.download_button(
        "Export presentation summary tables",
        data=csv_bytes(export),
        file_name="sensifake_presentation_summary.csv",
        mime="text/csv",
        type="primary",
    )
    st.download_button(
        "Export authenticity × sensitivity cells",
        data=cells.to_csv().encode("utf-8"),
        file_name="sensifake_authenticity_sensitivity_cells.csv",
        mime="text/csv",
    )


def main() -> None:
    args = parse_args()
    if args.list_annotators:
        available = list_annotators()
        print(
            "\n".join(available)
            if available
            else "No annotator task files available. "
            "Ask the maintainer to generate human-train-v0 tasks."
        )
        return
    style_page()
    st.title("SensiFake · Sensitivity Annotation Lab")
    st.markdown(
        "A reproducible, blinded manual-annotation workspace for studying how content "
        "sensitivity intersects with deepfake detection."
    )

    if args.annotation_round < 1:
        st.error("--annotation-round must be a positive integer")
        st.stop()
    if args.mode == "presentation" and (args.calibration or args.demo):
        st.error("--calibration and --demo are available only in annotation mode")
        st.stop()

    try:
        if args.mode == "human-train":
            ordered = load_human_train_task(args.annotator)
        else:
            dataset = load_manifest(args.manifest)
            ordered = deterministic_order(dataset.samples, seed=SEED)
    except (ManifestError, AnnotationError, OSError) as exc:
        st.error(str(exc))
        st.stop()

    scope = ordered
    mode_label = (
        f"Human training · {args.annotator}" if args.mode == "human-train" else "Full annotation"
    )
    if args.calibration:
        scope = ordered[:CALIBRATION_SIZE]
        mode_label = "30-image calibration"
    if args.demo:
        scope = ordered[:DEMO_SIZE]
        mode_label = "Read-only-output demo"

    with st.sidebar:
        st.badge(mode_label, icon=":material/visibility:", color="blue")
        if args.mode != "human-train":
            st.write(f"Seed: **{SEED}**")
        st.write(f"Annotation round: **{args.annotation_round}**")
        st.write(f"Manifest samples: **{len(ordered)}**")
        if args.demo:
            st.success("Demo annotations stay in session memory and never touch the real CSV.")
        review_only = False
        if args.mode in ("annotation", "human-train"):
            review_only = st.toggle("Review queue only", value=False)
            if not args.demo:
                st.caption(f"Autosave target: {args.annotations}")

    try:
        if args.mode == "presentation":
            annotations, report_source = presentation_annotations(
                live_path=args.annotations,
                frozen_path=args.frozen_annotations,
                samples=ordered,
                annotation_round=args.annotation_round,
            )
            st.caption(report_source)
        else:
            annotations = demo_annotations() if args.demo else load_annotations(args.annotations)
            if args.mode == "human-train":
                expected = {sample.content_hash: sample.blind_id for sample in ordered}
                if any(
                    a.annotation_round != 1 or expected.get(a.content_hash) != a.blind_id
                    for a in annotations
                ):
                    raise AnnotationError("Personal CSV contains annotations outside your task.")
    except AnnotationError as exc:
        st.error(str(exc))
        st.stop()

    protocol_tab, annotate_tab, quality_tab, dashboard_tab = st.tabs(
        ("Protocol", "Annotate", "Quality Control", "Dataset Dashboard")
    )
    with protocol_tab:
        render_protocol()
    with annotate_tab:
        if args.mode == "presentation":
            st.info("Presentation mode is read-only; annotation controls are disabled.")
        else:
            render_annotator(
                samples=scope,
                annotations=annotations,
                annotation_path=args.annotations,
                annotation_round=args.annotation_round,
                demo=args.demo,
                review_only=review_only,
                annotator_id=args.annotator if args.mode == "human-train" else None,
            )
    with quality_tab:
        render_quality_control(scope, annotations, args.annotation_round)
    with dashboard_tab:
        if args.mode == "presentation":
            try:
                render_presentation_dashboard(
                    dataset=dataset,
                    samples=ordered,
                    annotations=annotations,
                    annotation_round=args.annotation_round,
                )
            except AnnotationError as exc:
                st.error(str(exc))
        else:
            render_safe_dashboard(annotations, args.annotation_round)


if __name__ == "__main__":
    main()
