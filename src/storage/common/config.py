"""StorageConfig: all settings in one validated object."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from .exceptions import ConfigError

# field -> environment variable names, checked in order (first match wins)
_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "provider": ("STORAGEKIT_PROVIDER",),
    "bucket": ("STORAGEKIT_BUCKET", "BUCKET"),
    "ttl_days": ("STORAGEKIT_TTL_DAYS", "TTL"),
    "database_url": ("STORAGEKIT_DATABASE_URL",),
    "key_prefix": ("STORAGEKIT_KEY_PREFIX",),
    "s3_endpoint_url": ("STORAGEKIT_S3_ENDPOINT_URL", "CLOUD_ENDPOINT"),
    "s3_access_key": ("STORAGEKIT_S3_ACCESS_KEY", "ACCESS_TOKEN"),
    "s3_secret_key": ("STORAGEKIT_S3_SECRET_KEY", "API_KEY"),
    "s3_region": ("STORAGEKIT_S3_REGION", "REGION"),
    "s3_signature_version": ("STORAGEKIT_S3_SIGNATURE_VERSION", "SIGNATURE_VERSION"),
    "gcs_project": ("STORAGEKIT_GCS_PROJECT",),
    "gcs_credentials_file": ("STORAGEKIT_GCS_CREDENTIALS_FILE",),
    "azure_connection_string": ("STORAGEKIT_AZURE_CONNECTION_STRING",),
    "azure_account_url": ("STORAGEKIT_AZURE_ACCOUNT_URL",),
    "azure_credential": ("STORAGEKIT_AZURE_CREDENTIAL",),
}


class StorageConfig(BaseModel):
    """Settings for a :class:`~storage.StorageService`.

    Build it directly, or from the environment with :meth:`from_env`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["s3", "gcs", "azure"] = "s3"
    bucket: str  # bucket name (S3, GCS) or container name (Azure)
    ttl_days: float | None = 7  # None = objects never expire
    database_url: str = "sqlite:///metadata.db"
    key_prefix: str = "objects"

    # S3 and S3-compatible services
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "auto"
    s3_signature_version: str = "s3v4"

    # Google Cloud Storage
    gcs_project: str | None = None
    gcs_credentials_file: str | None = None

    # Azure Blob Storage
    azure_connection_string: SecretStr | None = None
    azure_account_url: str | None = None
    azure_credential: SecretStr | None = None

    @classmethod
    def from_env(
        cls, env_file: str | os.PathLike[str] | None = ".env", **overrides: Any
    ) -> StorageConfig:
        """Load settings from environment variables and/or a ``.env`` file.

        Real environment variables win over the file, and keyword ``overrides``
        win over both. Raises :class:`ConfigError` for missing or invalid values.
        """
        file_values = _parse_env_file(env_file) if env_file else {}

        values: dict[str, Any] = {}
        for field, names in _ENV_NAMES.items():
            raw = _lookup(names, file_values)
            if raw is not None and raw != "":
                values[field] = raw
        values.update(overrides)

        if "bucket" not in values:
            raise ConfigError(
                f"Missing configuration: bucket ({' or '.join(_ENV_NAMES['bucket'])})"
            )

        ttl = values.get("ttl_days")
        if isinstance(ttl, str):
            if ttl.lower() in {"never", "none"}:
                values["ttl_days"] = None
            else:
                try:
                    values["ttl_days"] = float(ttl)
                except ValueError as e:
                    raise ConfigError(
                        f"TTL must be a number of days or 'never', got {ttl!r}"
                    ) from e

        try:
            return cls(**values)
        except ValidationError as e:
            raise ConfigError(f"Invalid configuration: {e}") from e


def _lookup(names: tuple[str, ...], file_values: dict[str, str]) -> str | None:
    for name in names:
        if name in os.environ:
            return os.environ[name]
    for name in names:
        if name in file_values:
            return file_values[name]
    return None


def _parse_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parse simple ``KEY = "value"`` lines. A missing file gives an empty dict."""
    p = Path(path)
    if not p.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    return values
