#!/usr/bin/env python3
"""Progressively collect a reproducible, resumable image dataset."""

# 1. Imports and constants

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

try:
    from .source_adapters import (
        AdapterConfigurationError,
        MissingSourceFieldError,
        SourceAdapter,
        create_adapter,
    )
except ImportError:  # Direct execution: python scripts/stream_collect.py
    from source_adapters import (  # type: ignore[no-redef]
        AdapterConfigurationError,
        MissingSourceFieldError,
        SourceAdapter,
        create_adapter,
    )

LOGGER = logging.getLogger("sensifake.collect")
CHECKPOINT_VERSION = 1
MANIFEST_NAME = "manifest.jsonl"
ERRORS_NAME = "errors.jsonl"
CHECKPOINT_NAME = "checkpoint.json"
SUMMARY_NAME = "summary.json"
KAGGLE_METADATA_NAME = "dataset-metadata.json"
RUNTIME_ENTRIES = {
    "images",
    MANIFEST_NAME,
    ERRORS_NAME,
    CHECKPOINT_NAME,
    SUMMARY_NAME,
    KAGGLE_METADATA_NAME,
}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RESOLVE_SHA_PATTERN = re.compile(r"/resolve/([0-9a-f]{40})(?:/|$)", re.IGNORECASE)
HF_STREAMING_BATCH_SIZE = 1
HF_TOKEN_PATTERN = re.compile(r"\bhf_[A-Za-z0-9]{16,}\b")
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
SECRET_MARKERS = (
    "authorization",
    "credential",
    "password",
    "secret",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-signature",
)
MANIFEST_RESERVED_FIELDS = {
    "sample_id",
    "content_hash",
    "relative_image_path",
    "source_dataset",
    "requested_revision",
    "resolved_revision",
    "split",
    "stream_position",
    "normalized_label",
    "original_label",
    "width",
    "height",
    "image_mode",
    "image_format",
    "byte_source",
    "collection_timestamp",
    "kaggle_synchronized",
    "sensitivity_annotation",
}


class ConfigurationError(ValueError):
    """Raised when configuration is missing or internally inconsistent."""


class ResumeError(RuntimeError):
    """Raised when existing output cannot be resumed safely."""


class ImageValidationError(ValueError):
    """Raised when a streamed value is not a usable encoded image."""


class OriginalBytesUnavailable(RuntimeError):
    """Raised when a source requiring original bytes exposes only a decoded image."""


class SourceConfigurationError(RuntimeError):
    """Raised when a provider cannot enforce required source behaviour."""


class SourceUnavailable(RuntimeError):
    """Raised after the bounded source retry budget is exhausted."""


class RemoteVerificationError(RuntimeError):
    """Raised when a Kaggle publication cannot be proved correct and private."""


# 2. Configuration models and parsing


@dataclass(frozen=True)
class DatasetConfig:
    dataset_id: str
    revision: str
    split: str
    config_name: str | None
    streaming: bool
    accepted_labels: tuple[str, ...]


@dataclass(frozen=True)
class CollectionConfig:
    target: int
    quotas: dict[str, int]
    max_source_records: int | None
    seed: int
    shuffle: bool
    shuffle_buffer: int
    checkpoint_interval: int
    max_runtime_minutes: float
    shutdown_safety_buffer_seconds: float
    resume: bool


@dataclass(frozen=True)
class RetryConfig:
    count: int
    initial_backoff_seconds: float
    maximum_backoff_seconds: float


@dataclass(frozen=True)
class KaggleConfig:
    enabled: bool
    sync_every: int
    dataset_id: str
    title: str
    license_name: str
    license_description: str
    private: bool
    subprocess_timeout_seconds: float


