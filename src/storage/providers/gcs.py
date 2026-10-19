"""Google Cloud Storage. Needs the extra: ``pip install "storagekit[gcs]"``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

from ..common.base import StorageProvider
from ..common.exceptions import ObjectNotFoundError, ProviderError


class GCSProvider(StorageProvider):
    def __init__(
        self,
        bucket: str,
        *,
        project: str | None = None,
        credentials_file: str | None = None,
        client: Any | None = None,
    ) -> None:
        """
        Args:
            bucket: Bucket name.
            project: Google Cloud project id (optional).
            credentials_file: Path to a service-account JSON key. Omit to use
                Application Default Credentials.
            client: An existing ``google.cloud.storage.Client`` (mostly for tests).
        """
        try:
            from google.api_core import exceptions as gexc
            from google.cloud import storage as gcs
        except ImportError as e:
            raise ProviderError(
                'GCS support is not installed: pip install "storagekit[gcs]"'
            ) from e

        self._not_found: type[Exception] = gexc.NotFound
        self._api_error: type[Exception] = gexc.GoogleAPIError

        if client is None:
            if credentials_file:
                client = gcs.Client.from_service_account_json(
                    credentials_file, project=project
                )
            else:
                client = gcs.Client(project=project)
        self.bucket_name = bucket
        self._bucket = client.bucket(bucket)

    def upload(self, fileobj: BinaryIO, key: str, content_type: str) -> None:
        try:
            self._bucket.blob(key).upload_from_file(fileobj, content_type=content_type)
        except self._api_error as e:
            raise ProviderError(f"Failed to upload '{key}': {e}") from e

    def download_to(self, key: str, fileobj: BinaryIO) -> None:
        try:
            self._bucket.blob(key).download_to_file(fileobj)
        except self._not_found as e:
            raise ObjectNotFoundError(f"'{key}' is missing from the bucket") from e
        except self._api_error as e:
            raise ProviderError(f"Failed to download '{key}': {e}") from e

    def iter_chunks(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        try:
            with self._bucket.blob(key).open("rb") as reader:
                while chunk := reader.read(chunk_size):
                    yield chunk
        except self._not_found as e:
            raise ObjectNotFoundError(f"'{key}' is missing from the bucket") from e
        except self._api_error as e:
            raise ProviderError(f"Failed to download '{key}': {e}") from e

    def delete(self, key: str) -> None:
        try:
            self._bucket.blob(key).delete()
        except self._not_found:
            return  # already gone: deleting is idempotent
        except self._api_error as e:
            raise ProviderError(f"Failed to delete '{key}' from storage: {e}") from e
