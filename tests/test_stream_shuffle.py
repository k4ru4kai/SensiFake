"""Focused tests for bounded Hugging Face streaming shuffle behavior."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts import stream_collect


class RecordingDataset:
    """Minimal stream double that records shuffle requests."""

    def __init__(self) -> None:
        self.shuffle_calls: list[dict[str, int]] = []

    def shuffle(self, *, seed: int, buffer_size: int) -> "RecordingDataset":
        self.shuffle_calls.append({"seed": seed, "buffer_size": buffer_size})
        return self


def make_source(*, shuffle: bool, shuffle_buffer: int, seed: int = 42) -> Any:
    """Build a source without opening or importing a live dataset."""
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    collection = replace(
        config.collection,
        shuffle=shuffle,
        shuffle_buffer=shuffle_buffer,
        seed=seed,
    )
    return stream_collect.HuggingFaceStreamingSource(config.dataset, collection, adapter)


def test_zero_shuffle_buffer_bypasses_dataset_shuffle() -> None:
    dataset = RecordingDataset()

    result = make_source(shuffle=True, shuffle_buffer=0)._apply_streaming_shuffle(dataset)

    assert result is dataset
    assert dataset.shuffle_calls == []


def test_positive_shuffle_buffer_uses_configured_size_and_seed() -> None:
    dataset = RecordingDataset()

    result = make_source(
        shuffle=True,
        shuffle_buffer=37,
        seed=123,
    )._apply_streaming_shuffle(dataset)

    assert result is dataset
    assert dataset.shuffle_calls == [{"seed": 123, "buffer_size": 37}]


def test_negative_shuffle_buffer_is_rejected() -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    invalid = replace(
        config,
        collection=replace(config.collection, shuffle_buffer=-1),
    )

    with pytest.raises(stream_collect.ConfigurationError, match="shuffle_buffer must be >= 0"):
        stream_collect.validate_config(invalid)


def test_definitive_config_is_balanced_and_does_not_shuffle_source() -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))

    assert config.collection.target == 600
    assert config.collection.quotas == {"real": 300, "fake": 300}
    assert config.collection.seed == 42
    assert config.collection.shuffle is False
    assert config.collection.shuffle_buffer == 0
    assert config.collection.checkpoint_interval > 0
    assert config.kaggle.enabled is False
