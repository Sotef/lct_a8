# -*- coding: utf-8 -*-
"""Проверка восстановленных заявок: сколько их, какие статусы, видны ли диспетчеру."""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app import models_db as m  # noqa: E402
from app.database import SessionLocal  # noqa: E402

db = SessionLocal()
try:
    q = db.query(m.MaintenanceTask).filter(m.MaintenanceTask.score.is_(None))
    print("заявок без score (восстановленные из аудита):", q.count())
    print("по статусам:", db.query(m.MaintenanceTask.status, func.count())
          .filter(m.MaintenanceTask.score.is_(None))
          .group_by(m.MaintenanceTask.status).all())
    for t in q.limit(6).all():
        print(f"  #{t.id} {t.task:<7} ch={t.channel_id:<9} obj={t.object_id:<6} {t.status:<12} "
              f"{str(t.comment)[:60]}")
finally:
    db.close()
