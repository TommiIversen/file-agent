"""Alembic environment configuration for SQLite migrations.

Uses a synchronous SQLite engine for migrations to avoid the greenlet
dependency that SQLAlchemy's async engine requires.  This is safe because
Alembic is always invoked from a worker thread (via asyncio.to_thread)
in our application.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

# NOTE: We intentionally skip fileConfig() here because our app's logging
# is already configured by setup_logging() before migrations run.
# Calling fileConfig() would reset the root logger and remove all handlers.

target_metadata = None


def _sync_url() -> str:
    """Convert an async ``sqlite+aiosqlite:///…`` URL to plain ``sqlite:///…``."""
    url = config.get_main_option("sqlalchemy.url")
    if url and "+aiosqlite" in url:
        url = url.replace("+aiosqlite", "")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without connecting."""
    url = _sync_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a synchronous SQLite connection."""
    connectable = create_engine(
        _sync_url(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
