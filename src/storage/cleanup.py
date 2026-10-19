"""Removal of expired objects, plus a small background scheduler."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from .common.base import StorageProvider
from .metadata.repository import MetadataRepository

logger = logging.getLogger("storage")


def cleanup_expired(
    provider: StorageProvider,
    repository: MetadataRepository,
    now: datetime | None = None,
) -> int:
    """Delete every expired object from the provider, then its metadata row.

    A failure on one object is logged and does not stop the others; its row is
    kept so the next run retries it. Returns how many objects were removed.
    """
    removed = 0
    for record in repository.list_expired(now or datetime.now(timezone.utc)):
        try:
            provider.delete(record.key)
            repository.delete(record.object_id)
            removed += 1
        except Exception:
            logger.exception("Cleanup failed for %s", record.object_id)
    return removed


class CleanupScheduler:
    """Run ``task`` immediately and then every ``interval`` seconds in a daemon thread.

    The scheduler lives inside your process. If you run several processes
    against the same database, run it in only one of them.
    """

    def __init__(self, task: Callable[[], object], interval: float = 3600) -> None:
        self._task = task
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="storage-cleanup", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._task()
            except Exception:
                logger.exception("Error during cleanup cycle")
            self._stop.wait(self._interval)
