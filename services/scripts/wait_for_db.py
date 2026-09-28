# -*- coding: utf-8 -*-
"""Ожидание готовности БД для контейнера (docker-entrypoint.sh).

Читает DATABASE_URL, повторяет подключение до DB_WAIT_RETRIES раз по 2 секунды.
Для SQLite ничего не делает. Код возврата 0 — БД доступна, 1 — не дождались.
"""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine


def main() -> int:
    url = os.getenv("DATABASE_URL", "")
    if not url or url.startswith("sqlite"):
        return 0
    retries = int(os.getenv("DB_WAIT_RETRIES", "45"))
    engine = create_engine(url, pool_pre_ping=True)
    for i in range(1, retries + 1):
        try:
            with engine.connect():
                pass
            print(f"[wait_for_db] БД доступна (попытка {i})", flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001
            if i == 1 or i % 5 == 0:
                print(f"[wait_for_db] попытка {i}/{retries}: {type(exc).__name__}",
                      flush=True)
            time.sleep(2)
    print("[wait_for_db] не дождались готовности БД", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
