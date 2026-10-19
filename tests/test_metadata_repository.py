from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

from storage import MetadataError
from storage.metadata import MetadataRepository, ObjectRecord, create_db_engine, init_db

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def make(
    object_id: str,
    *,
    created: datetime = NOW,
    expires: datetime | None = None,
) -> ObjectRecord:
    return ObjectRecord(
        object_id=object_id,
        key=f"objects/{object_id}/f.txt",
        filename="f.txt",
        content_type="text/plain",
        size=3,
        created_at=created,
        expires_at=expires,
    )


@pytest.fixture
def repo() -> Iterator[MetadataRepository]:
    engine = create_db_engine("sqlite://")
    init_db(engine)
    yield MetadataRepository(engine)
    engine.dispose()


def test_insert_and_get_round_trip_with_utc(repo: MetadataRepository) -> None:
    expires = NOW + timedelta(days=1)
    stored = repo.insert(make("a", expires=expires))
    assert stored.object_id == "a"

    got = repo.get("a")
    assert got is not None
    assert got.key == "objects/a/f.txt"
    assert got.size == 3
    assert got.created_at == NOW
    assert got.created_at.tzinfo is not None
    assert got.expires_at == expires


def test_get_unknown_returns_none(repo: MetadataRepository) -> None:
    assert repo.get("nope") is None


def test_non_utc_datetimes_are_normalised(repo: MetadataRepository) -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 6, 1, 17, 30, 0, tzinfo=ist)  # == 12:00 UTC
    repo.insert(make("a", created=local))
    got = repo.get("a")
    assert got is not None
    assert got.created_at == NOW


def test_insert_duplicate_raises_metadata_error(repo: MetadataRepository) -> None:
    repo.insert(make("a"))
    with pytest.raises(MetadataError):
        repo.insert(make("a"))


def test_list_is_newest_first_with_paging(repo: MetadataRepository) -> None:
    for i in range(5):
        repo.insert(make(f"o{i}", created=NOW + timedelta(minutes=i)))
    assert [r.object_id for r in repo.list()] == ["o4", "o3", "o2", "o1", "o0"]
    assert [r.object_id for r in repo.list(limit=2)] == ["o4", "o3"]
    assert [r.object_id for r in repo.list(limit=2, offset=3)] == ["o1", "o0"]
    assert list(repo.list(offset=10)) == []


def test_delete(repo: MetadataRepository) -> None:
    repo.insert(make("a"))
    assert repo.delete("a") is True
    assert repo.get("a") is None
    assert repo.delete("a") is False


def test_list_expired(repo: MetadataRepository) -> None:
    repo.insert(make("past", expires=NOW - timedelta(hours=1)))
    repo.insert(make("exactly_now", expires=NOW))
    repo.insert(make("future", expires=NOW + timedelta(hours=1)))
    repo.insert(make("never", expires=None))

    expired = {r.object_id for r in repo.list_expired(NOW)}
    assert expired == {"past", "exactly_now"}


def test_list_expired_defaults_to_the_current_time(repo: MetadataRepository) -> None:
    now = datetime.now(timezone.utc)
    repo.insert(make("old", expires=now - timedelta(seconds=5)))
    repo.insert(make("new", expires=now + timedelta(hours=1)))
    assert {r.object_id for r in repo.list_expired()} == {"old"}


def test_database_errors_become_metadata_errors() -> None:
    engine = create_db_engine("sqlite://")  # tables never created
    repo = MetadataRepository(engine)
    with pytest.raises(MetadataError):
        repo.get("a")
    with pytest.raises(MetadataError):
        repo.insert(make("a"))
    with pytest.raises(MetadataError):
        repo.list()
    with pytest.raises(MetadataError):
        repo.delete("a")
    with pytest.raises(MetadataError):
        repo.list_expired()
