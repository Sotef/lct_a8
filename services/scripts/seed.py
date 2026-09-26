# -*- coding: utf-8 -*-
"""Служебный скрипт: создание таблиц, демо-пользователей и реестра моделей.

Запуск:  services\\.venv\\Scripts\\python.exe scripts\\seed.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models_db import ModelRegistry, User  # noqa: E402
from app.security import hash_password  # noqa: E402

ROLES = [
    # (username, password, role, full_name, district)
    ("central.operator", "central123", "central", "Центральный диспетчер ОДС", None),
    ("dispatcher.alpha", "alpha123", "dispatcher", "Диспетчер района Альфа", None),
    ("dispatcher.beta", "beta123", "dispatcher", "Диспетчер района Бета", None),
    ("tech.alpha", "tech123", "tech", "Техник района Альфа", "5122"),
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        for username, pwd, role, full, district in ROLES:
            if db.query(User).filter_by(username=username).first() is None:
                db.add(User(username=username, full_name=full, role=role,
                            district=district, password_hash=hash_password(pwd)))
        # реестр моделей (инфо; инференс читает активные артефакты напрямую)
        tasks = {"fire": "v0-2026-09-20", "access": "v0-2026-09-20",
                 "sensor": "v0-2026-09-20", "wear": "v0-2026-09-20"}
        for task, ver in tasks.items():
            if db.query(ModelRegistry).filter_by(task=task).first() is None:
                db.add(ModelRegistry(
                    task=task, version=ver,
                    model_path=str(config.MODELS_DIR / f"tte_{task}_discrete_hazard.cbm"),
                    calib_path=str(config.MODELS_DIR / f"calib30_{task}.pkl"),
                    z_stats_path=str(config.DATA_DIR / f"z_stats_{task}.csv"),
                    trained_on="<=2024-12-31", active=True,
                    metrics_json={"source": "research/final_metrics_v0.csv"}))
        db.commit()
        print("seed ok:", [u.username for u in db.query(User).all()])
    finally:
        db.close()


if __name__ == "__main__":
    main()