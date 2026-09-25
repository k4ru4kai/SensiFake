"""SID-Set native-schema normalization for the future binary core dataset."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import (
    AdapterConfigurationError,
    CanonicalExample,
    LabelDecoder,
    MissingSourceFieldError,
)

CORE_LABEL_MAPPING = {"0": "real", "1": "fake", "2": "skip"}
NATIVE_LABEL_NAMES = {"0": "real", "1": "full_synthetic", "2": "tampered"}


class SidSetAdapter:
    """Normalize ``saberzl/SID_Set`` rows without admitting tampered samples."""

    name = "sid_set"
    image_field = "image"
    label_field = "label"
    encoded_image_fields = ("image", "mask")

    def __init__(self, label_mapping: Mapping[str, Any]) -> None:
        normalized = {str(key): str(value).strip().casefold() for key, value in label_mapping.items()}
        if normalized != CORE_LABEL_MAPPING:
            raise AdapterConfigurationError(
                "SID-Set label_mapping must be exactly 0=real, 1=fake, 2=skip"
            )
        self.label_mapping = normalized

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

        scalar = getattr(original_label, "item", None)
        native_label = scalar() if callable(scalar) else original_label
        label_key = str(native_label).strip()
        mapped = self.label_mapping.get(label_key)
        normalized_label = mapped if mapped in {"real", "fake"} else None
        native_name = NATIVE_LABEL_NAMES.get(label_key, str(decode_label(original_label)))
        mask = record.get("mask")
        return CanonicalExample(
            image=image,
            source_id=record.get("img_id"),
            normalized_label=normalized_label,
            original_label=original_label,
            metadata={
                "sid_set_label": native_label,
                "sid_set_label_name": native_name,
                "mask_available": mask is not None,
                "source_width": record.get("width"),
                "source_height": record.get("height"),
            },
            auxiliary_metadata={
                "mask": mask,
                "native_label": native_label,
                "native_label_name": native_name,
            },
            skip_reason=(
                "tampered"
                if label_key == "2"
                else None if normalized_label is not None else "unsupported_label"
            ),
        )
