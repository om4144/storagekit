# storagekit

Save, load and auto-expire files on **Amazon S3 (and S3-compatible services), Google Cloud Storage or Azure Blob Storage** from plain Python.

Every `save()` returns an `object_id`. File metadata (name, type, size, created and expiry time) is tracked in a small database, and expired files are removed from the bucket by `cleanup()` or a background thread.

```python
from storage import StorageConfig, StorageService

config = StorageConfig(
    provider="s3",
    bucket="my-bucket",
    s3_endpoint_url="https://s3.filebase.com",
    s3_access_key="...",
    s3_secret_key="...",
    ttl_days=7,
)

with StorageService(config) as storage:
    result = storage.save("report.pdf")  # path, bytes, or binary file object
    print(result.object_id, result.expires_at)

    data = storage.load(result.object_id)  # bytes
    storage.download(result.object_id, "downloads/")  # writes downloads/report.pdf
    storage.delete(result.object_id)
```

> The distribution is called `storagekit`; the import name is `storage`.

## Install

```bash
pip install "git+https://github.com/om4144/storagekit.git@v0.1.0"      # a fixed version
pip install "git+https://github.com/om4144/storagekit.git@main"        # latest code
pip install "storagekit[gcs] @ git+https://github.com/om4144/storagekit.git@v0.1.0"   # with an extra
```

Python 3.10+.

## Configuration

Build a `StorageConfig` directly, or load it from the environment / a `.env` file:

```python
storage = StorageService.from_env()  # reads ./.env and os.environ
storage = StorageService.from_env("config/.env", ttl_days=1)  # custom file + override
```

See [`.env.example`](.env.example) for every variable. Real environment variables win over the `.env` file, and keyword arguments win over both.

| Field                     | Env var                              | Default                   |
| ------------------------- | ------------------------------------ | ------------------------- |
| `provider`                | `STORAGEKIT_PROVIDER`                | `s3` (`s3`, `gcs`, `azure`) |
| `bucket`                  | `STORAGEKIT_BUCKET`                  | required (container for Azure) |
| `ttl_days`                | `STORAGEKIT_TTL_DAYS`                | `7` (`never` or `None` = keep forever) |
| `database_url`            | `STORAGEKIT_DATABASE_URL`            | `sqlite:///metadata.db`   |
| `key_prefix`              | `STORAGEKIT_KEY_PREFIX`              | `objects`                 |
| `s3_endpoint_url`         | `STORAGEKIT_S3_ENDPOINT_URL`         | none (AWS S3)             |
| `s3_access_key`           | `STORAGEKIT_S3_ACCESS_KEY`           | boto3 default credentials |
| `s3_secret_key`           | `STORAGEKIT_S3_SECRET_KEY`           | boto3 default credentials |
| `s3_region`               | `STORAGEKIT_S3_REGION`               | `auto`                    |
| `s3_signature_version`    | `STORAGEKIT_S3_SIGNATURE_VERSION`    | `s3v4`                    |
| `gcs_project`             | `STORAGEKIT_GCS_PROJECT`             | from credentials          |
| `gcs_credentials_file`    | `STORAGEKIT_GCS_CREDENTIALS_FILE`    | Application Default Credentials |
| `azure_connection_string` | `STORAGEKIT_AZURE_CONNECTION_STRING` | -                         |
| `azure_account_url`       | `STORAGEKIT_AZURE_ACCOUNT_URL`       | -                         |
| `azure_credential`        | `STORAGEKIT_AZURE_CREDENTIAL`        | -                         |

The short names `BUCKET`, `TTL`, `CLOUD_ENDPOINT`, `ACCESS_TOKEN`, `API_KEY`, `REGION` and `SIGNATURE_VERSION` are read as fallbacks, so an older `.env` keeps working. Secrets are stored as `SecretStr`, so they do not appear in `repr()` or logs.

Notes:

- For AWS S3 set `s3_region` to a real region such as `us-east-1`; `auto` is for R2 and Filebase.
- `database_url` is any SQLAlchemy URL. For SQLite the path is relative to where your program runs, so use an absolute path in production, or Postgres (install a driver such as `psycopg`).

