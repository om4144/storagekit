"""GCSProvider tests with a fake client (no network, no credentials)."""

import io
from typing import Any

import pytest

pytest.importorskip("google.cloud.storage")

from google.api_core import exceptions as gexc

from storage import ObjectNotFoundError, ProviderError
from storage.providers import GCSProvider


class FakeBlob:
    def __init__(self, objects: dict[str, tuple[bytes, str | None]], name: str) -> None:
        self._objects = objects
        self._name = name

    def upload_from_file(self, fileobj: Any, content_type: str | None = None) -> None:
        self._objects[self._name] = (fileobj.read(), content_type)

    def download_to_file(self, fileobj: Any) -> None:
        if self._name not in self._objects:
            raise gexc.NotFound("no such object")
        fileobj.write(self._objects[self._name][0])

    def open(self, mode: str) -> io.BytesIO:
        if self._name not in self._objects:
            raise gexc.NotFound("no such object")
        return io.BytesIO(self._objects[self._name][0])

    def delete(self) -> None:
        if self._name not in self._objects:
            raise gexc.NotFound("no such object")
        del self._objects[self._name]


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self.objects, name)


class FakeClient:
    def __init__(self) -> None:
        self.bucket_obj = FakeBucket()

    def bucket(self, name: str) -> FakeBucket:
        return self.bucket_obj


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def gcs(client: FakeClient) -> GCSProvider:
    return GCSProvider("bucket", client=client)


def test_upload_and_download(gcs: GCSProvider, client: FakeClient) -> None:
    gcs.upload(io.BytesIO(b"hello"), "k/hello.txt", "text/plain")
    assert client.bucket_obj.objects["k/hello.txt"] == (b"hello", "text/plain")

    out = io.BytesIO()
    gcs.download_to("k/hello.txt", out)
    assert out.getvalue() == b"hello"


def test_iter_chunks(gcs: GCSProvider) -> None:
    payload = b"0123456789" * 100
    gcs.upload(io.BytesIO(payload), "k/big", "application/octet-stream")
    chunks = list(gcs.iter_chunks("k/big", chunk_size=64))
    assert b"".join(chunks) == payload
    assert all(len(c) <= 64 for c in chunks)


def test_missing_object_raises_not_found(gcs: GCSProvider) -> None:
    with pytest.raises(ObjectNotFoundError):
        gcs.download_to("nope", io.BytesIO())
    with pytest.raises(ObjectNotFoundError):
        list(gcs.iter_chunks("nope"))


def test_delete_is_idempotent(gcs: GCSProvider, client: FakeClient) -> None:
    gcs.upload(io.BytesIO(b"x"), "k/x", "text/plain")
    gcs.delete("k/x")
    assert "k/x" not in client.bucket_obj.objects
    gcs.delete("k/x")  # already gone: no error


def test_api_errors_become_provider_errors(
    gcs: GCSProvider, client: FakeClient
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise gexc.Forbidden("denied")

    client.bucket_obj.blob = lambda name: type(  # type: ignore[method-assign]
        "B",
        (),
        {
            "upload_from_file": boom,
            "download_to_file": boom,
            "open": boom,
            "delete": boom,
        },
    )()
    with pytest.raises(ProviderError):
        gcs.upload(io.BytesIO(b"x"), "k", "text/plain")
    with pytest.raises(ProviderError):
        gcs.download_to("k", io.BytesIO())
    with pytest.raises(ProviderError):
        list(gcs.iter_chunks("k"))
    with pytest.raises(ProviderError):
        gcs.delete("k")
