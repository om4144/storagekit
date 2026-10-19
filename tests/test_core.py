import io
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from storage import (
    FileMetadata,
    ObjectExpiredError,
    ObjectNotFoundError,
    ProviderError,
    StorageConfig,
    StorageService,
    UploadResult,
)
from storage.providers import S3Provider

from .conftest import BUCKET, bucket_keys


def test_save_bytes_and_load(service: StorageService, s3_client: Any) -> None:
    result = service.save(b"hello", filename="hello.txt")
    assert isinstance(result, UploadResult)
    assert result.filename == "hello.txt"
    assert result.content_type == "text/plain"
    assert result.size == 5
    assert result.key == f"objects/{result.object_id}/hello.txt"
    assert result.expires_at is not None
    assert result.expires_at - result.created_at == timedelta(days=1)
    assert bucket_keys(s3_client) == [result.key]
    assert service.load(result.object_id) == b"hello"


def test_save_path_and_download(service: StorageService, tmp_path: Path) -> None:
    src = tmp_path / "report.pdf"
    src.write_bytes(b"%PDF-1.4 data")
    result = service.save(src)
    assert result.filename == "report.pdf"
    assert result.content_type == "application/pdf"
    assert result.size == 13

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    path = service.download(result.object_id, out_dir)
    assert path == out_dir / "report.pdf"
    assert path.read_bytes() == b"%PDF-1.4 data"

    explicit = service.download(result.object_id, tmp_path / "nested" / "copy.bin")
    assert explicit.read_bytes() == b"%PDF-1.4 data"


