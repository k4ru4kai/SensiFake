"""Regression coverage for orderly streaming-source shutdown."""

import base64
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from scripts import stream_collect

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class ClosableIterator:
    """Iterator double that records explicit cleanup."""

    def __init__(self, source: Any) -> None:
        self.source = source
        self.close_calls = 0
        self.owners_present_during_close = False

    def close(self) -> None:
        self.close_calls += 1
        self.owners_present_during_close = (
            self.source.iterator is self and self.source.dataset is not None
        )


class EmptyDataset:
    """Minimal offline dataset double returned by load_dataset."""

    def __init__(self) -> None:
        self.features: dict[str, Any] = {}

    def __iter__(self) -> Any:
        return iter(())


class ClosableDatasetOwner:
    """Dataset wrapper double used to verify reverse owner cleanup."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class OneRecordSource:
    """Offline source that exercises the normal target-reached path."""

    resolved_revision = "0" * 40
    requires_original_encoded_bytes = True

    def __init__(self) -> None:
        self.yielded = False
        self.close_calls = 0

    def open(self, state: Any = None) -> None:
        del state

    def next_record(self) -> dict[str, Any]:
        if self.yielded:
            raise StopIteration
        self.yielded = True
        return {
            "id": "offline-1",
            "image": {"bytes": ONE_PIXEL_PNG, "path": None},
            "label": "real",
            "prompt": "offline test prompt",
            "model": "offline-test",
        }

    def state_dict(self) -> dict[str, int]:
        return {"yielded": int(self.yielded)}

    def decode_label(self, value: Any) -> Any:
        return value

    def close(self) -> None:
        self.close_calls += 1


def test_huggingface_source_close_releases_owned_resources() -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    source = stream_collect.HuggingFaceStreamingSource(
        config.dataset, config.collection, adapter
    )
    iterator = ClosableIterator(source)
    first_owner = ClosableDatasetOwner()
    final_owner = ClosableDatasetOwner()
    source.iterator = iterator
    source.dataset = final_owner
    source.dataset_owners = [first_owner, final_owner]
    source.label_feature = object()

    source.close()
    source.close()

    assert iterator.close_calls == 1
    assert iterator.owners_present_during_close
    assert first_owner.close_calls == 1
    assert final_owner.close_calls == 1
    assert source.iterator is None
    assert source.dataset is None
    assert source.dataset_owners == []
    assert source.label_feature is None


def test_huggingface_source_requests_single_record_batches(monkeypatch: Any) -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    source = stream_collect.HuggingFaceStreamingSource(
        config.dataset, config.collection, adapter
    )
    calls: list[dict[str, Any]] = []
    resolved_sha = "1" * 40

    monkeypatch.setattr(
        stream_collect,
        "resolve_huggingface_revision",
        lambda dataset_id, revision: resolved_sha,
    )

    def load_dataset(dataset_id: str, **kwargs: Any) -> EmptyDataset:
        calls.append({"dataset_id": dataset_id, **kwargs})
        return EmptyDataset()

    import datasets

    monkeypatch.setattr(datasets, "load_dataset", load_dataset)
    source.open()
    source.close()

    assert len(calls) == 1
    assert calls[0]["streaming"] is True
    assert calls[0]["revision"] == resolved_sha
    assert calls[0]["batch_size"] == stream_collect.HF_STREAMING_BATCH_SIZE == 1
    assert calls[0]["fragment_scan_options"] is not None
    assert calls[0]["fragment_scan_options"].pre_buffer is False


def test_target_reached_closes_streaming_source(monkeypatch: Any, tmp_path: Path) -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    config = replace(config, collection=replace(config.collection, target=1))
    source = OneRecordSource()
    monkeypatch.setattr(stream_collect, "create_source", lambda *_: source)

    exit_reason, counters = stream_collect.collect(
        config,
        tmp_path,
        publish_kaggle=False,
        resume=False,
        shutdown=stream_collect.ShutdownController(),
    )

    assert exit_reason == "target_reached"
    assert counters.accepted == 1
    assert source.close_calls == 1
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["source"]["requested_revision"] == "v1.0"
    assert summary["source"]["resolved_revision"] == "0" * 40
