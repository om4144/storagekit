"""Storage providers and the factory that builds one from a StorageConfig.

``GCSProvider`` and ``AzureBlobProvider`` import their SDKs only when
instantiated, so importing this package never needs the optional extras.
"""

from __future__ import annotations

from ..common.base import StorageProvider
from ..common.config import StorageConfig
from ..common.exceptions import ConfigError
from .azure_blob import AzureBlobProvider
from .gcs import GCSProvider
from .s3 import S3Provider


def create_provider(config: StorageConfig) -> StorageProvider:
    """Build the provider selected by ``config.provider``."""
    if config.provider == "s3":
        return S3Provider(
            config.bucket,
            endpoint_url=config.s3_endpoint_url,
            access_key=config.s3_access_key,
            secret_key=(
                config.s3_secret_key.get_secret_value()
                if config.s3_secret_key
                else None
            ),
            region=config.s3_region,
            signature_version=config.s3_signature_version,
        )
    if config.provider == "gcs":
        return GCSProvider(
            config.bucket,
            project=config.gcs_project,
            credentials_file=config.gcs_credentials_file,
        )
    if config.provider == "azure":
        return AzureBlobProvider(
            config.bucket,
            connection_string=(
                config.azure_connection_string.get_secret_value()
                if config.azure_connection_string
                else None
            ),
            account_url=config.azure_account_url,
            credential=(
                config.azure_credential.get_secret_value()
                if config.azure_credential
                else None
            ),
        )
    raise ConfigError(f"Unknown provider: {config.provider!r}")  # pragma: no cover


__all__ = [
    "AzureBlobProvider",
    "GCSProvider",
    "S3Provider",
    "create_provider",
]
