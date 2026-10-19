"""StorageService: the one class most users need."""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import tempfile
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, Union
from uuid import uuid4

from sqlalchemy import Engine

from .cleanup import CleanupScheduler, cleanup_expired
from .common.base import StorageProvider
from .common.config import StorageConfig
from .common.exceptions import (
    ObjectExpiredError,
    ObjectNotFoundError,
    StorageError,
)
from .common.models import FileMetadata, UploadResult
from .metadata.db import create_db_engine, init_db
from .metadata.models import ObjectRecord
from .metadata.repository import MetadataRepository
from .providers import create_provider

logger = logging.getLogger("storage")

Source = Union[str, "os.PathLike[str]", bytes, bytearray, memoryview, BinaryIO]


class _Default:
    def __repr__(self) -> str:
        return "<default>"


_DEFAULT: Any = _Default()


def _safe_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name or "file"


def _measure(fileobj: BinaryIO) -> int | None:
    """Bytes left to read in a seekable file object, else None."""
    try:
        if not fileobj.seekable():
            return None
        pos = fileobj.tell()
        end = fileobj.seek(0, os.SEEK_END)
        fileobj.seek(pos)
        return end - pos
    except (OSError, ValueError, AttributeError):
        return None


def _open_source(
    source: Source, filename: str | None
) -> tuple[BinaryIO, str, int | None, bool]:
    """Return (file object, filename, size, close_after_use)."""
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {path}")
        return (
            open(path, "rb"),
            _safe_filename(filename or path.name),
            path.stat().st_size,
            True,
        )

    if isinstance(source, (bytes, bytearray, memoryview)):
        if not filename:
            raise ValueError("filename is required when saving bytes")
        data = bytes(source)
        return io.BytesIO(data), _safe_filename(filename), len(data), False

    if hasattr(source, "read"):
        if isinstance(source, io.TextIOBase):
            raise TypeError("Open the file in binary mode ('rb')")
        raw_name = getattr(source, "name", None)
        name = filename or (raw_name if isinstance(raw_name, str) else None)
        if not name:
            raise ValueError("filename is required for file objects without a name")
        return source, _safe_filename(name), _measure(source), False

    raise TypeError(
        "source must be a path, bytes or a binary file object, "
        f"got {type(source).__name__}"
    )


def _expires_at(record: ObjectRecord) -> datetime | None:
    return record.expires_at


