"""storagekit: save, load and auto-expire files on S3, GCS or Azure Blob Storage."""

from .common.base import StorageProvider
from .common.config import StorageConfig
from .common.exceptions import (
    ConfigError,
    MetadataError,
    ObjectExpiredError,
    ObjectNotFoundError,
    ProviderError,
    StorageError,
)
from .common.models import FileMetadata, UploadResult
from .core import StorageService

__version__ = "0.1.0"

__all__ = [
    "ConfigError",
    "FileMetadata",
    "MetadataError",
    "ObjectExpiredError",
    "ObjectNotFoundError",
    "ProviderError",
    "StorageConfig",
    "StorageError",
    "StorageProvider",
    "StorageService",
    "UploadResult",
    "__version__",
]
