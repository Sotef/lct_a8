# -*- coding: utf-8 -*-
"""Разовый анализ журнала аудита: какие данные о заявках/решениях сохранились.

Нужен, чтобы понять, можно ли восстановить заявки, удалённые прежней логикой
перезапуска реплея (журнал аудита никогда не удалялся).

Запуск:  services\\.venv\\Scripts\\python.exe tests\\inspect_audit_tickets.py
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import func

sys.path.insert(0, ".")
from app import models_db as m  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    db = SessionLocal()
    try:
        cnt = (db.query(m.AuditLog.action, func.count(m.AuditLog.id))
               .group_by(m.AuditLog.action).order_by(func.count(m.AuditLog.id).desc()).all())
        print("действия в аудите:")
        for a, n in cnt:
            print(f"  {a:<28} {n}")
        for action in ("ticket.create", "ticket.status", "forecast.decision"):
            rows = (db.query(m.AuditLog).filter(m.AuditLog.action == action)
                    .order_by(m.AuditLog.id.asc()).limit(3).all())
            print(f"\nпримеры {action}:")
            for r in rows:
                print("  ", r.id, str(r.created_at)[:19], r.entity_id,
                      json.dumps(r.detail or {}, ensure_ascii=False)[:220])
        # сколько уникальных каналов фигурирует в истории заявок
        chans = set()
        for (d,) in db.query(m.AuditLog.detail).filter(m.AuditLog.action == "ticket.create").all():
            if isinstance(d, dict) and d.get("channel_id"):
                chans.add((d.get("task"), d["channel_id"]))
        print(f"\nканалов в ticket.create: {len(chans)}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
