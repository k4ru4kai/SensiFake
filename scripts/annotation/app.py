"""Shared manual annotation entry point. The legacy app remains available separately."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from scripts.annotation.import_batches import SNAPSHOT, prepare_legacy, prepare_zip
from scripts.annotation.annotation_schema import AnnotationError, calculate_score, sensitivity_level
from scripts.annotation.paths import REPOSITORY_ROOT
from scripts.annotation.annotation_database import RUBRIC_FIELDS, SharedStore, identity


def rubric_inputs(defaults: dict, key: str) -> dict:
    columns = st.columns(3)
    public = columns[0].radio(
        "Public relevance · 0–2",
        (0, 1, 2),
        index=defaults.get("public_relevance", 0),
        key=f"{key}_public",
    )
    harm = columns[1].radio(
        "Harm urgency · 0–2", (0, 1, 2), index=defaults.get("harm_urgency", 0), key=f"{key}_harm"
    )
    vulnerability = columns[2].radio(
        "Vulnerability · 0–1",
        (0, 1),
        index=defaults.get("vulnerability", 0),
        key=f"{key}_vulnerability",
    )
    score = calculate_score(public, harm, vulnerability)
    st.write(f"Sensitivity: **{score}/5 · {sensitivity_level(score)}**")
    rationale = st.text_area(
        "Optional observable rationale",
        max_chars=280,
        value=defaults.get("sensitivity_rationale", ""),
        key=f"{key}_rationale",
    )
    confidence_key, review_key = f"{key}_confidence", f"{key}_needs_review"
    if review_key not in st.session_state:
        st.session_state[review_key] = defaults.get("needs_review", False)

    def flag_low_confidence():
        if st.session_state[confidence_key] == "low":
            st.session_state[review_key] = True

    confidence = st.selectbox(
        "Annotation confidence",
        ("high", "medium", "low"),
        index=("high", "medium", "low").index(defaults.get("annotation_confidence", "medium")),
        key=confidence_key,
        on_change=flag_low_confidence,
    )
    needs_review = st.checkbox(
        "Needs review",
        key=review_key,
        help="Selected when confidence changes to low; you may edit the flag.",
    )
    return {
        "public_relevance": public,
        "harm_urgency": harm,
        "vulnerability": vulnerability,
        "sensitivity_rationale": rationale,
        "annotation_confidence": confidence,
        "needs_review": needs_review,
    }


def work_queue(store: SharedStore, name: str, batch_id: str | None, kind: str):
    person_key, _ = identity(name)
    state_key = f"lease_{person_key}_{kind}"
    include_reviewed = kind == "review" and st.checkbox("Include previously reviewed images")
    if state_key not in st.session_state:
        if st.button("Resume or reserve an image", type="primary"):
            lease = store.reserve(name, batch_id, kind=kind, include_reviewed=include_reviewed)
            if lease:
                st.session_state[state_key] = lease
                st.rerun()
            else:
                st.info("No eligible images are available. Others may have active reservations.")
        return
    lease = st.session_state[state_key]
    content_hash, token = lease["content_hash"], lease["token"]
    st.caption(f"Image SF-{content_hash[:20]}")
    st.caption(
        "The current reservation stays selected until you save or release it, even if you change the batch filter."
    )
    if st.button("Release image"):
        store.release(token, name)
        del st.session_state[state_key]
        st.rerun()
    st.image(store.image(content_hash), width="stretch")
    decision = store.decision(content_hash) if kind == "review" else None
    defaults = store.draft(lease) or (decision["current"] if decision else {})
    action, reason = "confirm", ""
    if decision:
        st.write(f"Original annotator: **{decision['annotator']}**")
        st.json({key: decision["original"][key] for key in RUBRIC_FIELDS})
        if decision["reviews"]:
            st.write("Latest reviewed annotation")
            st.json({key: decision["current"][key] for key in RUBRIC_FIELDS})
        action = st.radio(
            "Review decision",
            ("confirm", "correct"),
            format_func=lambda value: (
                "Confirm current annotation" if value == "confirm" else "Correct annotation"
            ),
            key=f"{token}_action",
        )
    if not decision or action == "correct":
        values = rubric_inputs(defaults, token)
    else:
        values = decision["current"]
    if action == "correct":
        reason = st.text_area(
            "Reason for correction (required)",
            value=defaults.get("review_reason", ""),
            key=f"{token}_reason",
        )
    # Widget changes trigger reruns; persist drafts and renew only a still-valid lease.
    try:
        store.save_draft(token, name, {**values, "review_reason": reason})
    except AnnotationError as exc:
        st.warning(str(exc))
        if st.button("Return to queue"):
            del st.session_state[state_key]
            st.rerun()
        return
    st.caption(
        f"Draft saved when controls change. Reservations expire after {store.reservation_seconds // 60} minutes without interaction. Text is saved after leaving the field."
    )
    if st.button(
        "Save completed annotation" if kind == "annotation" else "Save review", type="primary"
    ):
        store.complete(token, name, values, action=action, reason=reason)
        del st.session_state[state_key]
        st.success("Saved durably. Reserve the next image when ready.")
        st.rerun()


def imports(store: SharedStore):
    st.write(
        "Import a ZIP containing images and, optionally, a root metadata.json mapping filenames to provenance. All images must be readable. Existing hashes share their annotation across batches."
    )
    name = st.text_input("Batch name")
    role = st.selectbox("Dataset role", ("custom", "rrdataset", "gold_development", "human_train"))
    upload = st.file_uploader("Image ZIP", type="zip")
    if st.button("Import batch", disabled=upload is None):
        with st.spinner("Validating images and saving batch…"):
            result = store.import_batches(prepare_zip(upload, name, role))
        st.success(
            f"Imported {result['entries']} filenames: {result['new_images']} new images, {result['duplicate_images']} duplicate images."
        )
        if result["duplicates"]:
            st.dataframe(result["duplicates"], hide_index=True)
    with st.expander("Import existing completed annotations"):
        st.write(
            "Imports only the validated 401-row snapshot into separate gold_development and human_train batches. Existing source files are preserved. Imported annotations await independent review."
        )
        st.caption(SNAPSHOT)
        if st.button("Import validated 401-row snapshot"):
            with st.spinner("Checking the snapshot and copying verified images…"):
                store.import_batches(prepare_legacy(REPOSITORY_ROOT))
            st.success("Imported 401 completed annotations.")
    st.write("Batch availability")
    for batch in store.batches():
        opened = st.checkbox(
            batch["name"], value=bool(batch["is_open"]), key=f"open_{batch['batch_id']}"
        )
        if opened != bool(batch["is_open"]):
            store.set_open(batch["batch_id"], opened)
    st.caption(
        "Unchecked batches leave the queues. Existing reservations may finish; exports remain available."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--storage",
        type=Path,
        default=os.environ.get("SENSIFAKE_STORAGE")
        or REPOSITORY_ROOT / "annotations" / "shared" / "sensifake.sqlite3",
    )
    parser.add_argument("--reservation-minutes", type=int, default=15)
    args = parser.parse_args()
    st.set_page_config(page_title="SensiFake shared annotator", layout="wide")
    st.title("SensiFake · Manual sensitivity annotation")
    if not args.storage.is_absolute() or args.reservation_minutes < 1:
        st.error(
            "Storage must be an absolute SQLite file path. Reservation minutes must be positive."
        )
        return
    store = SharedStore(args.storage, args.reservation_minutes * 60)
    name = st.text_input(
        "Your name",
        help="Use the same name each time to resume drafts. Each person must use their own name.",
        key="annotator_name",
    )
    page = st.sidebar.radio(
        "Workspace", ("Annotate", "Review", "Progress and exports", "Import batches")
    )
    batches = store.batches()
    options = {
        b["batch_id"]: b["name"] for b in batches if b["is_open"] or page == "Progress and exports"
    }
    batch_id = st.sidebar.selectbox(
        "Batch",
        [None, *options],
        format_func=lambda value: options[value] if value else "All batches",
    )
    try:
        if page in ("Annotate", "Review"):
            if not name.strip():
                st.info("Enter your name to start or resume.")
                return
            with st.expander("Scoring rubric"):
                st.write(
                    "Judge only visible content. Do not infer authenticity, origin, or hidden context."
                )
                st.write(
                    "Public relevance: 0 no evident public interest; 1 limited/contextual; 2 clear, broad public interest."
                )
                st.write(
                    "Harm urgency: 0 no observable urgent harm; 1 plausible/moderate concern; 2 severe or time-critical concern."
                )
                st.write(
                    "Vulnerability: 0 no observable cue; 1 a person or context visibly warrants added protection."
                )
                st.write(
                    "Sum: 0–1 low, 2–3 medium, 4–5 high. Rationale is optional; low confidence flags review by default."
                )
            work_queue(store, name, batch_id, "annotation" if page == "Annotate" else "review")
        elif page == "Import batches":
            imports(store)
        else:
            st.dataframe(store.progress(), hide_index=True)
            st.caption(
                "Counts use unique image hashes. One image in multiple batches counts once in the overall total. Confirmed includes corrections approved by another person."
            )
            for kind, label in (
                ("current", "Current annotations"),
                ("confirmed", "Confirmed annotations"),
                ("history", "Review history"),
            ):
                st.download_button(
                    label,
                    store.export_csv(kind, batch_id),
                    file_name=f"sensifake_{kind}.csv",
                    mime="text/csv",
                )
            st.caption(
                "Exports include saved work immediately, even for incomplete or closed batches. Each filename membership has a row; repeated hashes across batches are intentional. Provenance appears only in exports and import administration."
            )
    except (AnnotationError, OSError, ValueError) as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
