"""Narrow source-adapter interface for canonical collector records."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

LabelDecoder = Callable[[Any], Any]


class AdapterConfigurationError(ValueError):
    """Raised when source-specific adapter settings are invalid."""


class MissingSourceFieldError(ValueError):
    """Raised when a source row lacks a field required by its adapter."""

    def __init__(self, field_name: str) -> None:
        super().__init__(f"required source field is absent: {field_name}")
        self.field_name = field_name


@dataclass(frozen=True)
class CanonicalExample:
    """Source-independent record consumed by the shared collector."""

    image: Any
    source_id: Any | None
    normalized_label: str | None
    original_label: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)
    auxiliary_metadata: Mapping[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None


class SourceAdapter(Protocol):
    """Small boundary between native dataset rows and collector semantics."""

    name: str
    image_field: str
    label_field: str

    def normalize(
        self,
        record: Mapping[str, Any],
        *,
        decode_label: LabelDecoder,
    ) -> CanonicalExample: ...
