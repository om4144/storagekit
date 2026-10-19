"""Pydantic models returned by the public API."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_validator


class FileMetadata(BaseModel):
    """Metadata for one stored file."""

    model_config = ConfigDict(frozen=True)

    object_id: str
    filename: str
    content_type: str
    size: int | None = None
    created_at: datetime
    expires_at: datetime | None = None  # None means the file never expires

    @field_validator("created_at", "expires_at")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    @property
    def expired(self) -> bool:
        return self.is_expired()


class UploadResult(FileMetadata):
    """What ``save()`` returns: the metadata plus the key used in the bucket."""

    key: str
