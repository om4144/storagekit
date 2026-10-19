import io
from typing import Any

import pytest

from storage import ObjectNotFoundError, ProviderError
from storage.providers import S3Provider
from storage.providers.s3 import normalize_signature_version

from .conftest import BUCKET


def test_upload_and_download(provider: S3Provider) -> None:
    provider.upload(io.BytesIO(b"hello"), "k/hello.txt", "text/plain")
    out = io.BytesIO()
    provider.download_to("k/hello.txt", out)
    assert out.getvalue() == b"hello"


def test_upload_sets_content_type(provider: S3Provider, s3_client: Any) -> None:
    provider.upload(io.BytesIO(b"{}"), "k/data.json", "application/json")
    head = s3_client.head_object(Bucket=BUCKET, Key="k/data.json")
    assert head["ContentType"] == "application/json"


def test_iter_chunks(provider: S3Provider) -> None:
    payload = b"abcdefghij" * 1000
    provider.upload(io.BytesIO(payload), "k/big", "application/octet-stream")
    chunks = list(provider.iter_chunks("k/big", chunk_size=1024))
    assert b"".join(chunks) == payload
    assert all(len(c) <= 1024 for c in chunks)


def test_missing_object_raises_not_found(provider: S3Provider) -> None:
    with pytest.raises(ObjectNotFoundError):
        provider.download_to("nope", io.BytesIO())
    with pytest.raises(ObjectNotFoundError):
        list(provider.iter_chunks("nope"))


def test_delete_is_idempotent(provider: S3Provider, s3_client: Any) -> None:
    provider.upload(io.BytesIO(b"x"), "k/x", "text/plain")
    provider.delete("k/x")
    provider.delete("k/x")  # already gone: no error
    assert "Contents" not in s3_client.list_objects_v2(Bucket=BUCKET)


def test_provider_errors_are_wrapped(s3_client: Any) -> None:
    broken = S3Provider("bucket-that-does-not-exist", client=s3_client)
    with pytest.raises(ProviderError):
        broken.upload(io.BytesIO(b"x"), "k", "text/plain")
    with pytest.raises(ProviderError):
        broken.delete("k")
    with pytest.raises(ProviderError):
        broken.download_to("k", io.BytesIO())


def test_signature_aliases() -> None:
    assert normalize_signature_version("v4") == "s3v4"
    assert normalize_signature_version("s3v4") == "s3v4"
    assert normalize_signature_version("V2") == "s3"
    assert normalize_signature_version("custom") == "custom"


def test_builds_its_own_client_when_none_given() -> None:
    p = S3Provider(
        "b",
        endpoint_url="https://example.invalid",
        access_key="a",
        secret_key="s",
        region="auto",
        signature_version="v4",
    )
    assert p.client.meta.endpoint_url == "https://example.invalid"
