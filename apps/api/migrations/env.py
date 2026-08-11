from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from cofield.adapters.persistence.schema import metadata

target_metadata = metadata


def _url() -> str:
    return os.environ.get("COFIELD_DATABASE_URL") or context.get_x_argument(
        as_dictionary=True
    ).get("url", "postgresql+psycopg://cofield:cofield@localhost:5432/cofield")


def run_migrations_online() -> None:
    engine = create_engine(_url(), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
