"""Focused coverage for durable collector checkpoint and resume behavior."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image

from scripts.collection import stream_collect


def encoded_png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color).save(buffer, format="PNG")
    return buffer.getvalue()


class ResumableSource:
    resolved_revision = "0" * 40
    requires_original_encoded_bytes = True

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.position = 0
        self.close_calls = 0

    def open(self, state: Mapping[str, Any] | None = None) -> None:
        if state is not None:
            self.position = int(state["position"])

    def next_record(self) -> dict[str, Any]:
        if self.position >= len(self.records):
            raise StopIteration
        record = self.records[self.position]
        self.position += 1
        return record

    def state_dict(self) -> dict[str, int]:
        return {"position": self.position}

    @staticmethod
    def decode_label(value: Any) -> Any:
        return value

    def close(self) -> None:
        self.close_calls += 1


def test_collection_resumes_from_compatible_checkpoint(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    records = [
        {
            "id": "resume-1",
            "image": {"bytes": encoded_png((255, 0, 0)), "path": None},
            "label": "real",
            "prompt": "first",
            "model": "real",
        },
        {
            "id": "resume-2",
            "image": {"bytes": encoded_png((0, 255, 0)), "path": None},
            "label": "real",
            "prompt": "second",
            "model": "real",
        },
    ]
    opened_sources: list[ResumableSource] = []

    def create_source(*_args: Any) -> ResumableSource:
        source = ResumableSource(records)
        opened_sources.append(source)
        return source

    monkeypatch.setattr(stream_collect, "create_source", create_source)
    base_config = stream_collect.load_config(Path("configs/sources/openfake.toml"))

    first_config = replace(
        base_config,
        collection=replace(base_config.collection, target=1),
    )
    first_reason, first_counters = stream_collect.collect(
        first_config,
        tmp_path,
        publish_kaggle=False,
        resume=False,
        shutdown=stream_collect.ShutdownController(),
    )

    second_config = replace(
        base_config,
        collection=replace(base_config.collection, target=2),
    )
    second_reason, second_counters = stream_collect.collect(
        second_config,
        tmp_path,
        publish_kaggle=False,
        resume=True,
        shutdown=stream_collect.ShutdownController(),
    )

    assert first_reason == "target_reached"
    assert first_counters.accepted == 1
    assert second_reason == "target_reached"
    assert second_counters.accepted == 2
    assert opened_sources[1].position == 2
    assert all(source.close_calls == 1 for source in opened_sources)
    assert len((tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["requested_revision"] == "v1.0"
    assert checkpoint["resolved_revision"] == "0" * 40
    assert checkpoint["source_state"] == {"position": 2}
