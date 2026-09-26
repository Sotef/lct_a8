# -*- coding: utf-8 -*-
"""Полный демо-цикл: БД -> справочники -> журнал (потоково) -> прогнозы -> сводка.

Запуск:  services\\.venv\\Scripts\\python.exe scripts\\run_demo.py [--limit N] [--recompute-panel]
Опции:
  --limit N             читать только первые N строк журнала (быстрый тест)
  --recompute-panel     пересобрать 6ч панели из кэша сырых бакетов
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts import seed  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app import models_db as dbm  # noqa: E402
from app.workers import ingestion  # noqa: E402
from app.services import object_service  # noqa: E402
from app.api.admin import _materialize_l2  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--recompute-panel", action="store_true")
    ap.add_argument("--no-ingest", action="store_true", help="пропустить чтение журнала")
    args = ap.parse_args()

    init_db()
    seed.main()
    db = SessionLocal()
    try:
        print("[1] справочники объектов/каналов...")
        refs = object_service.load_references_into_db(db)
        print("    refs:", refs)
        n_l2 = _materialize_l2(db)
        print("    object_risk_l2:", n_l2)

        if not args.no_ingest:
            print("[2] потоковый ингвест журнала 2026...")
            stat = ingestion.ingest_journal(db, year="2026", limit_rows=args.limit)
            print("    ingest:", stat)
        else:
            print("[2] пропущен (--no-ingest)")

        print("[3] прогнозный цикл (все задачи, бакет = максимум данных)...")
        res = ingestion.run_prediction_cycle(db, recompute_panel=args.recompute_panel)
        print("    bucket:", res["bucket"])
        for task, r in res["results"].items():
            print(f"    {task}: {r.get('n_subjects', r)}")

        print("[4] статистика БД:")
        for task in ("fire", "access", "sensor", "wear"):
            n = db.query(dbm.Prediction).filter_by(task=task).count()
            print(f"    predictions[{task}]: {n}")
        print("    users:", db.query(dbm.User).count(),
              "| objects_ref:", db.query(dbm.ObjectRef).count(),
              "| channels_ref:", db.query(dbm.ChannelRef).count())
    finally:
        db.close()


if __name__ == "__main__":
    main()