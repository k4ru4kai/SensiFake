"""Source-adapter selection for the shared streaming collector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import (
    AdapterConfigurationError,
    CanonicalExample,
    MissingSourceFieldError,
    SourceAdapter,
)
from .openfake import OpenFakeAdapter
from .sid_set import SidSetAdapter


def create_adapter(name: str, options: Mapping[str, Any]) -> SourceAdapter:
    """Select an adapter explicitly by its configured name."""
    normalized = name.strip().casefold()
    if normalized == "openfake":
        if options:
            raise AdapterConfigurationError("OpenFake adapter does not accept options")
        return OpenFakeAdapter()
    if normalized == "sid_set":
        label_mapping = options.get("label_mapping")
        if not isinstance(label_mapping, Mapping):
            raise AdapterConfigurationError("SID-Set adapter requires [adapter.label_mapping]")
        unknown = set(options) - {"label_mapping"}
        if unknown:
            raise AdapterConfigurationError(
                f"unsupported SID-Set adapter options: {', '.join(sorted(unknown))}"
            )
        return SidSetAdapter(label_mapping)
    raise AdapterConfigurationError(f"unsupported source adapter: {name}")


__all__ = [
    "AdapterConfigurationError",
    "CanonicalExample",
    "MissingSourceFieldError",
    "OpenFakeAdapter",
    "SidSetAdapter",
    "SourceAdapter",
    "create_adapter",
]
