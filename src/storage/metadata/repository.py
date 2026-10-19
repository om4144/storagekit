"""All reads and writes of ObjectRecord rows."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, col, select

from ..common.exceptions import MetadataError
from .models import ObjectRecord


def _to_db(value: datetime | None) -> datetime | None:
    """Store datetimes as naive UTC so every database behaves the same."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _from_db(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MetadataRepository:
    """CRUD for :class:`ObjectRecord`. Every call uses its own short session.

    Records you pass in or get back have timezone-aware UTC datetimes.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _session(self) -> Session:
        # expire_on_commit=False so returned records stay readable after close
        return Session(self._engine, expire_on_commit=False)

    @staticmethod
    def _detach(session: Session, row: ObjectRecord) -> ObjectRecord:
        session.expunge(row)
        row.created_at = _from_db(row.created_at)  # type: ignore[assignment]
        row.expires_at = _from_db(row.expires_at)
        return row

    def insert(self, record: ObjectRecord) -> ObjectRecord:
        """Add a record. Raises ``MetadataError`` if the object_id already exists."""
        row = ObjectRecord(
            object_id=record.object_id,
            key=record.key,
            filename=record.filename,
            content_type=record.content_type,
            size=record.size,
            created_at=_to_db(record.created_at),  # type: ignore[arg-type]
            expires_at=_to_db(record.expires_at),
        )
        try:
            with self._session() as session:
                session.add(row)
                session.commit()
                return self._detach(session, row)
        except IntegrityError as e:
            raise MetadataError(f"Object {record.object_id} already exists") from e
        except SQLAlchemyError as e:
            raise MetadataError(f"Failed to insert {record.object_id}: {e}") from e

    def get(self, object_id: str) -> ObjectRecord | None:
        try:
            with self._session() as session:
                row = session.get(ObjectRecord, object_id)
                return self._detach(session, row) if row else None
        except SQLAlchemyError as e:
            raise MetadataError(f"Failed to read {object_id}: {e}") from e

    def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ObjectRecord]:
        """Newest first."""
        try:
            with self._session() as session:
                rows = session.exec(
                    select(ObjectRecord)
                    .order_by(col(ObjectRecord.created_at).desc())
                    .offset(offset)
                    .limit(limit)
                ).all()
                return [self._detach(session, row) for row in rows]
        except SQLAlchemyError as e:
            raise MetadataError(f"Failed to list records: {e}") from e

    def delete(self, object_id: str) -> bool:
        """Delete a record. Returns False if there was nothing to delete."""
        try:
            with self._session() as session:
                row = session.get(ObjectRecord, object_id)
                if row is None:
                    return False
                session.delete(row)
                session.commit()
                return True
        except SQLAlchemyError as e:
            raise MetadataError(f"Failed to delete {object_id}: {e}") from e

    def list_expired(self, now: datetime | None = None) -> Sequence[ObjectRecord]:
        """Records whose ``expires_at`` is at or before ``now`` (default: now)."""
        cutoff = _to_db(now or datetime.now(timezone.utc))
        try:
            with self._session() as session:
                rows = session.exec(
                    select(ObjectRecord)
                    .where(col(ObjectRecord.expires_at).is_not(None))
                    .where(col(ObjectRecord.expires_at) <= cutoff)
                ).all()
                return [self._detach(session, row) for row in rows]
        except SQLAlchemyError as e:
            raise MetadataError(f"Failed to list expired records: {e}") from e
