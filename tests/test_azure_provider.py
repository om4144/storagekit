"""AzureBlobProvider tests with a fake client (no network, no credentials)."""

import io
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("azure.storage.blob")

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from storage import ConfigError, ObjectNotFoundError, ProviderError
from storage.providers import AzureBlobProvider


class FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readinto(self, fileobj: Any) -> int:
        fileobj.write(self._data)
        return len(self._data)

    def chunks(self) -> Iterator[bytes]:
        for i in range(0, len(self._data), 64):
            yield self._data[i : i + 64]


class FakeContainer:
    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str | None]] = {}

    def upload_blob(
        self, name: str, data: Any, overwrite: bool, content_settings: Any
    ) -> None:
        assert overwrite is True
        self.blobs[name] = (data.read(), content_settings.content_type)

    def download_blob(self, name: str) -> FakeDownloader:
        if name not in self.blobs:
            raise ResourceNotFoundError("no such blob")
        return FakeDownloader(self.blobs[name][0])

    def delete_blob(self, name: str) -> None:
        if name not in self.blobs:
            raise ResourceNotFoundError("no such blob")
        del self.blobs[name]


class FakeServiceClient:
    def __init__(self) -> None:
        self.container = FakeContainer()

    def get_container_client(self, name: str) -> FakeContainer:
        return self.container


@pytest.fixture
def service_client() -> FakeServiceClient:
    return FakeServiceClient()


@pytest.fixture
def azure(service_client: FakeServiceClient) -> AzureBlobProvider:
    return AzureBlobProvider("container", client=service_client)


def test_upload_and_download(
    azure: AzureBlobProvider, service_client: FakeServiceClient
) -> None:
    azure.upload(io.BytesIO(b"hello"), "k/hello.txt", "text/plain")
    assert service_client.container.blobs["k/hello.txt"] == (b"hello", "text/plain")

    out = io.BytesIO()
    azure.download_to("k/hello.txt", out)
    assert out.getvalue() == b"hello"


def test_iter_chunks(azure: AzureBlobProvider) -> None:
    payload = b"0123456789" * 100
    azure.upload(io.BytesIO(payload), "k/big", "application/octet-stream")
    assert b"".join(azure.iter_chunks("k/big")) == payload


def test_missing_object_raises_not_found(azure: AzureBlobProvider) -> None:
    with pytest.raises(ObjectNotFoundError):
        azure.download_to("nope", io.BytesIO())
    with pytest.raises(ObjectNotFoundError):
        list(azure.iter_chunks("nope"))


def test_delete_is_idempotent(
    azure: AzureBlobProvider, service_client: FakeServiceClient
) -> None:
    azure.upload(io.BytesIO(b"x"), "k/x", "text/plain")
    azure.delete("k/x")
    assert "k/x" not in service_client.container.blobs
    azure.delete("k/x")  # already gone: no error


def test_azure_errors_become_provider_errors(
    azure: AzureBlobProvider, service_client: FakeServiceClient
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise HttpResponseError("denied")

    container = service_client.container
    container.upload_blob = boom  # type: ignore[method-assign,assignment]
    container.download_blob = boom  # type: ignore[method-assign,assignment]
    container.delete_blob = boom  # type: ignore[method-assign]
    with pytest.raises(ProviderError):
        azure.upload(io.BytesIO(b"x"), "k", "text/plain")
    with pytest.raises(ProviderError):
        azure.download_to("k", io.BytesIO())
    with pytest.raises(ProviderError):
        list(azure.iter_chunks("k"))
    with pytest.raises(ProviderError):
        azure.delete("k")


def test_requires_connection_string_or_account_url() -> None:
    with pytest.raises(ConfigError):
        AzureBlobProvider("container")


def test_builds_client_from_connection_string() -> None:
    conn = (
        "DefaultEndpointsProtocol=https;AccountName=acct;"
        "AccountKey=a2V5;EndpointSuffix=core.windows.net"
    )
    provider = AzureBlobProvider("container", connection_string=conn)
    assert provider.container_name == "container"
