# -*- coding: utf-8 -*-
"""Alembic env: URL берётся из app.config (поддержка SQLite dev / PostgreSQL prod)."""
from __future__ import annotations

import sys
import pathlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import config as app_config          # noqa: E402
from app.database import Base                 # noqa: E402
import app.models_db                         # noqa: E402,F401  (регистрирует модели)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", app_config.DATABASE_URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,
                          target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()