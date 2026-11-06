"""Offline resolver tests; fixtures are synthetic and contain no dataset images."""
import base64
import csv
import hashlib
import io

import pytest

from sensifake_data import IntegrityError, PublishedDataset, published

PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture
def corpus(monkeypatch):
    stream = io.StringIO()
    fields = ["image_id", "sha256", "image_path", "source_original_path", "source_original_paths_json"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for i in range(4499):
        h = hashlib.sha256(PIXEL if i == 0 else str(i).encode()).hexdigest()
        writer.writerow({"image_id": h, "sha256": h, "image_path": f"images/{h}.png",
                         "source_original_path": f"original/{i}", "source_original_paths_json": "[]"})
    data = stream.getvalue().encode()
    monkeypatch.setitem(published.METADATA_SHA256, "metadata/sensifake_all.csv",
                        hashlib.sha256(data).hexdigest())
    return PublishedDataset(manifest_bytes=data)


def test_tampered_metadata_rejected():
    with pytest.raises(IntegrityError):
        PublishedDataset(manifest_bytes=b"tampered")


def test_stable_alias_and_conflict(corpus):
    row = corpus.record_for("original/0")
    assert corpus.record_for(row["sha256"]) == row
    with pytest.raises(IntegrityError):
        corpus.record_for({"sha256": "0" * 64, "image_path": row["image_path"]})
    with pytest.raises(IntegrityError):
        corpus.record_for("unknown")


def test_image_corruption_fails_before_decode(corpus, monkeypatch):
    monkeypatch.setattr(published, "_fetch", lambda path: b"corrupt")
    with pytest.raises(IntegrityError):
        corpus.load_image("original/0")


def test_job_cache_and_integrity(corpus, monkeypatch):
    calls = []
    def fetch(path):
        calls.append(path)
        return PIXEL
    monkeypatch.setattr(published, "_fetch", fetch)
    with corpus.temporary_cache() as job:
        directory = job._cache_dir
        assert job.load_image("original/0").size == (1, 1)
        assert job.image_bytes("original/0") == PIXEL
        assert len(calls) == 1
        (directory / job.record_for("original/0")["sha256"]).write_bytes(b"changed")
        with pytest.raises(IntegrityError):
            job.image_bytes("original/0")
    assert not directory.exists()


def test_metadata_copy_isolation(corpus):
    row = corpus.record_for("original/0")
    row["image_path"] = "changed"
    assert corpus.record_for("original/0")["image_path"] != "changed"
