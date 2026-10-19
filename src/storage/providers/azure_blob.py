"""Azure Blob Storage. Needs the extra: ``pip install "storagekit[azure]"``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

from ..common.base import StorageProvider
from ..common.exceptions import ConfigError, ObjectNotFoundError, ProviderError


class AzureBlobProvider(StorageProvider):
    def __init__(
        self,
        container: str,
        *,
        connection_string: str | None = None,
        account_url: str | None = None,
        credential: str | None = None,
        client: Any | None = None,
    ) -> None:
        """
        Args:
            container: Blob container name.
            connection_string: Full storage-account connection string, or...
            account_url / credential: ...the account URL plus an account key or
                SAS token.
            client: An existing ``BlobServiceClient`` (mostly for tests).
        """
        try:
            from azure.core.exceptions import AzureError, ResourceNotFoundError
            from azure.storage.blob import BlobServiceClient, ContentSettings
        except ImportError as e:
            raise ProviderError(
                'Azure support is not installed: pip install "storagekit[azure]"'
            ) from e

        self._not_found: type[Exception] = ResourceNotFoundError
        self._api_error: type[Exception] = AzureError
        self._content_settings = ContentSettings

        if client is None:
            if connection_string:
                client = BlobServiceClient.from_connection_string(connection_string)
            elif account_url:
                client = BlobServiceClient(
                    account_url=account_url, credential=credential
                )
            else:
                raise ConfigError(
                    "Azure needs azure_connection_string, or azure_account_url "
                    "with azure_credential"
                )
        self.container_name = container
        self._container = client.get_container_client(container)

    def upload(self, fileobj: BinaryIO, key: str, content_type: str) -> None:
        try:
            self._container.upload_blob(
                name=key,
                data=fileobj,
                overwrite=True,
                content_settings=self._content_settings(content_type=content_type),
            )
        except self._api_error as e:
            raise ProviderError(f"Failed to upload '{key}': {e}") from e

    def download_to(self, key: str, fileobj: BinaryIO) -> None:
        try:
            self._container.download_blob(key).readinto(fileobj)
        except self._not_found as e:
            raise ObjectNotFoundError(f"'{key}' is missing from the container") from e
        except self._api_error as e:
            raise ProviderError(f"Failed to download '{key}': {e}") from e

    def iter_chunks(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        # Azure decides the chunk size itself; ``chunk_size`` is not used here.
        try:
            yield from self._container.download_blob(key).chunks()
        except self._not_found as e:
            raise ObjectNotFoundError(f"'{key}' is missing from the container") from e
        except self._api_error as e:
            raise ProviderError(f"Failed to download '{key}': {e}") from e

    def delete(self, key: str) -> None:
        try:
            self._container.delete_blob(key)
        except self._not_found:
            return  # already gone: deleting is idempotent
        except self._api_error as e:
            raise ProviderError(f"Failed to delete '{key}' from storage: {e}") from e
