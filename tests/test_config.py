from pathlib import Path

import pytest

from storage import ConfigError, StorageConfig
from storage.common.config import _ENV_NAMES, _parse_env_file
from storage.providers import S3Provider, create_provider

ALL_ENV_NAMES = sorted({name for names in _ENV_NAMES.values() for name in names})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults() -> None:
    config = StorageConfig(bucket="b")
    assert config.provider == "s3"
    assert config.ttl_days == 7
    assert config.database_url == "sqlite:///metadata.db"
    assert config.key_prefix == "objects"
    assert config.s3_region == "auto"
    assert config.s3_signature_version == "s3v4"


def test_config_is_frozen_and_rejects_unknown_fields() -> None:
    config = StorageConfig(bucket="b")
    with pytest.raises(ValueError):
        config.bucket = "other"  # type: ignore[misc]
    with pytest.raises(ValueError):
        StorageConfig(bucket="b", nonsense=1)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        StorageConfig(bucket="b", provider="ftp")  # type: ignore[arg-type]


def test_secrets_are_hidden() -> None:
    config = StorageConfig(bucket="b", s3_secret_key="super-secret")  # type: ignore[arg-type]
    assert "super-secret" not in repr(config)
    assert "super-secret" not in config.model_dump_json()
    assert config.s3_secret_key is not None
    assert config.s3_secret_key.get_secret_value() == "super-secret"


def test_parse_env_file_handles_spaces_quotes_and_comments(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        'CLOUD_ENDPOINT = "https://s3.filebase.com"\n'
        "ACCESS_TOKEN = 'tok'\n"
        "TTL = 1\n"
        "\n"
        'BUCKET = "s3-storage"'  # no trailing newline
    )
    assert _parse_env_file(f) == {
        "CLOUD_ENDPOINT": "https://s3.filebase.com",
        "ACCESS_TOKEN": "tok",
        "TTL": "1",
        "BUCKET": "s3-storage",
    }
    assert _parse_env_file(tmp_path / "missing") == {}


def test_from_env_reads_the_example_file() -> None:
    example = Path(__file__).parent.parent / ".env.example"
    config = StorageConfig.from_env(example)
    assert config.provider == "s3"
    assert config.bucket == "my-bucket"
    assert config.ttl_days == 7
    assert config.s3_endpoint_url == "https://s3.filebase.com"
    assert config.s3_region == "auto"


def test_legacy_env_names_still_work(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text(
        'CLOUD_ENDPOINT = "https://s3.filebase.com"\n'
        'ACCESS_TOKEN = "ak"\nAPI_KEY = "sk"\n'
        'SIGNATURE_VERSION = "v4"\nTTL = 3\nBUCKET = "s3-storage"\n'
    )
    config = StorageConfig.from_env(f)
    assert config.s3_endpoint_url == "https://s3.filebase.com"
    assert config.s3_access_key == "ak"
    assert config.s3_secret_key is not None
    assert config.s3_secret_key.get_secret_value() == "sk"
    assert config.s3_signature_version == "v4"
    assert config.ttl_days == 3.0
    assert config.bucket == "s3-storage"


def test_precedence_override_over_env_over_file_and_new_over_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / ".env"
    f.write_text("BUCKET = from-file\n")
    monkeypatch.setenv("BUCKET", "legacy-env")
    assert StorageConfig.from_env(f).bucket == "legacy-env"
    monkeypatch.setenv("STORAGEKIT_BUCKET", "new-env")
    assert StorageConfig.from_env(f).bucket == "new-env"
    assert StorageConfig.from_env(f, bucket="explicit").bucket == "explicit"


def test_missing_bucket(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        StorageConfig.from_env(tmp_path / "nope.env")
    assert "bucket" in str(exc.value)


def test_ttl_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGEKIT_BUCKET", "b")
    monkeypatch.setenv("STORAGEKIT_TTL_DAYS", "never")
    assert StorageConfig.from_env(None).ttl_days is None
    monkeypatch.setenv("STORAGEKIT_TTL_DAYS", "2.5")
    assert StorageConfig.from_env(None).ttl_days == 2.5
    monkeypatch.setenv("STORAGEKIT_TTL_DAYS", "abc")
    with pytest.raises(ConfigError):
        StorageConfig.from_env(None)


def test_invalid_provider_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGEKIT_BUCKET", "b")
    monkeypatch.setenv("STORAGEKIT_PROVIDER", "ftp")
    with pytest.raises(ConfigError):
        StorageConfig.from_env(None)


def test_create_provider_builds_s3() -> None:
    config = StorageConfig(
        bucket="b",
        s3_endpoint_url="https://example.invalid",
        s3_access_key="a",
        s3_secret_key="s",  # type: ignore[arg-type]
        s3_signature_version="v4",
    )
    provider = create_provider(config)
    assert isinstance(provider, S3Provider)
    assert provider.bucket == "b"
    assert provider.client.meta.endpoint_url == "https://example.invalid"
