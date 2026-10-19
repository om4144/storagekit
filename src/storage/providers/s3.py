"""S3 and S3-compatible storage (AWS S3, Cloudflare R2, MinIO, B2, Filebase...)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from ..common.base import StorageProvider
from ..common.exceptions import ObjectNotFoundError, ProviderError

_SIGNATURE_ALIASES = {"v4": "s3v4", "s3v4": "s3v4", "v2": "s3", "s3": "s3"}
_MISSING_CODES = {"NoSuchKey", "404", "NotFound"}


def normalize_signature_version(value: str) -> str:
    """Accept ``v4`` as well as boto3's ``s3v4``."""
    return _SIGNATURE_ALIASES.get(value.lower(), value)


class S3Provider(StorageProvider):
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "auto",
        signature_version: str = "s3v4",
        client: Any | None = None,
    ) -> None:
        """
        Args:
            bucket: Bucket name.
            endpoint_url: Endpoint of an S3-compatible service; omit for AWS S3.
            access_key / secret_key: Credentials; omit to use boto3's default chain.
            region: ``"auto"`` for R2/Filebase, a real region name for AWS.
            signature_version: ``"s3v4"`` (``"v4"`` is accepted too).
            client: An existing boto3 S3 client (mostly for tests).
        """
        self.bucket = bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                signature_version=normalize_signature_version(signature_version)
            ),
        )

    def upload(self, fileobj: BinaryIO, key: str, content_type: str) -> None:
        try:
            self.client.upload_fileobj(
                fileobj, self.bucket, key, ExtraArgs={"ContentType": content_type}
            )
        except (ClientError, BotoCoreError) as e:
            raise ProviderError(f"Failed to upload '{key}': {e}") from e

    def download_to(self, key: str, fileobj: BinaryIO) -> None:
        try:
            self.client.download_fileobj(self.bucket, key, fileobj)
        except ClientError as e:
            raise self._translate(key, e, "download") from e
        except BotoCoreError as e:
            raise ProviderError(f"Failed to download '{key}': {e}") from e

    def iter_chunks(self, key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as e:
            raise self._translate(key, e, "download") from e
        except BotoCoreError as e:
            raise ProviderError(f"Failed to download '{key}': {e}") from e
        try:
            yield from body.iter_chunks(chunk_size)
        finally:
            body.close()

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as e:
            raise ProviderError(f"Failed to delete '{key}' from storage: {e}") from e

    @staticmethod
    def _translate(key: str, error: ClientError, action: str) -> Exception:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in _MISSING_CODES:
            return ObjectNotFoundError(f"'{key}' is missing from the bucket")
        return ProviderError(f"Failed to {action} '{key}': {error}")
