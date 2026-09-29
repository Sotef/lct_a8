# -*- coding: utf-8 -*-
"""SQLAlchemy-движок/сессии. Работает с PostgreSQL 12+ и SQLite (dev fallback)."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = config.DATABASE_URL
    kwargs = {"echo": config.DB_ECHO, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": config.SQLITE_RETRIES}
        engine = create_engine(url, **kwargs)
        # включаем WAL для конкурентного доступа нескольких воркеров
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=%d" % (config.SQLITE_RETRIES * 1000))
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = int(__import__("os").environ.get("DB_POOL_SIZE", "10"))
        kwargs["max_overflow"] = 10
        engine = create_engine(url, **kwargs)
    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Создаёт таблицы + лёгкие миграции (MVP; в проде — alembic upgrade head)."""
    from . import models_db  # noqa: F401  (регистрирует модели)
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """ALTER TABLE для колонок, добавленных после создания БД (SQLite/PG)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    migrations = {
        "predictions": {"p72": "FLOAT", "p7d": "FLOAT", "pinned": "INTEGER DEFAULT 0",
                        "age_days": "FLOAT", "norm_due": "TIMESTAMP",
                        "campaign": "INTEGER DEFAULT 0", "plan_date": "TIMESTAMP"},
        "maintenance_tasks": {"prediction_id": "INTEGER", "source": "VARCHAR(20)",
                              "priority": "VARCHAR(10)", "comment": "TEXT",
                              "scheduled_at": "TIMESTAMP", "updated_at": "TIMESTAMP",
                              "age_days": "FLOAT", "norm_due": "TIMESTAMP",
                              "rationale": "TEXT"},
    }
    with engine.begin() as conn:
        for table, cols in migrations.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()