@dataclass(frozen=True)
class AppConfig:
    provider: str
    adapter_name: str
    adapter_options: dict[str, Any]
    dataset: DatasetConfig
    collection: CollectionConfig
    retry: RetryConfig
    kaggle: KaggleConfig

    def source_fingerprint(self) -> str:
        """Hash fields that determine source identity and iteration order."""
        critical = {
            "provider": self.provider,
            "adapter": self.adapter_name,
            "adapter_options": self.adapter_options,
            "dataset_id": self.dataset.dataset_id,
            "revision": self.dataset.revision,
            "split": self.dataset.split,
            "config_name": self.dataset.config_name,
            "streaming": self.dataset.streaming,
            "accepted_labels": self.dataset.accepted_labels,
            "seed": self.collection.seed,
            "shuffle": self.collection.shuffle,
            "shuffle_buffer": self.collection.shuffle_buffer,
        }
        encoded = json.dumps(critical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _table(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"[{key}] must be a TOML table")
    return value


def _text(table: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = table.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _integer(table: Mapping[str, Any], key: str, *, minimum: int = 0) -> int:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationError(f"{key} must be an integer >= {minimum}")
    return value


def _optional_integer(
    table: Mapping[str, Any],
    key: str,
    *,
    minimum: int = 0,
) -> int | None:
    if key not in table:
        return None
    return _integer(table, key, minimum=minimum)


def _number(table: Mapping[str, Any], key: str, *, minimum: float = 0.0) -> float:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigurationError(f"{key} must be a number >= {minimum}")
    return float(value)


def _boolean(table: Mapping[str, Any], key: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be true or false")
    return value


def _string_tuple(table: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{key} must be a non-empty string array")
    items = tuple(str(item).strip() for item in value if str(item).strip())
    if len(items) != len(value) or len(set(items)) != len(items):
        raise ConfigurationError(f"{key} contains empty or duplicate entries")
    return items


def load_config(path: Path) -> AppConfig:
    """Load and validate collector settings from TOML."""
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise ConfigurationError("configuration file could not be read") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError("configuration file is invalid TOML") from exc

    if raw.get("version") != 1:
        raise ConfigurationError("configuration version must be 1")
    dataset_raw = _table(raw, "dataset")
    adapter_raw = _table(raw, "adapter")
    collection_raw = _table(raw, "collection")
    quotas_raw = _table(collection_raw, "quotas")
    retry_raw = _table(raw, "retry")
    kaggle_raw = _table(raw, "kaggle")

    accepted = tuple(label.casefold() for label in _string_tuple(dataset_raw, "accepted_labels"))
    if len(set(accepted)) != len(accepted):
        raise ConfigurationError("accepted_labels must be unique ignoring case")

    quotas: dict[str, int] = {}
    for label, value in quotas_raw.items():
        normalized = str(label).casefold()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigurationError("every label quota must be a non-negative integer")
        quotas[normalized] = value

    adapter_name = _text(adapter_raw, "name").casefold()
    adapter_options = {
        str(key): _json_compatible(value)
        for key, value in adapter_raw.items()
        if key != "name"
    }
    config = AppConfig(
        provider=_text(raw, "provider").casefold(),
        adapter_name=adapter_name,
        adapter_options=adapter_options,
        dataset=DatasetConfig(
            dataset_id=_text(dataset_raw, "id"),
            revision=_text(dataset_raw, "revision"),
            split=_text(dataset_raw, "split"),
            config_name=_text(dataset_raw, "config", allow_empty=True) or None,
            streaming=_boolean(dataset_raw, "streaming"),
            accepted_labels=accepted,
        ),
        collection=CollectionConfig(
            target=_integer(collection_raw, "target", minimum=1),
            quotas=quotas,
            max_source_records=_optional_integer(
                collection_raw, "max_source_records", minimum=1
            ),
            seed=_integer(collection_raw, "seed"),
            shuffle=_boolean(collection_raw, "shuffle"),
            shuffle_buffer=_integer(collection_raw, "shuffle_buffer", minimum=0),
            checkpoint_interval=_integer(collection_raw, "checkpoint_interval", minimum=1),
            max_runtime_minutes=_number(collection_raw, "max_runtime_minutes", minimum=0.01),
            shutdown_safety_buffer_seconds=_number(
                collection_raw, "shutdown_safety_buffer_seconds"
            ),
            resume=_boolean(collection_raw, "resume"),
        ),
        retry=RetryConfig(
            count=_integer(retry_raw, "count"),
            initial_backoff_seconds=_number(retry_raw, "initial_backoff_seconds"),
            maximum_backoff_seconds=_number(retry_raw, "maximum_backoff_seconds"),
        ),
        kaggle=KaggleConfig(
            enabled=_boolean(kaggle_raw, "enabled"),
            sync_every=_integer(kaggle_raw, "sync_every", minimum=1),
            dataset_id=_text(kaggle_raw, "dataset_id"),
            title=_text(kaggle_raw, "title"),
            license_name=_text(kaggle_raw, "license_name"),
            license_description=_text(kaggle_raw, "license_description"),
            private=_boolean(kaggle_raw, "private"),
            subprocess_timeout_seconds=_number(
                kaggle_raw, "subprocess_timeout_seconds", minimum=1.0
            ),
        ),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    """Validate relationships between otherwise well-typed settings."""
    if config.provider != "huggingface":
        raise ConfigurationError(f"unsupported provider: {config.provider}")
    if not config.dataset.streaming:
        raise ConfigurationError("the shared collector requires dataset.streaming = true")
    try:
        create_adapter(config.adapter_name, config.adapter_options)
    except AdapterConfigurationError as exc:
        raise ConfigurationError(str(exc)) from exc
    if config.collection.shuffle_buffer < 0:
        raise ConfigurationError("shuffle_buffer must be >= 0")
    accepted = set(config.dataset.accepted_labels)
    if set(config.collection.quotas) != accepted:
        raise ConfigurationError("quotas must contain exactly the accepted labels")
    if sum(config.collection.quotas.values()) < config.collection.target:
        raise ConfigurationError("target exceeds the sum of label quotas")
    runtime_seconds = config.collection.max_runtime_minutes * 60
    if config.collection.shutdown_safety_buffer_seconds >= runtime_seconds:
        raise ConfigurationError("shutdown safety buffer must be shorter than maximum runtime")
    if config.retry.maximum_backoff_seconds < config.retry.initial_backoff_seconds:
        raise ConfigurationError("maximum retry backoff must not be smaller than initial backoff")
    if not config.kaggle.private:
        raise ConfigurationError("this collector only permits private Kaggle publishing")
    owner, separator, slug = config.kaggle.dataset_id.partition("/")
    if separator != "/" or not owner or not slug:
        raise ConfigurationError("Kaggle dataset_id must use owner/slug form")


# 3. Utility and atomic file functions


def utc_now() -> str:
    """Return a stable, timezone-aware timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Durably replace a JSON file without exposing a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    """Append and flush one JSON Lines record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write bytes through a sibling temporary file and atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if not path.exists():
            os.replace(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_compatible(value: Any) -> Any:
    """Convert common scalar containers without importing provider libraries."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    item_method = getattr(value, "item", None)
    if callable(item_method):
        return _json_compatible(item_method())
    raise TypeError(f"unsupported checkpoint value type: {type(value).__name__}")


def _contains_sensitive_state(value: Any, key_hint: str = "") -> bool:
    """Reject opaque states that could persist credentials or personal paths."""
    lowered_key = key_hint.casefold()
    if any(marker in lowered_key for marker in SECRET_MARKERS):
        return True
    if isinstance(value, Mapping):
        return any(_contains_sensitive_state(item, str(key)) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_sensitive_state(item, key_hint) for item in value)
    if isinstance(value, str):
        lowered = value.casefold()
        if HF_TOKEN_PATTERN.search(value) or any(
            f"{marker}=" in lowered for marker in SECRET_MARKERS
        ):
            return True
        if value.startswith("~/") or os.path.isabs(value) or WINDOWS_ABSOLUTE_PATTERN.match(value):
            return True
    return False


def safe_source_state(value: Any) -> dict[str, Any] | None:
    """Return serializable, non-sensitive source state or omit it safely."""
    if value is None:
        return None
    try:
        converted = _json_compatible(value)
    except (TypeError, ValueError, OverflowError):
        LOGGER.warning("Provider checkpoint state is not JSON-compatible; omitting it")
        return None
    if not isinstance(converted, dict) or _contains_sensitive_state(converted):
        LOGGER.warning("Provider checkpoint state contains unsafe values; omitting it")
        return None
    return converted


def safe_scalar(value: Any, *, maximum_length: int = 16_384) -> Any:
    """Keep only bounded JSON scalar metadata."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    lowered = text.casefold()
    if HF_TOKEN_PATTERN.search(text) or any(f"{marker}=" in lowered for marker in SECRET_MARKERS):
        return "[redacted-secret]"
    if text.startswith("~/") or os.path.isabs(text) or WINDOWS_ABSOLUTE_PATTERN.match(text):
        return "[redacted-local-path]"
    return text[:maximum_length]


def sleep_with_deadline(seconds: float, deadline: float) -> bool:
    """Sleep only while useful runtime remains."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    time.sleep(min(seconds, remaining))
    return time.monotonic() < deadline


def resolve_huggingface_revision(dataset_id: str, requested_revision: str) -> str:
    """Resolve a symbolic Hub revision to an immutable commit SHA."""
    candidate = requested_revision.strip().casefold()
    if SHA_PATTERN.fullmatch(candidate):
        return candidate

    # Kept local so offline config and unit-test collection do not contact the Hub.
    from huggingface_hub import HfApi

    try:
        info = HfApi().dataset_info(
            repo_id=dataset_id,
            revision=requested_revision,
            files_metadata=False,
        )
    except Exception as exc:
        raise SourceConfigurationError(
            "Hugging Face revision could not be resolved to an immutable commit"
        ) from exc
    resolved = getattr(info, "sha", None)
    if not isinstance(resolved, str) or not SHA_PATTERN.fullmatch(resolved.casefold()):
        raise SourceConfigurationError(
            "Hugging Face revision metadata did not contain a valid commit SHA"
        )
    return resolved.casefold()


# 4. Streaming source abstraction


class StreamingSource(Protocol):
    """Provider boundary used by the provider-independent collection loop."""

    resolved_revision: str | None
    requires_original_encoded_bytes: bool

    def open(self, state: Mapping[str, Any] | None = None) -> None: ...

    def next_record(self) -> Mapping[str, Any]: ...

    def state_dict(self) -> dict[str, Any] | None: ...

    def decode_label(self, value: Any) -> Any: ...

    def close(self) -> None: ...


class HuggingFaceStreamingSource:
    """Hugging Face Datasets streaming provider."""

    def __init__(
        self,
        dataset: DatasetConfig,
        collection: CollectionConfig,
        adapter: SourceAdapter,
    ) -> None:
        self.dataset_config = dataset
        self.collection_config = collection
        self.adapter = adapter
        self.dataset: Any = None
        self.dataset_owners: list[Any] = []
        self.iterator: Iterator[Mapping[str, Any]] | None = None
        self.label_feature: Any = None
        self.resolved_revision: str | None = None
        self.requires_original_encoded_bytes = False

    def _apply_streaming_shuffle(self, dataset: Any) -> Any:
        """Apply a bounded deterministic shuffle, or return the stream unchanged."""
        if not self.collection_config.shuffle or self.collection_config.shuffle_buffer == 0:
            return dataset
        return dataset.shuffle(
            seed=self.collection_config.seed,
            buffer_size=self.collection_config.shuffle_buffer,
        )

    def open(self, state: Mapping[str, Any] | None = None) -> None:
        self.close()
        # Kept local so syntax/config verification does not import third parties.
        from datasets import Image as DatasetImage
        from datasets import load_dataset
        from pyarrow.dataset import ParquetFragmentScanOptions

        resolved_revision = resolve_huggingface_revision(
            self.dataset_config.dataset_id,
            self.dataset_config.revision,
        )
        self.resolved_revision = resolved_revision
        load_kwargs: dict[str, Any] = {
            "revision": resolved_revision,
            "split": self.dataset_config.split,
            "streaming": self.dataset_config.streaming,
            "batch_size": HF_STREAMING_BATCH_SIZE,
            "fragment_scan_options": ParquetFragmentScanOptions(pre_buffer=False),
        }
        if self.dataset_config.config_name is not None:
            load_kwargs["name"] = self.dataset_config.config_name
        dataset = load_dataset(
            self.dataset_config.dataset_id,
            **load_kwargs,
            # Datasets otherwise uses the whole first parquet row group. A
            # one-record batch prevents an early stop from leaving Arrow I/O
            # callbacks active against the generator's Python-backed file.
        )
        self.dataset = dataset
        self.dataset_owners = [dataset]

        encoded_image_fields = getattr(
            self.adapter,
            "encoded_image_fields",
            (self.adapter.image_field,),
        )
        for field_name in encoded_image_fields:
            features = getattr(dataset, "features", None)
            image_feature = (
                features.get(field_name) if isinstance(features, Mapping) else None
            )
            if not isinstance(image_feature, DatasetImage):
                if field_name == self.adapter.image_field:
                    self.requires_original_encoded_bytes = False
                continue
            cast_column = getattr(dataset, "cast_column", None)
            if not callable(cast_column):
                raise SourceConfigurationError(
                    "Hugging Face source cannot disable decoding for its image feature"
                )
            try:
                dataset = cast_column(
                    field_name,
                    DatasetImage(decode=False),
                )
            except Exception as exc:
                raise SourceConfigurationError(
                    "Hugging Face image decoding could not be disabled"
                ) from exc
            self.dataset_owners.append(dataset)
            self.dataset = dataset
            cast_features = getattr(dataset, "features", None)
            cast_feature = (
                cast_features.get(field_name)
                if isinstance(cast_features, Mapping)
                else None
            )
            if (
                not isinstance(cast_feature, DatasetImage)
                or getattr(cast_feature, "decode", None) is not False
            ):
                raise SourceConfigurationError(
                    "Hugging Face image decoding disablement could not be verified"
                )
            if field_name == self.adapter.image_field:
                self.requires_original_encoded_bytes = True

        dataset = self._apply_streaming_shuffle(dataset)
        if state is not None:
            restore = getattr(dataset, "load_state_dict", None)
            if not callable(restore):
                LOGGER.warning("Provider does not support restoring streaming state")
            else:
                restore(dict(state))

        features = getattr(dataset, "features", None)
        self.label_feature = (
            features.get(self.adapter.label_field) if isinstance(features, Mapping) else None
        )
        self.dataset = dataset
        self.iterator = iter(dataset)
        discovered_revision = self._discover_resolved_revision(dataset)
        if discovered_revision is not None and discovered_revision != resolved_revision:
            raise SourceConfigurationError(
                "loaded Hugging Face dataset revision differs from resolved commit"
            )

    def close(self) -> None:
        """Finalize the iterator while Python and native dependencies are alive."""
        iterator = self.iterator
        dataset = self.dataset
        owners = self.dataset_owners
        if iterator is None and dataset is None and not owners:
            self.label_feature = None
            return

        try:
            try:
                close_iterator = getattr(iterator, "close", None)
                if callable(close_iterator):
                    close_iterator()
            finally:
                closed: set[int] = set()
                for owner in reversed([*owners, dataset]):
                    if owner is None or id(owner) in closed:
                        continue
                    closed.add(id(owner))
                    close_dataset = getattr(owner, "close", None)
                    if callable(close_dataset):
                        close_dataset()
        finally:
            # Keep the owners reachable until close has unwound the generator
            # and released its backing file; then make repeated close calls no-ops.
            self.iterator = None
            self.dataset = None
            self.dataset_owners = []
            self.label_feature = None

    def next_record(self) -> Mapping[str, Any]:
        if self.iterator is None:
            raise RuntimeError("source is not open")
        record = next(self.iterator)
        if not isinstance(record, Mapping):
            raise TypeError("streamed record is not a mapping")
        if not self.requires_original_encoded_bytes:
            return record

        image_value = record.get(self.adapter.image_field)
        if not isinstance(image_value, Mapping):
            return record
        encoded = image_value.get("bytes")
        if isinstance(encoded, (bytes, bytearray, memoryview)):
            return record
        location = image_value.get("path")
        if not isinstance(location, str) or not location:
            return record

        # Streaming Image(decode=False) normally supplies bytes. If it supplies a
        # provider path instead, xopen preserves the encoded payload without Pillow.
        try:
            from datasets.utils.file_utils import xopen
        except ImportError as exc:
            raise SourceConfigurationError(
                "Hugging Face provider paths cannot be opened by this datasets version"
            ) from exc
        with xopen(location, "rb") as handle:
            content = handle.read()
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise OriginalBytesUnavailable("provider path did not yield encoded bytes")
        normalized_image = dict(image_value)
        normalized_image["bytes"] = bytes(content)
        normalized_image["_sensifake_byte_source"] = "provider_managed_path"
        normalized_record = dict(record)
        normalized_record[self.adapter.image_field] = normalized_image
        return normalized_record

    def state_dict(self) -> dict[str, Any] | None:
        if self.dataset is None:
            return None
        snapshot = getattr(self.dataset, "state_dict", None)
        if not callable(snapshot):
            return None
        state = snapshot()
        return dict(state) if isinstance(state, Mapping) else None

    def decode_label(self, value: Any) -> Any:
        converter = getattr(self.label_feature, "int2str", None)
        if callable(converter) and isinstance(value, int) and not isinstance(value, bool):
            try:
                return converter(value)
            except (TypeError, ValueError):
                return value
        return value

    @staticmethod
    def _discover_resolved_revision(dataset: Any) -> str | None:
        """Best-effort extraction of an immutable Hub commit SHA."""
        candidates: set[str] = set()
        for attribute in ("commit_hash", "_commit_hash"):
            value = getattr(dataset, attribute, None)
            if isinstance(value, str) and SHA_PATTERN.fullmatch(value.casefold()):
                candidates.add(value.casefold())

        info = getattr(dataset, "info", None) or getattr(dataset, "_info", None)
        checksums = getattr(info, "download_checksums", None)
        if isinstance(checksums, Mapping):
            for location in checksums:
                if isinstance(location, str):
                    match = RESOLVE_SHA_PATTERN.search(location)
                    if match:
                        candidates.add(match.group(1).casefold())
        return next(iter(candidates)) if len(candidates) == 1 else None


def create_source(config: AppConfig, adapter: SourceAdapter) -> StreamingSource:
    """Create a provider implementation without coupling it to persistence."""
    if config.provider == "huggingface":
        return HuggingFaceStreamingSource(config.dataset, config.collection, adapter)
    raise ConfigurationError(f"unsupported provider: {config.provider}")


def open_source_with_retries(
    source: StreamingSource,
    state: Mapping[str, Any] | None,
    retry: RetryConfig,
    errors: ManifestStore,
    deadline: float,
) -> None:
    """Open or recreate a source using bounded exponential backoff."""
    for attempt in range(retry.count + 1):
        try:
            source.open(state)
            return
        except SourceConfigurationError as exc:
            errors.append_error(
                category="source_configuration",
                error_type=type(exc).__name__,
                stream_position=None,
                message="source configuration or immutable revision resolution failed",
            )
            raise
        except Exception as exc:
            errors.append_error(
                category="source_open",
                error_type=type(exc).__name__,
                stream_position=None,
                message="stream source could not be opened",
            )
            if attempt >= retry.count:
                raise SourceUnavailable("stream source retry budget exhausted") from exc
            delay = min(
                retry.initial_backoff_seconds * (2**attempt),
                retry.maximum_backoff_seconds,
            )
            LOGGER.warning("Source open failed; retrying in %.1f seconds", delay)
            if not sleep_with_deadline(delay, deadline):
                raise SourceUnavailable("runtime expired while retrying source") from exc


# 5. Image validation and persistence


@dataclass(frozen=True)
class ValidatedImage:
    content: bytes
    sha256: str
    width: int
    height: int
    mode: str
    image_format: str
    extension: str
    byte_source: str


def _read_original_bytes(
    value: Any,
    *,
    allow_reencoding: bool,
) -> tuple[bytes, str]:
    """Prefer source bytes; losslessly fall back to a Pillow serialization."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value), "original_encoded_bytes"

    if isinstance(value, Mapping):
        encoded = value.get("bytes")
        if isinstance(encoded, (bytes, bytearray, memoryview)):
            origin = value.get("_sensifake_byte_source")
            byte_source = (
                origin
                if origin in {"original_encoded_bytes", "provider_managed_path"}
                else "original_encoded_bytes"
            )
            return bytes(encoded), byte_source
        location = value.get("path")
        if isinstance(location, str):
            path = Path(location)
            if path.is_file():
                try:
                    return path.read_bytes(), "provider_managed_path"
                except OSError as exc:
                    raise ImageValidationError("original image path could not be read") from exc

    from PIL import Image

    if isinstance(value, Image.Image):
        if not allow_reencoding:
            raise OriginalBytesUnavailable(
                "recognized Hugging Face image feature exposed a decoded Pillow image"
            )
        filename = getattr(value, "filename", None)
        if isinstance(filename, str) and filename:
            path = Path(filename)
            if path.is_file():
                try:
                    return path.read_bytes(), "provider_managed_path"
                except OSError:
                    pass

        # The decoded provider value no longer exposes its encoded payload. Preserve
        # dimensions and pixels without resizing, and make the fallback explicit.
        fallback_format = str(getattr(value, "format", "") or "PNG").upper()
        buffer = io.BytesIO()
        try:
            value.save(buffer, format=fallback_format)
        except (KeyError, OSError, ValueError):
            fallback_format = "PNG"
            buffer = io.BytesIO()
            try:
                value.save(buffer, format=fallback_format)
            except (KeyError, OSError, ValueError) as exc:
                raise ImageValidationError("decoded image could not be serialized") from exc
        byte_source = f"pillow_reencoded_{fallback_format.casefold()}"
        LOGGER.warning(
            "Original encoded bytes unavailable; using explicit Pillow fallback (%s)",
            byte_source,
        )
        return buffer.getvalue(), byte_source

    if not allow_reencoding:
        raise OriginalBytesUnavailable(
            "recognized Hugging Face image feature yielded no readable encoded bytes"
        )

    raise ImageValidationError("image value exposes neither encoded bytes nor a Pillow image")


def _extension_for_format(image_format: str) -> str:
    canonical = {
        "BMP": "bmp",
        "GIF": "gif",
        "JPEG": "jpg",
        "JPEG2000": "jp2",
        "PNG": "png",
        "TIFF": "tiff",
        "WEBP": "webp",
    }
    if image_format in canonical:
        return canonical[image_format]
    fallback = re.sub(r"[^a-z0-9]", "", image_format.casefold())
    if not fallback:
        raise ImageValidationError("image format has no safe extension")
    return fallback


def validate_image(value: Any, *, allow_reencoding: bool) -> ValidatedImage:
    """Validate one encoded image without resizing or recompressing source bytes."""
    from PIL import Image

    content, byte_source = _read_original_bytes(
        value,
        allow_reencoding=allow_reencoding,
    )
    if not content:
        raise ImageValidationError("image payload is empty")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            image_format = str(probe.format or "").upper()
            probe.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            width, height = image.size
            mode = str(image.mode)
            image_format = str(image.format or image_format).upper()
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError) as exc:
        raise ImageValidationError("Pillow rejected the encoded image") from exc
    if width <= 0 or height <= 0 or not image_format:
        raise ImageValidationError("image has invalid dimensions or format")
    return ValidatedImage(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        width=width,
        height=height,
        mode=mode,
        image_format=image_format,
        extension=_extension_for_format(image_format),
        byte_source=byte_source,
    )


def persist_image(output: Path, label: str, image: ValidatedImage) -> Path:
    """Persist original bytes under a content-addressed relative path."""
    relative = Path("images") / label / f"{image.sha256}.{image.extension}"
    atomic_write_bytes(output / relative, image.content)
    return relative


# 6. Manifest and checkpoint management


@dataclass
class Counters:
    scanned: int = 0
    accepted: int = 0
    skipped: int = 0
    duplicates: int = 0
    errors: int = 0
    reencoded_fallbacks: int = 0
    synchronized: int = 0
    accepted_by_label: Counter[str] = field(default_factory=Counter)
    skipped_by_reason: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "accepted": self.accepted,
            "skipped": self.skipped,
            "duplicates": self.duplicates,
            "errors": self.errors,
            "reencoded_fallbacks": self.reencoded_fallbacks,
            "synchronized": self.synchronized,
            "accepted_by_label": dict(sorted(self.accepted_by_label.items())),
            "skipped_by_reason": dict(sorted(self.skipped_by_reason.items())),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Counters:
        if not isinstance(raw, Mapping):
            return cls()

        def count(key: str) -> int:
            value = raw.get(key, 0)
            return value if isinstance(value, int) and value >= 0 else 0

        labels_raw = raw.get("accepted_by_label", {})
        labels = Counter()
        if isinstance(labels_raw, Mapping):
            labels.update(
                {
                    str(key): value
                    for key, value in labels_raw.items()
                    if isinstance(value, int) and value >= 0
                }
            )
        skipped_raw = raw.get("skipped_by_reason", {})
        skipped_reasons = Counter()
        if isinstance(skipped_raw, Mapping):
            skipped_reasons.update(
                {
                    str(key): value
                    for key, value in skipped_raw.items()
                    if isinstance(value, int) and value >= 0
                }
            )
        return cls(
            scanned=count("scanned"),
            accepted=count("accepted"),
            skipped=count("skipped"),
            duplicates=count("duplicates"),
            errors=count("errors"),
            reencoded_fallbacks=count("reencoded_fallbacks"),
            synchronized=count("synchronized"),
            accepted_by_label=labels,
            skipped_by_reason=skipped_reasons,
        )


@dataclass
class KaggleState:
    created: bool = False
    successful_syncs: int = 0
    last_successful_sync: str | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "successful_syncs": self.successful_syncs,
            "last_successful_sync": self.last_successful_sync,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> KaggleState:
        if not isinstance(raw, Mapping):
            return cls()
        syncs = raw.get("successful_syncs", 0)
        return cls(
            created=raw.get("created") is True,
            successful_syncs=syncs if isinstance(syncs, int) and syncs >= 0 else 0,
            last_successful_sync=(
                raw.get("last_successful_sync")
                if isinstance(raw.get("last_successful_sync"), str)
                else None
            ),
            last_error=(raw.get("last_error") if isinstance(raw.get("last_error"), str) else None),
        )


class ManifestStore:
    """Durable append-only records plus atomic synchronization-status updates."""

    def __init__(self, output: Path) -> None:
        self.path = output / MANIFEST_NAME
        self.errors_path = output / ERRORS_NAME
        self.known_hashes: set[str] = set()
        self.known_sample_ids: set[str] = set()
        self.unsynchronized_hashes: set[str] = set()
        self.synchronized_hashes: set[str] = set()
        self.accepted_by_label: Counter[str] = Counter()
        self.reencoded_fallbacks = 0

    @property
    def accepted_count(self) -> int:
        return len(self.known_hashes)

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, Mapping):
                        raise ResumeError(f"manifest row {line_number} is not an object")
                    content_hash = record.get("content_hash")
                    label = record.get("normalized_label")
                    if not isinstance(content_hash, str) or not isinstance(label, str):
                        raise ResumeError(f"manifest row {line_number} lacks identity fields")
                    if content_hash in self.known_hashes:
                        raise ResumeError(f"manifest row {line_number} repeats a content hash")
                    self.known_hashes.add(content_hash)
                    self.accepted_by_label[label] += 1
                    if str(record.get("byte_source", "")).startswith("pillow_reencoded_"):
                        self.reencoded_fallbacks += 1
                    sample_id = record.get("sample_id")
                    if isinstance(sample_id, str) and sample_id:
                        if sample_id in self.known_sample_ids:
                            raise ResumeError(f"manifest row {line_number} repeats a sample ID")
                        self.known_sample_ids.add(sample_id)
                    if record.get("kaggle_synchronized") is True:
                        self.synchronized_hashes.add(content_hash)
                    else:
                        self.unsynchronized_hashes.add(content_hash)
        except (OSError, json.JSONDecodeError) as exc:
            raise ResumeError("manifest could not be loaded safely") from exc

    def append(self, record: Mapping[str, Any]) -> None:
        content_hash = str(record["content_hash"])
        sample_id = record.get("sample_id")
        label = str(record["normalized_label"])
        append_jsonl(self.path, record)
        self.known_hashes.add(content_hash)
        self.unsynchronized_hashes.add(content_hash)
        self.accepted_by_label[label] += 1
        if str(record.get("byte_source", "")).startswith("pillow_reencoded_"):
            self.reencoded_fallbacks += 1
        if isinstance(sample_id, str) and sample_id:
            self.known_sample_ids.add(sample_id)

    def append_error(
        self,
        *,
        category: str,
        error_type: str,
        stream_position: int | None,
        message: str,
    ) -> None:
        append_jsonl(
            self.errors_path,
            {
                "timestamp": utc_now(),
                "category": category,
                "error_type": error_type,
                "stream_position": stream_position,
                "message": message,
            },
        )

    def mark_synchronized(self, hashes: set[str]) -> None:
        """Atomically rewrite status only after a successful Kaggle command."""
        hashes = hashes & self.unsynchronized_hashes
        if not hashes:
            return
        temporary: Path | None = None
        try:
            with (
                self.path.open("r", encoding="utf-8") as source,
                tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as destination,
            ):
                temporary = Path(destination.name)
                for line in source:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("content_hash") in hashes:
                        record["kaggle_synchronized"] = True
                    destination.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                    destination.write("\n")
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.unsynchronized_hashes.difference_update(hashes)
        self.synchronized_hashes.update(hashes)


class RuntimeStore:
    """Own atomic checkpoint and summary persistence."""

    def __init__(self, output: Path, fingerprint: str) -> None:
        self.output = output
        self.fingerprint = fingerprint
        self.checkpoint_path = output / CHECKPOINT_NAME
        self.summary_path = output / SUMMARY_NAME

    def load_checkpoint(self) -> Mapping[str, Any] | None:
        if not self.checkpoint_path.exists():
            return None
        try:
            with self.checkpoint_path.open("r", encoding="utf-8") as handle:
                checkpoint = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ResumeError("checkpoint could not be loaded safely") from exc
        if not isinstance(checkpoint, Mapping):
            raise ResumeError("checkpoint is not a JSON object")
        if checkpoint.get("version") != CHECKPOINT_VERSION:
            raise ResumeError("checkpoint version is not supported")
        if checkpoint.get("source_fingerprint") != self.fingerprint:
            raise ResumeError("checkpoint source configuration is incompatible")
        return checkpoint

    def save_checkpoint(
        self,
        *,
        source_state: Mapping[str, Any] | None,
        counters: Counters,
        kaggle_state: KaggleState,
        resolved_revision: str | None,
    ) -> None:
        atomic_write_json(
            self.checkpoint_path,
            {
                "version": CHECKPOINT_VERSION,
                "updated_at": utc_now(),
                "source_fingerprint": self.fingerprint,
                "source_state": source_state,
                "resolved_revision": resolved_revision,
                "counters": counters.as_dict(),
                "kaggle_publishing": kaggle_state.as_dict(),
                "last_successful_kaggle_sync": kaggle_state.last_successful_sync,
            },
        )

    def save_summary(
        self,
        *,
        config: AppConfig,
        counters: Counters,
        kaggle_state: KaggleState,
        resolved_revision: str | None,
        publishing_enabled: bool,
        started_at: str,
        exit_reason: str,
    ) -> None:
        atomic_write_json(
            self.summary_path,
            {
                "updated_at": utc_now(),
                "started_at": started_at,
                "exit_reason": exit_reason,
                "source": {
                    "provider": config.provider,
                    "dataset": config.dataset.dataset_id,
                    "requested_revision": config.dataset.revision,
                    "resolved_revision": resolved_revision,
                    "split": config.dataset.split,
                },
                "target": config.collection.target,
                "max_source_records": config.collection.max_source_records,
                "quotas": config.collection.quotas,
                "counters": counters.as_dict(),
                "publishing_enabled": publishing_enabled,
                "kaggle": kaggle_state.as_dict(),
            },
        )


def validate_output_directory(output: Path, resume: bool) -> None:
    """Refuse overwrite or accidental upload of unrelated local content."""
    if not output.exists():
        return
    if not output.is_dir():
        raise ResumeError("output exists but is not a directory")
    entries = list(output.iterdir())
    unknown = [entry.name for entry in entries if entry.name not in RUNTIME_ENTRIES]
    if unknown:
        raise ResumeError("output contains entries not owned by this collector")
    if not resume and entries:
        raise ResumeError("--no-resume requires an empty output directory")


def reconcile_counters(counters: Counters, manifest: ManifestStore) -> None:
    """Treat the flushed manifest as authoritative after a hard interruption."""
    counters.accepted = manifest.accepted_count
    counters.accepted_by_label = Counter(manifest.accepted_by_label)
    counters.reencoded_fallbacks = max(
        counters.reencoded_fallbacks,
        manifest.reencoded_fallbacks,
    )
    counters.synchronized = len(manifest.synchronized_hashes)


def source_sample_id(value: Any | None) -> str | None:
    if value is None:
        return None
    candidate = str(safe_scalar(value, maximum_length=1_024)).strip()
    return candidate[:1_024] or None


# 7. Kaggle publishing


class KagglePublisher:
    """Publish and verify complete snapshots through the Kaggle CLI."""

    def __init__(
        self,
        output: Path,
        config: KaggleConfig,
        retry: RetryConfig,
        errors: ManifestStore,
    ) -> None:
        self.output = output
        self.config = config
        # Source reads use the configured retry policy, but remote publication is
        # intentionally one-shot. Retrying an ambiguous create/version operation
        # could publish more than once.
        del retry
        self.errors = errors

    def _write_metadata(self) -> None:
        atomic_write_json(
            self.output / KAGGLE_METADATA_NAME,
            {
                "id": self.config.dataset_id,
                "title": self.config.title,
                "licenses": [{"name": self.config.license_name}],
                "description": self.config.license_description,
            },
        )

    def _command(self, state: KaggleState) -> list[str]:
        if state.created:
            return [
                "kaggle",
                "datasets",
                "version",
                "--path",
                str(self.output),
                "--message",
                f"SensiFake sync {utc_now()}",
                "--dir-mode",
                "zip",
            ]
        # Kaggle dataset creation is private by default; no public flag is passed.
        return [
            "kaggle",
            "datasets",
            "create",
            "--path",
            str(self.output),
            "--dir-mode",
            "zip",
        ]

    def _expected_remote_resources(self) -> set[str]:
        """Return the exact resource names produced by the fixed zip dir mode."""
        resources: set[str] = set()
        for entry in self.output.iterdir():
            if entry.name == KAGGLE_METADATA_NAME:
                continue
            resources.add(f"{entry.name}.zip" if entry.is_dir() else entry.name)
        return resources

    def _run_verification_command(
        self,
        command: list[str],
        deadline: float,
    ) -> subprocess.CompletedProcess[str]:
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise RemoteVerificationError("verification deadline exhausted")
        timeout = max(1.0, min(self.config.subprocess_timeout_seconds, remaining))
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RemoteVerificationError("verification command timed out") from exc
        except OSError as exc:
            raise RemoteVerificationError("verification command could not execute") from exc
        if result.returncode != 0:
            raise RemoteVerificationError("verification command failed")
        return result

    @staticmethod
    def _json_object(raw: str, description: str) -> Mapping[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteVerificationError(f"{description} was not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise RemoteVerificationError(f"{description} was not a JSON object")
        return value

    @staticmethod
    def _resource_names(raw: Any, description: str) -> set[str]:
        if not isinstance(raw, list):
            raise RemoteVerificationError(f"{description} was not a JSON array")
        names: list[str] = []
        for item in raw:
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                raise RemoteVerificationError(f"{description} contained an invalid resource")
            names.append(item["name"])
        if len(names) != len(set(names)):
            raise RemoteVerificationError(f"{description} contained duplicate resources")
        return set(names)

    def verify_remote(self, deadline: float) -> None:
        """Fail closed unless identity, privacy, readiness, and files all agree."""
        owner, slug = self.config.dataset_id.split("/", maxsplit=1)
        expected_resources = self._expected_remote_resources()
        if not expected_resources:
            raise RemoteVerificationError("local publication has no resources")

        try:
            with tempfile.TemporaryDirectory(prefix="sensifake-kaggle-metadata-") as directory:
                metadata_directory = Path(directory)
                self._run_verification_command(
                    [
                        "kaggle",
                        "datasets",
                        "metadata",
                        self.config.dataset_id,
                        "--path",
                        str(metadata_directory),
                    ],
                    deadline,
                )
                metadata_path = metadata_directory / KAGGLE_METADATA_NAME
                try:
                    with metadata_path.open("r", encoding="utf-8") as handle:
                        metadata = json.load(handle)
                except (OSError, json.JSONDecodeError) as exc:
                    raise RemoteVerificationError("remote metadata could not be read") from exc
        except OSError as exc:
            raise RemoteVerificationError("temporary metadata directory could not be used") from exc

        if not isinstance(metadata, Mapping):
            raise RemoteVerificationError("remote metadata was not a JSON object")
        if metadata.get("ownerUser") != owner or metadata.get("datasetSlug") != slug:
            raise RemoteVerificationError("remote dataset identity did not match")
        if metadata.get("isPrivate") is not True:
            raise RemoteVerificationError("remote dataset was not private")
        metadata_resources = self._resource_names(metadata.get("data"), "remote metadata")
        if metadata_resources != expected_resources:
            raise RemoteVerificationError("remote metadata resources did not match")

        files_result = self._run_verification_command(
            [
                "kaggle",
                "datasets",
                "files",
                self.config.dataset_id,
                "--format",
                "json",
                "--page-size",
                "200",
            ],
            deadline,
        )
        try:
            files = json.loads(files_result.stdout)
        except json.JSONDecodeError as exc:
            raise RemoteVerificationError("remote file listing was not valid JSON") from exc
        listed_resources = self._resource_names(files, "remote file listing")
        if listed_resources != expected_resources:
            raise RemoteVerificationError("remote file listing did not match")

        status_result = self._run_verification_command(
            [
                "kaggle",
                "datasets",
                "status",
                self.config.dataset_id,
                "--format",
                "json",
            ],
            deadline,
        )
        status = self._json_object(status_result.stdout, "remote status")
        version = status.get("current_version_number")
        if status.get("status") != "ready":
            raise RemoteVerificationError("remote dataset version was not ready")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise RemoteVerificationError("remote dataset version was invalid")

    def synchronize(self, state: KaggleState, deadline: float) -> bool:
        """Return true only after one upload and fail-closed remote verification."""
        self._write_metadata()
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            state.last_error = "insufficient runtime for Kaggle synchronization"
            return False
        timeout = max(1.0, min(self.config.subprocess_timeout_seconds, remaining))
        try:
            result = subprocess.run(
                self._command(state),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            succeeded = result.returncode == 0
            error_type = f"exit_{result.returncode}"
        except subprocess.TimeoutExpired:
            succeeded = False
            error_type = "timeout"
        except OSError:
            succeeded = False
            error_type = "execution_error"

        if not succeeded:
            state.last_error = f"Kaggle synchronization failed ({error_type})"
            self.errors.append_error(
                category="kaggle_sync",
                error_type=error_type,
                stream_position=None,
                message="Kaggle CLI synchronization failed; command output was not retained",
            )
            return False

        try:
            self.verify_remote(deadline)
        except RemoteVerificationError as exc:
            error_type = type(exc).__name__
            state.last_error = "Kaggle remote verification failed"
            self.errors.append_error(
                category="kaggle_remote_verification",
                error_type=error_type,
                stream_position=None,
                message=str(exc),
            )
            return False

        state.created = True
        state.successful_syncs += 1
        state.last_successful_sync = utc_now()
        state.last_error = None
        return True


# 8. Collection loop


class ShutdownController:
    """Convert termination signals into a loop-visible graceful-stop request."""

    def __init__(self) -> None:
        self.requested = False
        self.reason = "signal"

    def install(self) -> None:
        def request_stop(signum: int, _frame: Any) -> None:
            self.requested = True
            self.reason = signal.Signals(signum).name.casefold()
            LOGGER.warning("Shutdown requested by %s", self.reason)

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)


def _postfix(counters: Counters, labels: tuple[str, ...]) -> dict[str, int]:
    values = {
        "scanned": counters.scanned,
        "accepted": counters.accepted,
    }
    values.update({label: counters.accepted_by_label.get(label, 0) for label in labels})
    values.update(
        {
            "skipped": counters.skipped,
            "duplicates": counters.duplicates,
            "errors": counters.errors,
            "reencoded_fallbacks": counters.reencoded_fallbacks,
            "synchronized": counters.synchronized,
        }
    )
    return values


def _collection_complete(config: AppConfig, counters: Counters) -> str | None:
    if counters.accepted >= config.collection.target:
        return "target_reached"
    if all(
        counters.accepted_by_label.get(label, 0) >= quota
        for label, quota in config.collection.quotas.items()
    ):
        return "quotas_reached"
    return None


def _source_state(source: StreamingSource) -> dict[str, Any] | None:
    try:
        return safe_source_state(source.state_dict())
    except Exception:  # noqa: BLE001 -- provider state hooks are third-party boundaries
        LOGGER.warning("Provider checkpoint state could not be captured")
        return None


def _process_record(
    *,
    record: Mapping[str, Any],
    stream_position: int,
    source: StreamingSource,
    adapter: SourceAdapter,
    config: AppConfig,
    output: Path,
    manifest: ManifestStore,
    counters: Counters,
) -> None:
    dataset = config.dataset
    try:
        example = adapter.normalize(record, decode_label=source.decode_label)
    except MissingSourceFieldError as exc:
        counters.skipped += 1
        reason = "missing_image" if exc.field_name == adapter.image_field else "missing_label"
        counters.skipped_by_reason[reason] += 1
        manifest.append_error(
            category=reason,
            error_type="MissingField",
            stream_position=stream_position,
            message=f"required {exc.field_name} field is absent",
        )
        return

    original_label = safe_scalar(example.original_label, maximum_length=1_024)
    label = example.normalized_label
    if label is None:
        counters.skipped += 1
        counters.skipped_by_reason[example.skip_reason or "unsupported_label"] += 1
        return
    if label not in dataset.accepted_labels:
        raise SourceConfigurationError(
            f"adapter {adapter.name} produced an unsupported canonical label: {label}"
        )
    if counters.accepted_by_label[label] >= config.collection.quotas[label]:
        counters.skipped += 1
        counters.skipped_by_reason[f"quota_{label}_reached"] += 1
        return

    sample_id = source_sample_id(example.source_id)
    if sample_id is not None and sample_id in manifest.known_sample_ids:
        counters.duplicates += 1
        return

    try:
        image = validate_image(
            example.image,
            allow_reencoding=not source.requires_original_encoded_bytes,
        )
    except ImageValidationError as exc:
        counters.errors += 1
        manifest.append_error(
            category="invalid_image",
            error_type=type(exc).__name__,
            stream_position=stream_position,
            message="image failed encoded-byte validation",
        )
        return
    if image.byte_source.startswith("pillow_reencoded_"):
        counters.reencoded_fallbacks += 1
    if image.sha256 in manifest.known_hashes:
        counters.duplicates += 1
        return

    relative_path = persist_image(output, label, image)
    if set(example.metadata) & MANIFEST_RESERVED_FIELDS:
        raise SourceConfigurationError("adapter metadata fields collide with manifest fields")
    metadata = {
        field_name: safe_scalar(value) for field_name, value in example.metadata.items()
    }
    manifest_record: dict[str, Any] = {
        "sample_id": sample_id,
        "content_hash": image.sha256,
        "relative_image_path": relative_path.as_posix(),
        "source_dataset": dataset.dataset_id,
        "requested_revision": dataset.revision,
        "resolved_revision": source.resolved_revision,
        "split": dataset.split,
        "stream_position": stream_position,
        "normalized_label": label,
        "original_label": original_label,
        "width": image.width,
        "height": image.height,
        "image_mode": image.mode,
        "image_format": image.image_format,
        "byte_source": image.byte_source,
        "collection_timestamp": utc_now(),
        "kaggle_synchronized": False,
        "sensitivity_annotation": None,
    }
    manifest_record.update(metadata)
    manifest.append(manifest_record)
    counters.accepted += 1
    counters.accepted_by_label[label] += 1


def collect(
    config: AppConfig,
    output: Path,
    *,
    publish_kaggle: bool,
    resume: bool,
    shutdown: ShutdownController,
) -> tuple[str, Counters]:
    """Run provider-independent collection until a defined exit condition."""
    from tqdm import tqdm

    validate_output_directory(output, resume)
    output.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    deadline = time.monotonic() + config.collection.max_runtime_minutes * 60
    safety_deadline = deadline - config.collection.shutdown_safety_buffer_seconds

    manifest = ManifestStore(output)
    manifest.load()
    runtime = RuntimeStore(output, config.source_fingerprint())
    checkpoint = runtime.load_checkpoint() if resume else None
    counters = Counters.from_dict(checkpoint.get("counters") if checkpoint else None)
    kaggle_state = KaggleState.from_dict(
        checkpoint.get("kaggle_publishing") if checkpoint else None
    )
    if checkpoint and counters.accepted > 0 and not manifest.path.exists():
        raise ResumeError("checkpoint records accepted images but manifest is missing")
    reconcile_counters(counters, manifest)
    saved_resolved_revision = (
        checkpoint.get("resolved_revision")
        if checkpoint and isinstance(checkpoint.get("resolved_revision"), str)
        else None
    )
    checkpoint_state = checkpoint.get("source_state") if checkpoint else None
    if checkpoint_state is not None and not isinstance(checkpoint_state, Mapping):
        raise ResumeError("checkpoint source state is invalid")

    try:
        adapter = create_adapter(config.adapter_name, config.adapter_options)
    except AdapterConfigurationError as exc:
        raise ConfigurationError(str(exc)) from exc
    source = create_source(config, adapter)
    try:
        open_source_with_retries(source, checkpoint_state, config.retry, manifest, deadline)
    except (SourceUnavailable, SourceConfigurationError) as exc:
        failure_reason = (
            "source_configuration_error"
            if isinstance(exc, SourceConfigurationError)
            else "source_retry_exhausted"
        )
        runtime.save_checkpoint(
            source_state=(
                dict(checkpoint_state) if isinstance(checkpoint_state, Mapping) else None
            ),
            counters=counters,
            kaggle_state=kaggle_state,
            resolved_revision=saved_resolved_revision,
        )
        runtime.save_summary(
            config=config,
            counters=counters,
            kaggle_state=kaggle_state,
            resolved_revision=saved_resolved_revision,
            publishing_enabled=publish_kaggle,
            started_at=started_at,
            exit_reason=failure_reason,
        )
        raise
    if (
        saved_resolved_revision
        and source.resolved_revision
        and saved_resolved_revision != source.resolved_revision
    ):
        raise ResumeError("resolved source revision changed since the checkpoint")
    resolved_revision = source.resolved_revision or saved_resolved_revision
    safe_resume_state = _source_state(source) or (
        dict(checkpoint_state) if isinstance(checkpoint_state, Mapping) else None
    )

    publisher = KagglePublisher(output, config.kaggle, config.retry, manifest)
    exit_reason = "running"
    progress = tqdm(
        total=config.collection.target,
        initial=min(counters.accepted, config.collection.target),
        unit="image",
        desc="collecting",
        dynamic_ncols=True,
    )
    progress.set_postfix(_postfix(counters, config.dataset.accepted_labels), refresh=True)

    def save_runtime(reason: str) -> None:
        runtime.save_checkpoint(
            source_state=safe_resume_state,
            counters=counters,
            kaggle_state=kaggle_state,
            resolved_revision=resolved_revision,
        )
        runtime.save_summary(
            config=config,
            counters=counters,
            kaggle_state=kaggle_state,
            resolved_revision=resolved_revision,
            publishing_enabled=publish_kaggle,
            started_at=started_at,
            exit_reason=reason,
        )

    def synchronize() -> bool:
        if not publish_kaggle or not manifest.unsynchronized_hashes:
            return True
        pending_hashes = set(manifest.unsynchronized_hashes)
        save_runtime("kaggle_sync_in_progress")
        if not publisher.synchronize(kaggle_state, deadline):
            save_runtime("kaggle_sync_failed")
            return False
        manifest.mark_synchronized(pending_hashes)
        counters.synchronized = len(manifest.synchronized_hashes)
        save_runtime("running")
        progress.set_postfix(_postfix(counters, config.dataset.accepted_labels), refresh=True)
        return True

    try:
        complete_reason = _collection_complete(config, counters)
        if complete_reason:
            exit_reason = complete_reason
        elif publish_kaggle and resume and manifest.unsynchronized_hashes and not synchronize():
            exit_reason = "kaggle_sync_failed"

        source_failures = 0
        while exit_reason == "running":
            complete_reason = _collection_complete(config, counters)
            if complete_reason:
                exit_reason = complete_reason
                break
            if shutdown.requested:
                exit_reason = f"shutdown_{shutdown.reason}"
                break
            if time.monotonic() >= safety_deadline:
                exit_reason = "runtime_safety_buffer"
                break
            if (
                config.collection.max_source_records is not None
                and counters.scanned >= config.collection.max_source_records
            ):
                exit_reason = "source_record_limit"
                break

            pre_record_state = safe_resume_state
            try:
                record = source.next_record()
                source_failures = 0
            except StopIteration:
                exit_reason = "source_exhausted"
                break
            except (SourceConfigurationError, OriginalBytesUnavailable) as exc:
                counters.errors += 1
                exit_reason = (
                    "source_configuration_error"
                    if isinstance(exc, SourceConfigurationError)
                    else "original_bytes_unavailable"
                )
                manifest.append_error(
                    category=exit_reason,
                    error_type=type(exc).__name__,
                    stream_position=counters.scanned,
                    message="source could not provide guaranteed original encoded bytes",
                )
                LOGGER.error("Collection stopped: %s", exit_reason)
                break
            except Exception as exc:  # noqa: BLE001 -- source implementations are third-party
                counters.errors += 1
                manifest.append_error(
                    category="source_read",
                    error_type=type(exc).__name__,
                    stream_position=counters.scanned,
                    message="stream read failed",
                )
                if source_failures >= config.retry.count:
                    exit_reason = "source_retry_exhausted"
                    break
                delay = min(
                    config.retry.initial_backoff_seconds * (2**source_failures),
                    config.retry.maximum_backoff_seconds,
                )
                source_failures += 1
                LOGGER.warning("Stream read failed; recreating source after %.1f seconds", delay)
                if not sleep_with_deadline(delay, safety_deadline):
                    exit_reason = "runtime_safety_buffer"
                    break
                try:
                    open_source_with_retries(
                        source,
                        pre_record_state,
                        config.retry,
                        manifest,
                        safety_deadline,
                    )
                except SourceConfigurationError:
                    exit_reason = "source_configuration_error"
                    LOGGER.error("Collection stopped: %s", exit_reason)
                    continue
                except SourceUnavailable:
                    exit_reason = "source_retry_exhausted"
                    continue
                if (
                    resolved_revision
                    and source.resolved_revision
                    and resolved_revision != source.resolved_revision
                ):
                    exit_reason = "source_revision_changed"
                    continue
                resolved_revision = source.resolved_revision or resolved_revision
                continue

            counters.scanned += 1
            try:
                _process_record(
                    record=record,
                    stream_position=counters.scanned,
                    source=source,
                    adapter=adapter,
                    config=config,
                    output=output,
                    manifest=manifest,
                    counters=counters,
                )
            except OriginalBytesUnavailable as exc:
                counters.errors += 1
                exit_reason = "original_bytes_unavailable"
                manifest.append_error(
                    category=exit_reason,
                    error_type=type(exc).__name__,
                    stream_position=counters.scanned,
                    message="recognized image feature did not expose original encoded bytes",
                )
                LOGGER.error("Collection stopped: %s", exit_reason)
                break
            progress.n = min(counters.accepted, config.collection.target)
            progress.set_postfix(_postfix(counters, config.dataset.accepted_labels), refresh=True)

            # Advance the resumable cursor only after all durable record effects finish.
            captured_state = _source_state(source)
            if captured_state is not None:
                safe_resume_state = captured_state
            if counters.scanned % config.collection.checkpoint_interval == 0:
                save_runtime("running")
            if (
                publish_kaggle
                and len(manifest.unsynchronized_hashes) >= config.kaggle.sync_every
                and not synchronize()
            ):
                exit_reason = "kaggle_sync_failed"
                break
    except KeyboardInterrupt:
        exit_reason = "shutdown_keyboard_interrupt"
    finally:
        try:
            if (
                publish_kaggle
                and manifest.unsynchronized_hashes
                and exit_reason != "kaggle_sync_failed"
                and not synchronize()
            ):
                exit_reason = "kaggle_sync_failed"
            save_runtime(exit_reason)
            progress.set_postfix(_postfix(counters, config.dataset.accepted_labels), refresh=True)
        finally:
            try:
                progress.close()
            finally:
                source.close()

    return exit_reason, counters


# 9. Command-line parsing and main entry point


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Progressively collect validated images from a streaming dataset."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/sources/openfake.toml"),
        help="TOML configuration path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Collector-owned output directory",
    )
    parser.add_argument("--max-samples", type=int, help="Override the accepted-image target")
    parser.add_argument(
        "--quota",
        action="append",
        default=[],
        metavar="LABEL=COUNT",
        help="Override one accepted-label quota; may be repeated",
    )
    parser.add_argument(
        "--max-source-records",
        type=int,
        help="Stop after examining this many source records",
    )
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        help="Override maximum wall-clock runtime",
    )
    parser.add_argument(
        "--sync-every",
        type=int,
        help="Override accepted images between Kaggle synchronizations",
    )
    parser.add_argument(
        "--publish-kaggle",
        action="store_true",
        help="Explicitly enable private Kaggle Dataset synchronization",
    )
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument("--resume", dest="resume", action="store_true")
    resume_group.add_argument("--no-resume", dest="resume", action="store_false")
    parser.set_defaults(resume=None)
    return parser.parse_args(argv)


def apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    collection = config.collection
    kaggle = config.kaggle
    if args.max_samples is not None:
        if args.max_samples <= 0:
            raise ConfigurationError("--max-samples must be positive")
        collection = replace(collection, target=args.max_samples)
    if args.quota:
        quotas = dict(collection.quotas)
        seen_labels: set[str] = set()
        for raw_quota in args.quota:
            label, separator, raw_count = raw_quota.partition("=")
            normalized_label = label.strip().casefold()
            if separator != "=" or normalized_label not in quotas:
                raise ConfigurationError("--quota must use a configured LABEL=COUNT")
            if normalized_label in seen_labels:
                raise ConfigurationError("--quota repeats a label")
            seen_labels.add(normalized_label)
            try:
                count = int(raw_count)
            except ValueError as exc:
                raise ConfigurationError("--quota count must be an integer") from exc
            if count < 0:
                raise ConfigurationError("--quota count must be non-negative")
            quotas[normalized_label] = count
        collection = replace(collection, quotas=quotas)
    if args.max_source_records is not None:
        if args.max_source_records <= 0:
            raise ConfigurationError("--max-source-records must be positive")
        collection = replace(collection, max_source_records=args.max_source_records)
    if args.max_runtime_minutes is not None:
        if args.max_runtime_minutes <= 0:
            raise ConfigurationError("--max-runtime-minutes must be positive")
        collection = replace(collection, max_runtime_minutes=args.max_runtime_minutes)
    if args.sync_every is not None:
        if args.sync_every <= 0:
            raise ConfigurationError("--sync-every must be positive")
        kaggle = replace(kaggle, sync_every=args.sync_every)
    overridden = replace(config, collection=collection, kaggle=kaggle)
    validate_config(overridden)
    return overridden


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)
    try:
        config = apply_cli_overrides(load_config(args.config), args)
        resume = config.collection.resume if args.resume is None else args.resume
        shutdown = ShutdownController()
        shutdown.install()
        exit_reason, counters = collect(
            config,
            args.output,
            publish_kaggle=args.publish_kaggle,
            resume=resume,
            shutdown=shutdown,
        )
    except (
        ConfigurationError,
        ResumeError,
        SourceConfigurationError,
        SourceUnavailable,
    ) as exc:
        LOGGER.error("Collector stopped: %s", exc)
        return 2
    except OSError as exc:
        LOGGER.error("Collector stopped after a local I/O failure (%s)", type(exc).__name__)
        return 2

    label_summary = tuple(
        f"{label}={counters.accepted_by_label.get(label, 0)}"
        for label in config.dataset.accepted_labels
    )
    print(
        " ".join(
            (
                f"exit_reason={exit_reason}",
                f"scanned={counters.scanned}",
                f"accepted={counters.accepted}",
                *label_summary,
                f"duplicates={counters.duplicates}",
                f"errors={counters.errors}",
                "skipped_by_reason="
                + json.dumps(counters.skipped_by_reason, sort_keys=True, separators=(",", ":")),
                f"reencoded_fallbacks={counters.reencoded_fallbacks}",
                f"synchronized={counters.synchronized}",
            )
        )
    )
    failures = {
        "kaggle_sync_failed",
        "original_bytes_unavailable",
        "source_configuration_error",
        "source_retry_exhausted",
        "source_revision_changed",
    }
    return 2 if exit_reason in failures else 0


if __name__ == "__main__":
    sys.exit(main())
