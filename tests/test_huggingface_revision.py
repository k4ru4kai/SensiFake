"""Offline tests for immutable Hugging Face revision provenance."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.collection import stream_collect

RESOLVED_SHA = "a" * 40


class EmptyDataset:
    def __init__(self) -> None:
        self.features: dict[str, Any] = {}

    def __iter__(self) -> Any:
        return iter(())


def test_symbolic_revision_resolves_to_commit_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def dataset_info(_self: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(sha=RESOLVED_SHA.upper())

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub.HfApi, "dataset_info", dataset_info)

    assert stream_collect.resolve_huggingface_revision("owner/dataset", "main") == RESOLVED_SHA
    assert calls == [
        {
            "repo_id": "owner/dataset",
            "revision": "main",
            "files_metadata": False,
        }
    ]


def test_resolved_sha_is_used_for_stream_loading_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = stream_collect.load_config(Path("configs/sources/sid_set.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    source = stream_collect.HuggingFaceStreamingSource(
        config.dataset, config.collection, adapter
    )
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        stream_collect,
        "resolve_huggingface_revision",
        lambda dataset_id, revision: RESOLVED_SHA,
    )

    def load_dataset(dataset_id: str, **kwargs: Any) -> EmptyDataset:
        calls.append({"dataset_id": dataset_id, **kwargs})
        return EmptyDataset()

    import datasets

    monkeypatch.setattr(datasets, "load_dataset", load_dataset)
    source.open()
    source.close()

    assert calls[0]["revision"] == RESOLVED_SHA
    assert calls[0]["streaming"] is True
    assert source.resolved_revision == RESOLVED_SHA


def test_expected_revision_drift_stops_before_stream_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = stream_collect.load_config(Path("configs/sources/sid_set_1500.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    source = stream_collect.HuggingFaceStreamingSource(
        config.dataset, config.collection, adapter
    )
    load_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        stream_collect,
        "resolve_huggingface_revision",
        lambda dataset_id, revision: RESOLVED_SHA,
    )

    import datasets

    monkeypatch.setattr(
        datasets,
        "load_dataset",
        lambda *args, **kwargs: load_calls.append({"args": args, **kwargs}),
    )

    with pytest.raises(
        stream_collect.SourceConfigurationError,
        match="does not match expected commit SHA",
    ):
        source.open()

    assert load_calls == []


def test_revision_resolution_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_self: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("offline")

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub.HfApi, "dataset_info", fail)

    with pytest.raises(
        stream_collect.SourceConfigurationError,
        match="could not be resolved to an immutable commit",
    ):
        stream_collect.resolve_huggingface_revision("owner/dataset", "main")


def test_invalid_revision_metadata_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import huggingface_hub

    monkeypatch.setattr(
        huggingface_hub.HfApi,
        "dataset_info",
        lambda _self, **_kwargs: SimpleNamespace(sha=None),
    )

    with pytest.raises(
        stream_collect.SourceConfigurationError,
        match="did not contain a valid commit SHA",
    ):
        stream_collect.resolve_huggingface_revision("owner/dataset", "main")


def test_cli_can_enforce_balanced_smoke_quotas() -> None:
    args = stream_collect.parse_args(
        [
            "--config",
            "configs/sources/sid_set.toml",
            "--output",
            "unused",
            "--max-samples",
            "2",
            "--quota",
            "real=1",
            "--quota",
            "fake=1",
        ]
    )

    config = stream_collect.apply_cli_overrides(
        stream_collect.load_config(args.config),
        args,
    )

    assert config.collection.target == 2
    assert config.collection.quotas == {"real": 1, "fake": 1}


def test_sid_set_production_config_is_balanced_and_pinned() -> None:
    config = stream_collect.load_config(Path("configs/sources/sid_set_1500.toml"))

    assert config.dataset.dataset_id == "saberzl/SID_Set"
    assert config.dataset.revision == "main"
    assert config.dataset.expected_resolved_revision == (
        "dc03ead57929879319ce30a82bfcfb8d317b10bd"
    )
    assert config.dataset.streaming is True
    assert config.collection.target == 1_500
    assert config.collection.quotas == {"real": 750, "fake": 750}
    assert config.collection.shuffle is False
    assert config.collection.shuffle_buffer == 0
    assert config.collection.checkpoint_interval == 20
    assert config.collection.max_source_records == 50_000
    assert config.collection.resume is True
    assert config.kaggle.enabled is False