def test_save_file_object(service: StorageService, tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    src.write_bytes(b"a,b\n1,2\n")
    with open(src, "rb") as fh:
        result = service.save(fh)
    assert result.filename == "a.csv"
    assert result.size == 8
    assert service.load(result.object_id) == b"a,b\n1,2\n"


def test_save_argument_errors(service: StorageService, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        service.save(b"no name")
    with pytest.raises(ValueError):
        service.save(io.BytesIO(b"no name"))
    with pytest.raises(FileNotFoundError):
        service.save(tmp_path / "missing.txt")
    with pytest.raises(TypeError):
        service.save(io.StringIO("text"), filename="t.txt")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        service.save(123)  # type: ignore[arg-type]


def test_filename_is_reduced_to_base_name(service: StorageService) -> None:
    result = service.save(b"x", filename="../../etc/passwd")
    assert result.filename == "passwd"
    assert result.key.endswith("/passwd")


def test_stream(service: StorageService) -> None:
    payload = b"x" * 200_000
    result = service.save(payload, filename="big.bin")
    chunks = service.stream(result.object_id, chunk_size=1000)
    assert b"".join(chunks) == payload


def test_metadata_and_list_files(service: StorageService) -> None:
    first = service.save(b"1", filename="one.txt")
    time.sleep(0.01)
    second = service.save(b"2", filename="two.txt")

    meta = service.metadata(first.object_id)
    assert isinstance(meta, FileMetadata)
    assert meta.object_id == first.object_id
    assert meta.created_at == first.created_at
    assert service.metadata("nope") is None

    listed = service.list_files()
    assert [m.object_id for m in listed] == [second.object_id, first.object_id]
    assert [m.object_id for m in service.list_files(limit=1)] == [second.object_id]
    assert [m.object_id for m in service.list_files(limit=1, offset=1)] == [
        first.object_id
    ]


def test_models_dump(service: StorageService) -> None:
    result = service.save(b"hi", filename="hi.txt")
    data = result.model_dump()
    assert data["object_id"] == result.object_id
    assert data["key"] == result.key
    assert '"filename":"hi.txt"' in result.model_dump_json()


def test_unknown_id(service: StorageService) -> None:
    with pytest.raises(ObjectNotFoundError):
        service.load("nope")
    with pytest.raises(ObjectNotFoundError):
        service.delete("nope")
    service.delete("nope", missing_ok=True)


def test_delete_removes_bucket_object_and_metadata(
    service: StorageService, s3_client: Any
) -> None:
    result = service.save(b"bye", filename="bye.txt")
    service.delete(result.object_id)
    assert bucket_keys(s3_client) == []
    assert service.metadata(result.object_id) is None


def test_ttl_override_and_never_expire(service: StorageService) -> None:
    short = service.save(b"a", filename="a.txt", ttl_days=0.5)
    forever = service.save(b"b", filename="b.txt", ttl_days=None)
    assert short.expires_at is not None
    assert short.expires_at - short.created_at == timedelta(hours=12)
    assert forever.expires_at is None
    assert not forever.expired


def test_expired_objects_are_blocked_then_cleaned(
    service: StorageService, s3_client: Any
) -> None:
    keep = service.save(b"keep", filename="keep.txt")
    gone = service.save(b"gone", filename="gone.txt", ttl_days=-1)  # already expired
    assert gone.expired

    with pytest.raises(ObjectExpiredError):
        service.load(gone.object_id)
    with pytest.raises(ObjectNotFoundError):  # ObjectExpiredError is a subclass
        service.download(gone.object_id)

    assert service.cleanup() == 1
    assert bucket_keys(s3_client) == [keep.key]
    assert service.metadata(gone.object_id) is None
    assert service.metadata(keep.object_id) is not None
    assert service.cleanup() == 0


def test_cleanup_continues_after_a_failure(
    service: StorageService, provider: S3Provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = service.save(b"a", filename="a.txt", ttl_days=-1)
    b = service.save(b"b", filename="b.txt", ttl_days=-1)

    real_delete = provider.delete

    def flaky(key: str) -> None:
        if key == a.key:
            raise ProviderError("boom")
        real_delete(key)

    monkeypatch.setattr(provider, "delete", flaky)
    assert service.cleanup() == 1
    assert service.metadata(a.object_id) is not None  # kept for the next run
    assert service.metadata(b.object_id) is None


def test_failed_provider_delete_keeps_metadata(
    service: StorageService, provider: S3Provider, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = service.save(b"a", filename="a.txt")

    def boom(key: str) -> None:
        raise ProviderError("boom")

    monkeypatch.setattr(provider, "delete", boom)
    with pytest.raises(ProviderError):
        service.delete(result.object_id)
    assert service.metadata(result.object_id) is not None


def test_upload_is_rolled_back_if_metadata_write_fails(
    service: StorageService, s3_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(record: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(service._repo, "insert", boom)
    with pytest.raises(RuntimeError):
        service.save(b"x", filename="x.txt")
    assert bucket_keys(s3_client) == []


def test_object_missing_from_bucket_raises_not_found(
    service: StorageService, s3_client: Any
) -> None:
    result = service.save(b"x", filename="x.txt")
    s3_client.delete_object(Bucket=BUCKET, Key=result.key)
    with pytest.raises(ObjectNotFoundError):
        service.load(result.object_id)


def test_failed_download_leaves_no_partial_file(
    service: StorageService, s3_client: Any, tmp_path: Path
) -> None:
    result = service.save(b"x", filename="x.txt")
    s3_client.delete_object(Bucket=BUCKET, Key=result.key)
    target = tmp_path / "out" / "x.txt"
    with pytest.raises(ObjectNotFoundError):
        service.download(result.object_id, target)
    assert not target.exists()
    assert list(target.parent.iterdir()) == []


def test_background_cleanup_thread(service: StorageService, s3_client: Any) -> None:
    gone = service.save(b"gone", filename="gone.txt", ttl_days=-1)
    service.start_cleanup(interval=0.05)
    service.start_cleanup(interval=0.05)  # second call is a no-op
    for _ in range(100):
        if service.metadata(gone.object_id) is None:
            break
        time.sleep(0.05)
    service.stop_cleanup()
    assert service.metadata(gone.object_id) is None
    assert bucket_keys(s3_client) == []


def test_metadata_persists_across_instances(
    config: StorageConfig, provider: S3Provider
) -> None:
    with StorageService(config, provider=provider) as one:
        result = one.save(b"persist", filename="p.txt")
    with StorageService(config, provider=provider) as two:
        assert two.load(result.object_id) == b"persist"
        assert two.metadata(result.object_id) == FileMetadata(
            **result.model_dump(exclude={"key"})
        )


def test_custom_key_prefix(provider: S3Provider, tmp_path: Path) -> None:
    config = StorageConfig(
        bucket=BUCKET,
        key_prefix="/uploads/",
        database_url=f"sqlite:///{tmp_path / 'm.db'}",
    )
    with StorageService(config, provider=provider) as svc:
        assert svc.save(b"x", filename="x.txt").key.startswith("uploads/")


def test_empty_key_prefix(provider: S3Provider, tmp_path: Path) -> None:
    config = StorageConfig(
        bucket=BUCKET, key_prefix="", database_url=f"sqlite:///{tmp_path / 'm.db'}"
    )
    with StorageService(config, provider=provider) as svc:
        result = svc.save(b"x", filename="x.txt")
        assert result.key == f"{result.object_id}/x.txt"


def test_is_expired_compares_with_given_time(service: StorageService) -> None:
    result = service.save(b"x", filename="x.txt")
    assert result.is_expired(datetime.now(timezone.utc) + timedelta(days=2))
    assert not result.is_expired(datetime.now(timezone.utc))


def test_from_env(
    monkeypatch: pytest.MonkeyPatch, provider: S3Provider, tmp_path: Path
) -> None:
    monkeypatch.setenv("STORAGEKIT_BUCKET", BUCKET)
    monkeypatch.setenv("STORAGEKIT_DATABASE_URL", f"sqlite:///{tmp_path / 'e.db'}")
    config = StorageConfig.from_env(env_file=None)
    with StorageService(config, provider=provider) as svc:
        assert svc.config.bucket == BUCKET
        assert svc.save(b"x", filename="x.txt").object_id
