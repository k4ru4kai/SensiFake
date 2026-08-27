"""Offline coverage for fail-closed Kaggle publication verification."""

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from scripts import stream_collect

DATASET_ID = "saracristinabasco/sensifake-openfake-pilot"
REMOTE_RESOURCES = {"checkpoint.json", "images.zip", "manifest.jsonl", "summary.json"}


def make_publisher(
    output: Path,
) -> tuple[stream_collect.KagglePublisher, stream_collect.ManifestStore]:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    (output / "images").mkdir()
    for name in ("checkpoint.json", "manifest.jsonl", "summary.json"):
        (output / name).touch()
    manifest = stream_collect.ManifestStore(output)
    return (
        stream_collect.KagglePublisher(output, config.kaggle, config.retry, manifest),
        manifest,
    )


def completed(command: list[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def install_successful_remote(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner: str = "saracristinabasco",
    private: bool = True,
    metadata_resources: set[str] = REMOTE_RESOURCES,
    listed_resources: set[str] = REMOTE_RESOURCES,
    status: str = "ready",
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(command)
        if command[1:3] == ["datasets", "metadata"]:
            metadata_path = Path(command[command.index("--path") + 1]) / "dataset-metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "ownerUser": owner,
                        "datasetSlug": "sensifake-openfake-pilot",
                        "isPrivate": private,
                        "data": [{"name": name} for name in sorted(metadata_resources)],
                    }
                ),
                encoding="utf-8",
            )
            return completed(command)
        if command[1:3] == ["datasets", "files"]:
            return completed(
                command,
                json.dumps([{"name": name} for name in sorted(listed_resources)]),
            )
        if command[1:3] == ["datasets", "status"]:
            return completed(
                command,
                json.dumps({"status": status, "current_version_number": 1}),
            )
        return completed(command)

    monkeypatch.setattr(stream_collect.subprocess, "run", run)
    return calls


def test_definitive_configs_use_confirmed_private_owner() -> None:
    for path in (Path("configs/sources/openfake.toml"),):
        config = stream_collect.load_config(path)

        assert config.kaggle.dataset_id == DATASET_ID
        assert config.kaggle.private is True


def test_success_is_recorded_only_after_all_remote_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    publisher, _ = make_publisher(tmp_path)
    calls = install_successful_remote(monkeypatch)
    state = stream_collect.KaggleState()

    assert publisher.synchronize(state, time.monotonic() + 60) is True
    assert [command[2] for command in calls] == ["create", "metadata", "files", "status"]
    assert state.created is True
    assert state.successful_syncs == 1
    assert state.last_successful_sync is not None
    assert state.last_error is None


@pytest.mark.parametrize(
    ("owner", "private"),
    [("someone-else", True), ("saracristinabasco", False)],
)
def test_identity_or_privacy_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    owner: str,
    private: bool,
) -> None:
    publisher, manifest = make_publisher(tmp_path)
    calls = install_successful_remote(monkeypatch, owner=owner, private=private)
    state = stream_collect.KaggleState()

    assert publisher.synchronize(state, time.monotonic() + 60) is False
    assert len(calls) == 2
    assert state == stream_collect.KaggleState(last_error="Kaggle remote verification failed")
    error = json.loads(manifest.errors_path.read_text(encoding="utf-8"))
    assert error["category"] == "kaggle_remote_verification"


@pytest.mark.parametrize(
    ("metadata_resources", "listed_resources", "status"),
    [
        (REMOTE_RESOURCES - {"images.zip"}, REMOTE_RESOURCES, "ready"),
        (REMOTE_RESOURCES, REMOTE_RESOURCES - {"images.zip"}, "ready"),
        (REMOTE_RESOURCES, REMOTE_RESOURCES, "blobs_received"),
    ],
)
def test_incomplete_remote_publication_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    metadata_resources: set[str],
    listed_resources: set[str],
    status: str,
) -> None:
    publisher, _ = make_publisher(tmp_path)
    install_successful_remote(
        monkeypatch,
        metadata_resources=metadata_resources,
        listed_resources=listed_resources,
        status=status,
    )
    state = stream_collect.KaggleState()

    assert publisher.synchronize(state, time.monotonic() + 60) is False
    assert state.created is False
    assert state.successful_syncs == 0
    assert state.last_successful_sync is None
    assert state.last_error == "Kaggle remote verification failed"


def test_failed_upload_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    publisher, _ = make_publisher(tmp_path)
    calls: list[list[str]] = []

    def fail(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(command)
        return subprocess.CompletedProcess(command, 23)

    monkeypatch.setattr(stream_collect.subprocess, "run", fail)
    state = stream_collect.KaggleState()

    assert publisher.synchronize(state, time.monotonic() + 60) is False
    assert len(calls) == 1
    assert calls[0][1:3] == ["datasets", "create"]
    assert state.created is False
    assert state.successful_syncs == 0
    assert state.last_error == "Kaggle synchronization failed (exit_23)"
