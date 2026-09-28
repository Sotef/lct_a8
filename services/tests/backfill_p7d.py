# -*- coding: utf-8 -*-
"""Одноразовое заполнение колонки predictions.p7d из сохранённых кривых S(t).

Колонка p7d добавлена позже (для раскраски графа и алертов), поэтому у прогнозов,
посчитанных раньше, она пустая. Скрипт досчитывает её из surv_points.

Запуск при остановленном сервисе:
  services\\.venv\\Scripts\\python.exe tests\\backfill_p7d.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from app import models_db as dbm  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402


def main() -> int:
    init_db()          # лёгкие миграции: колонка predictions.p7d добавляется здесь
    db = SessionLocal()
    total = 0
    try:
        q = (db.query(dbm.Prediction)
             .filter(dbm.Prediction.p7d.is_(None),
                     dbm.Prediction.surv_points.isnot(None)))
        n_all = q.count()
        print(f"прогнозов без p7d: {n_all}")
        batch = 5000
        while True:
            rows = q.limit(batch).all()
            if not rows:
                break
            for p in rows:
                sp = p.surv_points or []
                if len(sp) >= 6:
                    try:
                        p.p7d = round(1.0 - float(sp[5]), 6)
                    except (TypeError, ValueError):
                        continue
                else:
                    p.p7d = 0.0 if sp else None
            db.commit()
            total += len(rows)
            print(f"  обновлено {total}/{n_all}")
        print(f"готово: {total} записей")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