## API

```python
result = storage.save(source, filename=None, content_type=None, ttl_days=...)
```

- `source`: a path (`str`/`Path`), `bytes`, or a file opened with `"rb"`. `filename` is required for bytes and unnamed file objects.
- `ttl_days` overrides the config for this object; `None` means never expires.
- Returns an `UploadResult` (a `FileMetadata` plus `key`).

| Method                                    | Does                                                              |
| ----------------------------------------- | ----------------------------------------------------------------- |
| `storage.load(object_id)`                 | Whole file as `bytes`                                             |
| `storage.stream(object_id, chunk_size)`   | Iterator of `bytes` chunks, low memory                            |
| `storage.download(object_id, dest)`       | Write to a file or directory, atomically; returns the `Path`      |
| `storage.metadata(object_id)`             | `FileMetadata`, or `None` if unknown (no provider call)           |
| `storage.list_files(limit, offset)`       | `FileMetadata` for stored files, newest first                     |
| `storage.delete(object_id)`               | Delete from the provider, then metadata. `missing_ok=True` to ignore unknown ids |
| `storage.cleanup()`                       | Delete all expired objects now; returns the count                 |
| `storage.start_cleanup(interval=3600)`    | Daemon thread running `cleanup()` now and every `interval` seconds |
| `storage.stop_cleanup()` / `close()`      | Stop the thread / release resources. `with StorageService(...)` also works |

`load`, `stream` and `download` raise `ObjectExpiredError` for an object past its expiry that has not been cleaned up yet.

`FileMetadata` and `UploadResult` are frozen Pydantic models: `result.model_dump()` gives a dict, `result.model_dump_json()` gives JSON.

### Errors

All inherit from `StorageError`:

| Exception             | Meaning                                              |
| --------------------- | ---------------------------------------------------- |
| `ConfigError`         | Missing or invalid settings                          |
| `MetadataError`       | The metadata database failed                         |
| `ProviderError`       | S3, GCS or Azure rejected or failed a request        |
| `ObjectNotFoundError` | Unknown `object_id`                                  |
| `ObjectExpiredError`  | Subclass of the above; the TTL has passed            |

### Using a provider directly or adding your own

Providers implement the small `StorageProvider` contract (`upload`, `download_to`, `iter_chunks`, `delete`). Pass your own to the service:

```python
from storage import StorageService
from storage.providers import S3Provider

storage = StorageService(
    config, provider=S3Provider("my-bucket", client=my_boto3_client)
)
```

## Project layout

```
src/storage/
├── __init__.py         public exports
├── core.py             StorageService
├── cleanup.py          cleanup_expired + CleanupScheduler
├── common/             config, exceptions, Pydantic models, StorageProvider base
├── providers/          s3.py, gcs.py, azure_blob.py
└── metadata/           db.py (engine), models.py (ObjectRecord), repository.py
```

## Development and testing
 
Clone the repository and install it in editable mode with the test tools:
 
```bash
git clone https://github.com/om4144/storagekit.git
cd storagekit
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```
 
Run the checks:
 
```bash
pytest                                      # tests only
pytest --cov                                # tests with coverage
ruff format . && ruff check . && mypy       # format, lint, strict type check
```
 
Tests run against a mocked S3 (moto) and in-memory SQLite, so no credentials are needed. The GCS and Azure providers are tested with fake clients; they have not been run against the real services.
 
To try it against a real bucket, copy `.env.example` to `.env`, fill it in, and run:
 
```python
from storage import StorageService
 
with StorageService.from_env() as storage:
    result = storage.save(b"hello", filename="hello.txt")
    print(storage.load(result.object_id))
    storage.delete(result.object_id)
```
 
Run this from a directory where it is fine to create `metadata.db`. To keep the database in one place, set `STORAGEKIT_DATABASE_URL=sqlite:////absolute/path/metadata.db`.

## License

MIT. See [LICENSE](LICENSE).
