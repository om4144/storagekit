from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlmodel import Session

from storage import MetadataError
from storage.metadata import ObjectRecord, create_db_engine, init_db


def _record(object_id: str = "a") -> ObjectRecord:
    return ObjectRecord(
        object_id=object_id,
        key=f"objects/{object_id}/f.txt",
        filename="f.txt",
        content_type="text/plain",
        size=1,
        created_at=datetime(2026, 1, 1),
    )


def test_init_db_creates_the_table() -> None:
    engine = create_db_engine("sqlite://")
    assert "object_records" not in inspect(engine).get_table_names()
    init_db(engine)
    tables = inspect(engine).get_table_names()
    assert "object_records" in tables
    columns = {c["name"] for c in inspect(engine).get_columns("object_records")}
    assert columns == {
        "object_id",
        "key",
        "filename",
        "content_type",
        "size",
        "created_at",
        "expires_at",
    }


def test_init_db_is_idempotent_and_keeps_data() -> None:
    engine = create_db_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        session.add(_record())
        session.commit()
    init_db(engine)
    with Session(engine) as session:
        assert session.get(ObjectRecord, "a") is not None


def test_expires_at_is_indexed() -> None:
    engine = create_db_engine("sqlite://")
    init_db(engine)
    indexed = [
        c
        for i in inspect(engine).get_indexes("object_records")
        for c in i["column_names"]
    ]
    assert "expires_at" in indexed


def test_in_memory_database_is_shared_between_sessions() -> None:
    engine = create_db_engine("sqlite://")
    init_db(engine)
    with Session(engine) as one:
        one.add(_record())
        one.commit()
    with Session(engine) as two:
        assert two.get(ObjectRecord, "a") is not None


def test_file_database_persists(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'meta.db'}"
    first = create_db_engine(url)
    init_db(first)
    with Session(first) as session:
        session.add(_record())
        session.commit()
    first.dispose()

    second = create_db_engine(url)
    init_db(second)
    with Session(second) as session:
        assert session.get(ObjectRecord, "a") is not None
    assert (tmp_path / "meta.db").exists()


def test_bad_urls_raise_metadata_error() -> None:
    with pytest.raises(MetadataError):
        create_db_engine("not a url")
    with pytest.raises(MetadataError):
        create_db_engine("nosuchdialect://host/db")


def test_init_db_failure_raises_metadata_error(tmp_path: Path) -> None:
    # a directory is not a valid SQLite file
    engine = create_db_engine(f"sqlite:///{tmp_path}")
    with pytest.raises(MetadataError):
        init_db(engine)


def test_naive_datetimes_round_trip_as_given() -> None:
    engine = create_db_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        session.add(_record())
        session.commit()
        row = session.get(ObjectRecord, "a")
        assert row is not None
        assert row.created_at == datetime(2026, 1, 1)
        assert row.created_at.tzinfo is None
    assert datetime.now(timezone.utc).tzinfo is not None
