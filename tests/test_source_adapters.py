"""Offline coverage for explicit source adapters and manifest semantics."""

import base64
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.collection import stream_collect
from scripts.collection.source_adapters import OpenFakeAdapter, SidSetAdapter

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class OfflineSource:
    resolved_revision = "0" * 40
    requires_original_encoded_bytes = True

    @staticmethod
    def decode_label(value: Any) -> Any:
        return value


class RepeatedTamperedSource(OfflineSource):
    def __init__(self) -> None:
        self.position = 0
        self.close_calls = 0

    def open(self, state: Any = None) -> None:
        del state

    def next_record(self) -> dict[str, Any]:
        self.position += 1
        return {
            "img_id": f"tampered-{self.position}",
            "image": {"bytes": ONE_PIXEL_PNG},
            "mask": {"bytes": b"mock-mask"},
            "width": 1,
            "height": 1,
            "label": 2,
        }

    def state_dict(self) -> dict[str, int]:
        return {"position": self.position}

    def close(self) -> None:
        self.close_calls += 1


def test_openfake_adapter_normalizes_established_fields() -> None:
    example = OpenFakeAdapter().normalize(
        {
            "id": "openfake-7",
            "image": {"bytes": ONE_PIXEL_PNG, "path": None},
            "label": "Fake",
            "model": "generator-name",
            "prompt": "visible prompt",
        },
        decode_label=lambda value: value,
    )

    assert example.source_id == "openfake-7"
    assert example.normalized_label == "fake"
    assert example.original_label == "Fake"
    assert example.metadata == {"prompt": "visible prompt", "model": "generator-name"}


@pytest.mark.parametrize(("native_label", "expected"), [(0, "real"), (1, "fake")])
def test_sid_set_binary_label_mapping(native_label: int, expected: str) -> None:
    adapter = SidSetAdapter({"0": "real", "1": "fake", "2": "skip"})

    example = adapter.normalize(
        {
            "img_id": "sid-1",
            "image": {"bytes": ONE_PIXEL_PNG},
            "mask": None,
            "label": native_label,
        },
        decode_label=lambda value: value,
    )

    assert example.normalized_label == expected
    assert example.source_id == "sid-1"
    assert example.metadata["sid_set_label"] == native_label
    assert example.metadata["sid_set_label_name"] == (
        "real" if native_label == 0 else "full_synthetic"
    )
    assert adapter.encoded_image_fields == ("image", "mask")


def test_sid_set_tampered_label_is_skipped_before_binary_persistence(tmp_path: Path) -> None:
    config = stream_collect.load_config(Path("configs/sources/sid_set.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    manifest = stream_collect.ManifestStore(tmp_path)
    counters = stream_collect.Counters()

    example = adapter.normalize(
        {
            "img_id": "tampered-2",
            "image": {"bytes": ONE_PIXEL_PNG},
            "mask": {"bytes": b"future-mask"},
            "width": 1024,
            "height": 768,
            "label": 2,
        },
        decode_label=lambda value: value,
    )
    assert example.normalized_label is None
    assert example.skip_reason == "tampered"
    assert example.auxiliary_metadata["mask"] == {"bytes": b"future-mask"}
    assert example.metadata["sid_set_label"] == 2
    assert example.metadata["sid_set_label_name"] == "tampered"
    assert example.metadata["source_width"] == 1024
    assert example.metadata["source_height"] == 768

    stream_collect._process_record(
        record={
            "img_id": "tampered-2",
            "image": {"bytes": ONE_PIXEL_PNG},
            "mask": {"bytes": b"future-mask"},
            "width": 1024,
            "height": 768,
            "label": 2,
        },
        stream_position=1,
        source=OfflineSource(),
        adapter=adapter,
        config=config,
        output=tmp_path,
        manifest=manifest,
        counters=counters,
    )

    assert counters.skipped == 1
    assert counters.skipped_by_reason == {"tampered": 1}
    assert counters.accepted == 0
    assert not manifest.path.exists()
    assert not (tmp_path / "images").exists()


def test_adapter_is_selected_explicitly_from_configuration() -> None:
    openfake = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    sid_set = stream_collect.load_config(Path("configs/sources/sid_set.toml"))

    assert isinstance(
        stream_collect.create_adapter(openfake.adapter_name, openfake.adapter_options),
        OpenFakeAdapter,
    )
    assert isinstance(
        stream_collect.create_adapter(sid_set.adapter_name, sid_set.adapter_options),
        SidSetAdapter,
    )
    assert sid_set.dataset.config_name == "default"
    assert sid_set.dataset.split == "train"
    assert sid_set.collection.max_source_records == 50


def test_collector_stops_at_configured_source_record_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = stream_collect.load_config(Path("configs/sources/sid_set.toml"))
    config = replace(
        config,
        collection=replace(config.collection, max_source_records=3),
    )
    source = RepeatedTamperedSource()
    monkeypatch.setattr(stream_collect, "create_source", lambda *_: source)

    exit_reason, counters = stream_collect.collect(
        config,
        tmp_path,
        publish_kaggle=False,
        resume=False,
        shutdown=stream_collect.ShutdownController(),
    )

    assert exit_reason == "source_record_limit"
    assert counters.scanned == 3
    assert counters.accepted == 0
    assert counters.skipped == 3
    assert counters.skipped_by_reason == {"tampered": 3}
    assert source.close_calls == 1


def test_openfake_manifest_fields_remain_unchanged(tmp_path: Path) -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    manifest = stream_collect.ManifestStore(tmp_path)
    counters = stream_collect.Counters()

    stream_collect._process_record(
        record={
            "id": "openfake-1",
            "image": {"bytes": ONE_PIXEL_PNG, "path": None},
            "label": "real",
            "prompt": "offline prompt",
            "model": "real",
        },
        stream_position=1,
        source=OfflineSource(),
        adapter=adapter,
        config=config,
        output=tmp_path,
        manifest=manifest,
        counters=counters,
    )

    row = json.loads(manifest.path.read_text(encoding="utf-8"))
    assert set(row) == stream_collect.MANIFEST_RESERVED_FIELDS | {"prompt", "model"}
    assert row["sample_id"] == "openfake-1"
    assert row["normalized_label"] == "real"
    assert row["original_label"] == "real"
    assert row["source_dataset"] == "ComplexDataLab/OpenFake"
    assert row["requested_revision"] == "v1.0"
    assert row["resolved_revision"] == "0" * 40
    assert row["split"] == "train"
    assert row["prompt"] == "offline prompt"
    assert row["model"] == "real"
    assert row["relative_image_path"].startswith("images/real/")
    assert counters.accepted == 1
