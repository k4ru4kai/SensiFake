"""Focused coverage for read-only, fingerprinted exclusion manifests."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from scripts.collection import stream_collect


class OfflineSource:
    resolved_revision = "0" * 40
    requires_original_encoded_bytes = True

    @staticmethod
    def decode_label(value: Any) -> Any:
        return value


def encoded_png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(buffer, format="PNG")
    return buffer.getvalue()


def write_exclusion_manifest(
    root: Path,
    colors: list[tuple[int, int, int]],
) -> tuple[Path, list[str]]:
    root.mkdir(parents=True)
    image_root = root / "images"
    image_root.mkdir()
    rows: list[dict[str, str]] = []
    hashes: list[str] = []
    for index, color in enumerate(colors):
        content = encoded_png(color)
        content_hash = hashlib.sha256(content).hexdigest()
        relative_path = Path("images") / f"{index}.png"
        (root / relative_path).write_bytes(content)
        rows.append(
            {
                "content_hash": content_hash,
                "relative_image_path": relative_path.as_posix(),
            }
        )
        hashes.append(content_hash)
    manifest = root / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return manifest, hashes


def openfake_record(identifier: str, content: bytes) -> dict[str, Any]:
    return {
        "id": identifier,
        "image": {"bytes": content, "path": None},
        "label": "real",
        "prompt": "synthetic fixture",
        "model": "fixture",
    }


def test_valid_exclusion_manifest_is_loaded_read_only(tmp_path: Path) -> None:
    manifest, hashes = write_exclusion_manifest(tmp_path / "existing", [(1, 2, 3)])
    manifest_before = manifest.read_bytes()
    image = manifest.parent / "images/0.png"
    image_before = image.read_bytes()

    exclusions = stream_collect.load_exclusion_manifests((str(manifest),))

    assert exclusions.hashes == frozenset(hashes)
    assert exclusions.manifests[0].path == str(manifest)
    assert exclusions.manifests[0].sha256 == hashlib.sha256(manifest_before).hexdigest()
    assert exclusions.manifests[0].hash_count == 1
    assert manifest.read_bytes() == manifest_before
    assert image.read_bytes() == image_before


def test_multiple_exclusion_manifests_have_deterministic_provenance(
    tmp_path: Path,
) -> None:
    first, first_hashes = write_exclusion_manifest(tmp_path / "first", [(10, 20, 30)])
    second, second_hashes = write_exclusion_manifest(tmp_path / "second", [(40, 50, 60)])
    paths = (str(first), str(second))

    first_load = stream_collect.load_exclusion_manifests(paths)
    second_load = stream_collect.load_exclusion_manifests(paths)

    assert first_load == second_load
    assert first_load.hashes == frozenset(first_hashes + second_hashes)
    assert [item.path for item in first_load.manifests] == list(paths)


@pytest.mark.parametrize(
    "manifest_text",
    [
        "not-json\n",
        json.dumps({"relative_image_path": "images/0.png"}) + "\n",
        json.dumps({"content_hash": "not-a-sha", "relative_image_path": "images/0.png"})
        + "\n",
        json.dumps({"content_hash": "0" * 64}) + "\n",
    ],
)
def test_malformed_exclusion_manifest_is_rejected(
    tmp_path: Path,
    manifest_text: str,
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(manifest_text, encoding="utf-8")

    with pytest.raises(stream_collect.ConfigurationError):
        stream_collect.load_exclusion_manifests((str(manifest),))


def test_missing_exclusion_manifest_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(stream_collect.ConfigurationError, match="does not exist"):
        stream_collect.load_exclusion_manifests((str(tmp_path / "missing.jsonl"),))


def test_matching_hash_is_excluded_without_writing_or_satisfying_quota(
    tmp_path: Path,
) -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    manifest = stream_collect.ManifestStore(tmp_path / "output")
    counters = stream_collect.Counters()
    content = encoded_png((70, 80, 90))
    content_hash = hashlib.sha256(content).hexdigest()
    exclusions = stream_collect.ExclusionSet(frozenset({content_hash}))

    stream_collect._process_record(
        record=openfake_record("excluded", content),
        stream_position=1,
        source=OfflineSource(),
        adapter=adapter,
        config=config,
        output=tmp_path / "output",
        manifest=manifest,
        counters=counters,
        exclusions=exclusions,
    )

    assert counters.accepted == 0
    assert counters.accepted_by_label == {}
    assert counters.excluded == 1
    assert counters.excluded_by_reason == {"excluded_existing_hash": 1}
    assert counters.duplicates == 0
    assert not manifest.path.exists()
    assert not (tmp_path / "output/images").exists()


def test_exclusions_and_in_run_duplicates_are_counted_separately(tmp_path: Path) -> None:
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    adapter = stream_collect.create_adapter(config.adapter_name, config.adapter_options)
    output = tmp_path / "output"
    manifest = stream_collect.ManifestStore(output)
    counters = stream_collect.Counters()
    excluded_content = encoded_png((100, 110, 120))
    accepted_content = encoded_png((130, 140, 150))
    exclusions = stream_collect.ExclusionSet(
        frozenset({hashlib.sha256(excluded_content).hexdigest()})
    )

    for position, (identifier, content) in enumerate(
        [
            ("excluded", excluded_content),
            ("accepted", accepted_content),
            ("duplicate", accepted_content),
        ],
        start=1,
    ):
        stream_collect._process_record(
            record=openfake_record(identifier, content),
            stream_position=position,
            source=OfflineSource(),
            adapter=adapter,
            config=config,
            output=output,
            manifest=manifest,
            counters=counters,
            exclusions=exclusions,
        )

    assert counters.accepted == 1
    assert counters.excluded == 1
    assert counters.duplicates == 1
    assert len(manifest.path.read_text(encoding="utf-8").splitlines()) == 1


def test_changed_exclusion_manifest_is_rejected_on_resume(tmp_path: Path) -> None:
    manifest, _ = write_exclusion_manifest(tmp_path / "existing", [(1, 1, 1)])
    config = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    config = replace(
        config,
        collection=replace(config.collection, exclusion_manifests=(str(manifest),)),
    )
    first_exclusions = stream_collect.load_exclusion_manifests((str(manifest),))
    output = tmp_path / "output"
    output.mkdir()
    first_runtime = stream_collect.RuntimeStore(
        output,
        config.source_fingerprint(first_exclusions),
        config.dataset.revision,
        first_exclusions,
    )
    first_runtime.save_checkpoint(
        source_state=None,
        counters=stream_collect.Counters(),
        kaggle_state=stream_collect.KaggleState(),
        resolved_revision="0" * 40,
    )
    first_runtime.save_summary(
        config=config,
        counters=stream_collect.Counters(),
        kaggle_state=stream_collect.KaggleState(),
        resolved_revision="0" * 40,
        publishing_enabled=False,
        started_at="2026-08-28T00:00:00Z",
        exit_reason="running",
    )
    checkpoint = json.loads(first_runtime.checkpoint_path.read_text(encoding="utf-8"))
    summary = json.loads(first_runtime.summary_path.read_text(encoding="utf-8"))
    assert checkpoint["exclusions"] == first_exclusions.as_dict()
    assert summary["exclusions"] == first_exclusions.as_dict()

    replacement = encoded_png((2, 2, 2))
    replacement_hash = hashlib.sha256(replacement).hexdigest()
    (manifest.parent / "images/0.png").write_bytes(replacement)
    manifest.write_text(
        json.dumps(
            {
                "content_hash": replacement_hash,
                "relative_image_path": "images/0.png",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    changed_exclusions = stream_collect.load_exclusion_manifests((str(manifest),))
    changed_runtime = stream_collect.RuntimeStore(
        output,
        config.source_fingerprint(changed_exclusions),
        config.dataset.revision,
        changed_exclusions,
    )

    with pytest.raises(stream_collect.ResumeError, match="incompatible"):
        changed_runtime.load_checkpoint()


def test_legacy_fingerprints_are_unchanged_without_exclusions() -> None:
    openfake = stream_collect.load_config(Path("configs/sources/openfake.toml"))
    sid_set = stream_collect.load_config(Path("configs/sources/sid_set.toml"))

    assert openfake.collection.exclusion_manifests == ()
    assert sid_set.collection.exclusion_manifests == ()
    assert (
        openfake.source_fingerprint()
        == "f5d23b2ceba120683e9fd4245dede0695c780c26a4fdc439b59ab0a6df91b836"
    )
    assert (
        sid_set.source_fingerprint()
        == "d5a8bc6bf27945a602a252e672e5a5540442f9f5568eb368f108fe3aefa34802"
    )


def test_additional_900_configuration_is_pinned_and_excludes_existing_data() -> None:
    config = stream_collect.load_config(
        Path("configs/sources/openfake_additional_900.toml")
    )

    assert config.dataset.dataset_id == "ComplexDataLab/OpenFake"
    assert config.dataset.revision == "v1.0"
    assert (
        config.dataset.expected_resolved_revision
        == "750279a9710d3d98bbc6d0d87250312cfdf922a0"
    )
    assert config.dataset.streaming is True
    assert config.collection.target == 900
    assert config.collection.quotas == {"real": 450, "fake": 450}
    assert config.collection.shuffle is False
    assert config.collection.shuffle_buffer == 0
    assert config.collection.checkpoint_interval == 20
    assert config.collection.max_source_records == 50000
    assert config.collection.max_runtime_minutes == 720
    assert config.collection.shutdown_safety_buffer_seconds == 300
    assert config.collection.exclusion_manifests == (
        "data/datasets/openfake/pilot-600/manifest.jsonl",
        "data/datasets/sid-set/candidate-1500/manifest.jsonl",
    )
    assert config.kaggle.enabled is False
