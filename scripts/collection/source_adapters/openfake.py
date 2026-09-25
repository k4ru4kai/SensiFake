"""OpenFake row normalization with the pilot's established semantics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import CanonicalExample, LabelDecoder, MissingSourceFieldError


class OpenFakeAdapter:
    """Normalize ``ComplexDataLab/OpenFake`` rows for binary collection."""

    name = "openfake"
    image_field = "image"
    label_field = "label"

    def normalize(
        self,
        record: Mapping[str, Any],
        *,
        decode_label: LabelDecoder,
    ) -> CanonicalExample:
        image = record.get(self.image_field)
        if image is None:
            raise MissingSourceFieldError(self.image_field)
        original_label = record.get(self.label_field)
        if original_label is None:
            raise MissingSourceFieldError(self.label_field)
        candidate = str(decode_label(original_label)).strip().casefold()
        label = candidate if candidate in {"real", "fake"} else None
        return CanonicalExample(
            image=image,
            source_id=record.get("id"),
            normalized_label=label,
            original_label=original_label,
            metadata={
                "prompt": record.get("prompt"),
                "model": record.get("model"),
            },
            skip_reason=None if label is not None else "unsupported_label",
        )
