"""Exceptions raised by storagekit."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for every error raised by storagekit."""


class ConfigError(StorageError):
    """Required configuration is missing or invalid."""


class MetadataError(StorageError):
    """The metadata database failed or rejected an operation."""


class ProviderError(StorageError):
    """A storage provider (S3, GCS, Azure) failed or is unavailable."""


class ObjectNotFoundError(StorageError):
    """No object exists for the given object_id (or key)."""


class ObjectExpiredError(ObjectNotFoundError):
    """The object's TTL has passed; it is waiting for the next cleanup run."""
