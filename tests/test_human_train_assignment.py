"""Human training selection, immutable publication and personal annotation workflow."""

import csv
import io
import subprocess
import sys
from collections import Counter
from functools import partial
from pathlib import Path

import pytest
from PIL import Image

from scripts.build_human_train_assignment import main as build_main
from sensifake_annotation import human_train_assignment as ht
from sensifake_annotation.assignment import ASSIGNMENT_FIELDS
from sensifake_annotation.core import AnnotationError, load_annotations

IDS = ["alice", "bob", "carol"]
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path):
    rows = []
    dev_remaining = 101
    for source_index, dataset in enumerate(("ComplexDataLab/OpenFake", "saberzl/SID_Set")):
        for index in range(1500):
            label = "real" if index % 2 == 0 else "fake"
            role = "gold_test" if index < 100 else "unassigned"
            if source_index == 0 and role == "unassigned" and dev_remaining:
                role = "gold_development"
                dev_remaining -= 1
            content_hash = f"{source_index * 1500 + index:064x}"
            rows.append(
                {
                    "content_hash": content_hash,
                    "source_dataset": dataset,
                    "component": (
                        "sid_set_candidate_1500"
                        if source_index
                        else "openfake_pilot_600"
                        if index < 600
                        else "openfake_additional_900"
                    ),
                    "normalized_label": label,
                    "relative_image_path": f"images/{content_hash}.png",
                    "role": role,
                    "split_seed": "42",
                }
            )
    path = tmp_path / "gold_silver.csv"
    path.write_bytes(ht.serialize_csv(rows, ASSIGNMENT_FIELDS))
    return path


@pytest.fixture
def planned(source):
    return ht.build_human_train_assignment(IDS, input_path=source)


def test_balance_exclusion_and_original_bytes(source, planned, tmp_path):
    before = source.read_bytes()
    original = list(csv.DictReader(io.StringIO(before.decode())))
    hashes = {r["content_hash"] for r in planned}
    assert len(planned) == len(hashes) == 300
    assert hashes <= {r["content_hash"] for r in original if r["role"] == "unassigned"}
    assert hashes.isdisjoint(r["content_hash"] for r in original if r["role"] != "unassigned")
    assert Counter((r["source_dataset"], r["normalized_label"]) for r in planned) == dict.fromkeys(
        ht.STRATA, 75
    )
    assert Counter(r["annotator_id"] for r in planned) == dict.fromkeys(IDS, 100)
    for annotator in IDS:
        rows = [r for r in planned if r["annotator_id"] == annotator]
        assert Counter((r["source_dataset"], r["normalized_label"]) for r in rows) == dict.fromkeys(
            ht.STRATA, 25
        )
        assert [int(r["annotation_order"]) for r in rows] == list(range(1, 101))
        assert len({(r["source_dataset"], r["normalized_label"]) for r in rows[:25]}) > 1
    assert all(
        r["role"] == "unassigned"
        and r["assignment_role"] == "human_train"
        and r["human_train_seed"] == "42"
        for r in planned
    )
    files = ht.assignment_files(
        planned, output=tmp_path / "master.csv", tasks_dir=tmp_path / "tasks"
    )
    assert ht.write_assignment_files(files, input_path=source) == "created"
    assert ht.write_assignment_files(files, input_path=source) == "unchanged"
    assert source.read_bytes() == before


def test_determinism_and_seed(source, planned):
    assert planned == ht.build_human_train_assignment(IDS[::-1], input_path=source)
    assert {r["content_hash"] for r in planned} != {
        r["content_hash"] for r in ht.build_human_train_assignment(IDS, input_path=source, seed=43)
    }
    lines = source.read_bytes().splitlines(keepends=True)
    source.write_bytes(lines[0] + b"".join(reversed(lines[1:])))
    assert planned == ht.build_human_train_assignment(IDS, input_path=source)


@pytest.mark.parametrize(
    "ids",
    [
        ["a", "b"],
        ["a", "b", "c", "d"],
        ["a", "a", "b"],
        ["a", "A", "b"],
        ["../a", "b", "c"],
        ["", "b", "c"],
    ],
)
def test_bad_ids(source, ids):
    with pytest.raises(AnnotationError):
        ht.build_human_train_assignment(ids, input_path=source)


def test_conflict_preflight_and_input_protection(source, planned, tmp_path):
    master = tmp_path / "master.csv"
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    conflict = tasks / "bob.csv"
    conflict.write_bytes(b"existing")
    files = ht.assignment_files(planned, output=master, tasks_dir=tasks)
    with pytest.raises(AnnotationError, match="differs"):
        ht.write_assignment_files(files, input_path=source)
    assert not master.exists() and not (tasks / "alice.csv").exists()
    assert conflict.read_bytes() == b"existing"
    before = source.read_bytes()
    with pytest.raises(AnnotationError, match="original"):
        ht.write_assignment_files({source: b"bad"}, input_path=source)
    assert source.read_bytes() == before


