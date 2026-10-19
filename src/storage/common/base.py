"""The contract every storage provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import BinaryIO


class StorageProvider(ABC):
    """A place that can hold objects by key (S3, GCS, Azure Blob, ...).

    Implementations translate their SDK's errors into ``ObjectNotFoundError``
    and ``ProviderError`` so callers never see SDK exception types.
    """

    @abstractmethod
    def upload(self, fileobj: BinaryIO, key: str, content_type: str) -> None:
        """Store the bytes read from ``fileobj`` under ``key``."""

    @abstractmethod
    def download_to(self, key: str, fileobj: BinaryIO) -> None:
        """Write the object's bytes into ``fileobj``.

        Raises ``ObjectNotFoundError`` if the key does not exist.
        """

    @abstractmethod
    def iter_chunks(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Yield the object's bytes in chunks.

        Raises ``ObjectNotFoundError`` (on first iteration) if the key is missing.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete the object. Deleting a key that does not exist is not an error."""

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally not abstract
        """Release any resources held by the provider."""
