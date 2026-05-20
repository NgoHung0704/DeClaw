"""Alembic environment for DeClaw.

The DB URL is taken from ``declaw.config.Settings`` (or the
``DECLAW_DB_URL`` env var if the caller wants to override it, e.g. tests)
so users never edit ``alembic.ini`` by hand.

Migrations run synchronously — schema operations don't need async and the
sync driver keeps Alembic simple. Runtime app code still uses aiosqlite.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context

# Import models so they register on ``SQLModel.metadata`` before autogenerate
# inspects it. Without these imports, autogenerate sees an empty metadata.
from declaw.config import get_settings
from declaw.db import models  # noqa: F401  (registers tables on SQLModel.metadata)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    override = os.environ.get("DECLAW_DB_URL")
    if override:
        return override
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_path = settings.data_dir / "declaw.db"
    return f"sqlite:///{db_path.as_posix()}"


config.set_main_option("sqlalchemy.url", _resolve_url())

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a DB."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-friendly ALTERs
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Open a real DB connection and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