def test_dry_run_and_help(source, tmp_path, capsys):
    output = tmp_path / "new" / "master.csv"
    tasks = tmp_path / "new-tasks"
    args = [
        "--input",
        str(source),
        "--output",
        str(output),
        "--tasks-dir",
        str(tasks),
        "--annotators",
        *IDS,
    ]
    assert build_main([*args, "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "dry-run" in printed and "SHA-256" in printed and "300" in printed
    assert not output.parent.exists() and not tasks.exists()
    assert build_main(args) == 0
    assert build_main(args) == 0
    assert "unchanged" in capsys.readouterr().out
    assert build_main([*args, "--seed", "43"]) == 1
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_human_train_assignment.py"), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0 and "--dry-run" in result.stdout


@pytest.fixture
def task_repository(source, planned, tmp_path):
    files = ht.assignment_files(
        planned,
        output=tmp_path / "master.csv",
        tasks_dir=tmp_path / "annotations/tasks/human-train-v0",
    )
    ht.write_assignment_files(files, input_path=source)
    for row in planned:
        image = tmp_path / ht.COMPONENT_PATHS[row["component"]] / row["relative_image_path"]
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (2, 2)).save(image)
    return tmp_path


def test_blinded_tasks_and_errors(task_repository):
    root = task_repository
    assert ht.list_annotators(root) == IDS
    for annotator in IDS:
        task = root / f"annotations/tasks/human-train-v0/{annotator}.csv"
        with task.open() as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames == list(ht.TASK_FIELDS)
            rows = list(reader)
        samples = ht.load_human_train_task(annotator, root)
        assert len(samples) == len(rows) == 100
        assert [r["annotation_order"] for r in rows] == [str(i) for i in range(1, 101)]
        assert [s.content_hash for s in samples] == [r["content_hash"] for r in rows]
    with pytest.raises(AnnotationError, match="No task"):
        ht.load_human_train_task("unknown", root)
    samples[0].image_path.unlink()
    with pytest.raises(AnnotationError, match="image missing"):
        ht.load_human_train_task("carol", root)
    with pytest.raises(AnnotationError, match="Invalid annotator"):
        ht.human_train_annotation_path("../bob", root)
    output = ht.human_train_annotation_path("alice", root)
    output.parent.mkdir(parents=True)
    output.symlink_to(root / "bob.csv")
    with pytest.raises(AnnotationError, match="symlink"):
        ht.human_train_annotation_path("alice", root)


def test_app_autosave_resume_and_isolation(task_repository, monkeypatch):
    from streamlit.testing.v1 import AppTest

    root = task_repository
    samples = ht.load_human_train_task("alice", root)
    output = ht.human_train_annotation_path("alice", root)
    monkeypatch.setattr(
        ht, "load_human_train_task", partial(ht.load_human_train_task, repository_root=root)
    )
    monkeypatch.setattr(
        ht,
        "human_train_annotation_path",
        partial(ht.human_train_annotation_path, repository_root=root),
    )
    monkeypatch.setattr(
        sys, "argv", ["annotation_app.py", "--mode", "human-train", "--annotator", "alice"]
    )
    app = AppTest.from_file(str(ROOT / "annotation_app.py")).run()
    assert not app.exception and not app.error
    next(button for button in app.button if button.label == "Next →").click().run()
    assert not app.exception and not app.error
    assert load_annotations(output)[0].content_hash == samples[0].content_hash
    resumed = AppTest.from_file(str(ROOT / "annotation_app.py")).run()
    assert not resumed.exception
    assert (
        next(metric for metric in resumed.metric if metric.label == "Queue position").value
        == "2 / 100"
    )
    assert not (root / "annotations/human-train-v0/bob").exists()
    assert not (root / "annotations/openfake").exists()


def test_app_cli_rejects_overrides_and_lists_without_streamlit(monkeypatch, capsys):
    import annotation_app

    for option in (
        ["--annotations", "/tmp/other.csv"],
        ["--manifest", "/tmp/other.jsonl"],
        ["--demo"],
        ["--calibration"],
        ["--annotation-round", "2"],
    ):
        with pytest.raises(SystemExit):
            annotation_app.parse_args(["--mode", "human-train", "--annotator", "alice", *option])
    monkeypatch.setattr(sys, "argv", ["annotation_app.py", "--list-annotators"])
    monkeypatch.setattr(annotation_app, "list_annotators", lambda: IDS)
    monkeypatch.setattr(
        annotation_app, "style_page", lambda: pytest.fail("Streamlit must not start")
    )
    annotation_app.main()
    assert capsys.readouterr().out.splitlines() == IDS


def test_production_gold_silver_stays_byte_identical():
    source = ROOT / "annotations/splits/gold_silver_assignment.csv"
    if not source.exists():
        pytest.skip("Production source is local-only")
    before = source.read_bytes()
    ht.build_human_train_assignment(IDS, input_path=source)
    assert source.read_bytes() == before
