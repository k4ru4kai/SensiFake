"""Image transport only: never construct splits, targets, transforms or results."""

import csv
import hashlib
import io
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

DATASET_ID = "K4ru4k4i/SensiFake"
REVISION = "0804959a6daab0e8041e5120e366580543726905"
BASE_URL = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{REVISION}"
METADATA_SHA256 = {
    "metadata/sensifake_all.csv": "f3fa97806f35c7d8d967e26d31b74095ad2b8e276cf2a0c456f58d5c0d0aa6be",
    "metadata/dataset_statistics.json": "cd01b0389e0abb4813ec357b6b047af431cf5d5fe6e73925f4ca36eef5824057",
}


class IntegrityError(ValueError):
    """The requested identity, metadata or payload differs from the pinned release."""


def _verify(payload, expected):
    if hashlib.sha256(payload).hexdigest() != expected:
        raise IntegrityError(f"SHA-256 mismatch for expected identity {expected}")
    return payload


def _fetch(path):
    # Direct HTTPS bypasses the global Hub/Datasets/Xet cache entirely.
    with urlopen(f"{BASE_URL}/{path}", timeout=90) as response:
        return response.read()


class PublishedDataset:
    """Resolve release IDs, content hashes or unambiguous original-path aliases.

    Metadata retains the exact published CSV bytes and row order. A caller's
    labels, indices, split assignments and transforms are never rewritten here.
    By default all downloads remain in memory. Use ``temporary_cache()`` around
    an entire job to reuse bytes; stop loader workers before leaving its context.
    """

    def __init__(self, *, manifest_bytes=None):
        self.manifest_bytes = _verify(
            _fetch("metadata/sensifake_all.csv") if manifest_bytes is None else manifest_bytes,
            METADATA_SHA256["metadata/sensifake_all.csv"],
        )
        self._rows = tuple(csv.DictReader(io.StringIO(self.manifest_bytes.decode("utf-8"))))
        if len(self._rows) != 4499:
            raise IntegrityError("Unexpected corpus size")
        self._by_hash = {r["sha256"]: r for r in self._rows}
        if len(self._by_hash) != len(self._rows):
            raise IntegrityError("Repeated content identities")
        self._aliases = {}
        for row in self._rows:
            path = PurePosixPath(row["image_path"])
            if path.is_absolute() or ".." in path.parts:
                raise IntegrityError("Unsafe release-relative image path")
            aliases = [row["sha256"], row["image_id"], row["image_path"],
                       row["source_original_path"], *json.loads(row["source_original_paths_json"])]
            for alias in aliases:
                if alias in self._aliases and self._aliases[alias]["sha256"] != row["sha256"]:
                    raise IntegrityError(f"Ambiguous original image identity: {alias}")
                self._aliases[alias] = row
        self._cache_dir = None
        self._metadata = {}

    def record_for(self, identity):
        """Return a copy; unknown identities and conflicting hashes fail closed."""
        if isinstance(identity, str):
            try:
                return self._aliases[identity].copy()
            except KeyError as exc:
                raise IntegrityError(f"Image not in the pinned release: {identity}") from exc
        values = [str(identity[k]) for k in ("sha256", "content_hash", "image_id", "image_path")
                  if k in identity and identity[k] is not None and str(identity[k]) not in {"", "nan"}]
        matches = [self._aliases[v] for v in values if v in self._aliases]
        if not matches or len({r["sha256"] for r in matches}) != 1:
            raise IntegrityError("Unknown or conflicting manifest identities")
        row = matches[0]
        for key in ("sha256", "content_hash"):
            if key in identity and str(identity[key]) != row["sha256"]:
                raise IntegrityError(f"Conflicting {key} in requested row")
        if "image_path" in identity:
            path = str(identity["image_path"])
            # A historical path can be an alias, but not a different release image.
            if path in self._aliases and self._aliases[path]["sha256"] != row["sha256"]:
                raise IntegrityError("Conflicting image path")
        return row.copy()

    def image_bytes(self, identity):
        row = self.record_for(identity)
        cached = self._cache_dir / row["sha256"] if self._cache_dir is not None else None
        if cached is not None and cached.exists():
            return _verify(cached.read_bytes(), row["sha256"])
        payload = _verify(_fetch(row["image_path"]), row["sha256"])
        if cached is not None:
            # Distinct writers can race, but only verified identical bytes are stored.
            with tempfile.NamedTemporaryFile(dir=self._cache_dir, delete=False) as stream:
                staging = Path(stream.name)
                stream.write(payload)
            staging.replace(cached)
        return payload

    def load_image(self, identity, *, exif_transpose=False):
        """Decode RGB; retain the caller's original EXIF behavior explicitly."""
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(self.image_bytes(identity))) as image:
            if exif_transpose:
                image = ImageOps.exif_transpose(image)
            return image.convert("RGB")

    def metadata_bytes(self, path):
        if path not in METADATA_SHA256:
            raise KeyError(f"Metadata is not in the verified allowlist: {path}")
        if path == "metadata/sensifake_all.csv":
            return self.manifest_bytes
        if path not in self._metadata:
            self._metadata[path] = _verify(_fetch(path), METADATA_SHA256[path])
        return self._metadata[path]

    def statistics(self):
        return json.loads(self.metadata_bytes("metadata/dataset_statistics.json"))

    @contextmanager
    def temporary_cache(self):
        """Own and dispose only this newly created job directory, never global caches."""
        with tempfile.TemporaryDirectory(prefix="sensifake-job-") as directory:
            cached = PublishedDataset(manifest_bytes=self.manifest_bytes)
            cached._metadata = self._metadata.copy()
            cached._cache_dir = Path(directory)
            try:
                yield cached
            finally:
                cached._cache_dir = None
