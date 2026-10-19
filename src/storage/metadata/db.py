"""Database engine creation and table setup."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, NoSuchModuleError, SQLAlchemyError
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from ..common.exceptions import MetadataError
from . import models  # noqa: F401  (importing registers the table with SQLModel)


def create_db_engine(
    url: str = "sqlite:///metadata.db", *, echo: bool = False
) -> Engine:
    """Create a SQLAlchemy engine for the metadata database.

    Any SQLAlchemy URL works (``postgresql+psycopg://...``; install the driver
    yourself). SQLite gets the settings needed to share it between threads, and
    ``sqlite://`` (in memory) uses a single shared connection so that all
    sessions see the same data.
    """
    kwargs: dict[str, Any] = {}
    try:
        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False}
            if parsed.database in (None, "", ":memory:"):
                kwargs["poolclass"] = StaticPool
        return create_engine(url, echo=echo, **kwargs)
    except (ArgumentError, NoSuchModuleError, ImportError) as e:
        raise MetadataError(f"Cannot create a database engine for {url!r}: {e}") from e


def init_db(engine: Engine) -> None:
    """Create the metadata tables if they do not exist yet. Safe to call repeatedly."""
    try:
        SQLModel.metadata.create_all(engine)
    except SQLAlchemyError as e:
        raise MetadataError(f"Cannot initialise the metadata database: {e}") from e
