from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from storage import StorageConfig, StorageService
from storage.providers import S3Provider

BUCKET = "test-bucket"


@pytest.fixture
def s3_client() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="x",
            aws_secret_access_key="x",
        )
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def provider(s3_client: Any) -> S3Provider:
    return S3Provider(BUCKET, client=s3_client)


@pytest.fixture
def config(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        bucket=BUCKET,
        ttl_days=1,
        database_url=f"sqlite:///{tmp_path / 'metadata.db'}",
    )


@pytest.fixture
def service(config: StorageConfig, provider: S3Provider) -> Iterator[StorageService]:
    svc = StorageService(config, provider=provider)
    yield svc
    svc.close()


def bucket_keys(s3_client: Any) -> list[str]:
    resp = s3_client.list_objects_v2(Bucket=BUCKET)
    return [o["Key"] for o in resp.get("Contents", [])]
