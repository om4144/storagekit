"""The ObjectRecord table.

This module deliberately does not use ``from __future__ import annotations``:
SQLModel needs the real annotation objects to build the table columns.
"""

from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel


class ObjectRecord(SQLModel, table=True):
    """One row per stored object."""

    __tablename__ = "object_records"

    object_id: str = Field(primary_key=True, description="Unique id of the object")
    key: str = Field(description="Object key in the bucket or container")
    filename: str = Field(description="Original filename")
    content_type: str = Field(description="MIME type")
    size: int | None = Field(default=None, description="Size in bytes, if known")
    # sa_type pins a plain DateTime column. The repository stores naive UTC, and
    # newer SQLModel releases would otherwise pick a timezone-required type.
    created_at: datetime = Field(
        sa_type=DateTime, description="When the object was stored (UTC)"
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_type=DateTime,
        index=True,
        description="When the object expires (UTC); NULL means never",
    )