class StorageService:
    """Save, load and auto-expire files on S3, GCS or Azure Blob Storage.

    >>> config = StorageConfig(bucket="my-bucket", s3_access_key="...",
    ...                        s3_secret_key="...")
    >>> with StorageService(config) as storage:
    ...     result = storage.save("report.pdf")
    ...     data = storage.load(result.object_id)
    ...     storage.delete(result.object_id)
    """

    def __init__(
        self,
        config: StorageConfig,
        *,
        provider: StorageProvider | None = None,
        repository: MetadataRepository | None = None,
    ) -> None:
        """
        Args:
            config: Settings. ``config.provider`` picks S3, GCS or Azure.
            provider: Use this provider instead of building one from ``config``.
            repository: Use this metadata repository instead of creating the
                database from ``config.database_url``.
        """
        self.config = config
        self._provider = provider or create_provider(config)
        self._engine: Engine | None = None
        if repository is None:
            self._engine = create_db_engine(config.database_url)
            init_db(self._engine)
            repository = MetadataRepository(self._engine)
        self._repo = repository
        self._scheduler: CleanupScheduler | None = None

    @classmethod
    def from_env(
        cls, env_file: str | os.PathLike[str] | None = ".env", **overrides: Any
    ) -> StorageService:
        """Build a service from environment variables and/or a ``.env`` file."""
        return cls(StorageConfig.from_env(env_file, **overrides))

    # ------------------------------------------------------------------ save

    def save(
        self,
        source: Source,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        ttl_days: float | None = _DEFAULT,
    ) -> UploadResult:
        """Upload a file and return its :class:`UploadResult`.

        ``source`` may be a path, ``bytes`` or a binary file object. ``filename``
        is required unless it can be taken from the path or the file object's name.
        ``ttl_days`` overrides ``config.ttl_days`` for this object (``None`` = never).
        """
        fileobj, name, size, close_after = _open_source(source, filename)
        try:
            content_type = (
                content_type
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream"
            )
            object_id = str(uuid4())
            prefix = self.config.key_prefix.strip("/")
            key = f"{prefix}/{object_id}/{name}" if prefix else f"{object_id}/{name}"
            self._provider.upload(fileobj, key, content_type)
        finally:
            if close_after:
                fileobj.close()

        ttl = self.config.ttl_days if ttl_days is _DEFAULT else ttl_days
        now = datetime.now(timezone.utc)
        record = ObjectRecord(
            object_id=object_id,
            key=key,
            filename=name,
            content_type=content_type,
            size=size,
            created_at=now,
            expires_at=now + timedelta(days=ttl) if ttl is not None else None,
        )
        try:
            stored = self._repo.insert(record)
        except Exception:
            # Don't leave an untracked object behind that no cleanup will find.
            try:
                self._provider.delete(key)
            except StorageError:
                logger.warning("Could not roll back upload of %s", key)
            raise
        return UploadResult(key=stored.key, **self._metadata_fields(stored))

    # ------------------------------------------------------------------ read

    @staticmethod
    def _metadata_fields(record: ObjectRecord) -> dict[str, Any]:
        return {
            "object_id": record.object_id,
            "filename": record.filename,
            "content_type": record.content_type,
            "size": record.size,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
        }

    def metadata(self, object_id: str) -> FileMetadata | None:
        """Return the file's metadata, or ``None`` if unknown (no provider call)."""
        record = self._repo.get(object_id)
        return FileMetadata(**self._metadata_fields(record)) if record else None

    def list_files(
        self, *, limit: int = 100, offset: int = 0
    ) -> Sequence[FileMetadata]:
        """Metadata for stored files, newest first."""
        return [
            FileMetadata(**self._metadata_fields(r))
            for r in self._repo.list(limit=limit, offset=offset)
        ]

    def _require(self, object_id: str) -> ObjectRecord:
        record = self._repo.get(object_id)
        if record is None:
            raise ObjectNotFoundError(f"Invalid object id: {object_id}")
        expires_at = _expires_at(record)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise ObjectExpiredError(f"Object {object_id} has expired")
        return record

    def load(self, object_id: str) -> bytes:
        """Return the whole file as bytes (loads it into memory)."""
        record = self._require(object_id)
        buffer = io.BytesIO()
        self._provider.download_to(record.key, buffer)
        return buffer.getvalue()

    def stream(self, object_id: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Yield the file in chunks without holding it all in memory."""
        record = self._require(object_id)
        return self._provider.iter_chunks(record.key, chunk_size)

    def download(self, object_id: str, dest: str | os.PathLike[str] = ".") -> Path:
        """Save the file to ``dest`` and return the path.

        If ``dest`` is an existing directory the original filename is used. The
        file is written atomically, so a failed download leaves nothing behind.
        """
        record = self._require(object_id)
        target = Path(dest)
        if target.is_dir():
            target = target / record.filename
        target.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".storage-")
        try:
            with os.fdopen(fd, "wb") as tmp:
                self._provider.download_to(record.key, tmp)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return target

    # ---------------------------------------------------------------- delete

    def delete(self, object_id: str, *, missing_ok: bool = False) -> None:
        """Delete the file from the provider, then its metadata.

        If the provider fails, the metadata is kept so you can retry.
        """
        record = self._repo.get(object_id)
        if record is None:
            if missing_ok:
                return
            raise ObjectNotFoundError(f"Invalid object id: {object_id}")
        self._provider.delete(record.key)
        self._repo.delete(object_id)

    # --------------------------------------------------------------- cleanup

    def cleanup(self) -> int:
        """Delete every expired object now. Returns how many were removed."""
        return cleanup_expired(self._provider, self._repo)

    def start_cleanup(self, interval: float = 3600) -> None:
        """Run :meth:`cleanup` now and every ``interval`` seconds in a daemon thread."""
        if self._scheduler is None:
            self._scheduler = CleanupScheduler(self.cleanup, interval)
        self._scheduler.start()

    def stop_cleanup(self) -> None:
        if self._scheduler is not None:
            self._scheduler.stop()
            self._scheduler = None

    # --------------------------------------------------------------- closing

    def close(self) -> None:
        """Stop background cleanup and release the provider and database."""
        self.stop_cleanup()
        self._provider.close()
        if self._engine is not None:
            self._engine.dispose()

    def __enter__(self) -> StorageService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
