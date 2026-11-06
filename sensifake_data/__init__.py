"""Verified access to the published SensiFake corpus, without a permanent cache."""

from .published import DATASET_ID, REVISION, IntegrityError, PublishedDataset

__all__ = ["DATASET_ID", "REVISION", "IntegrityError", "PublishedDataset"]
