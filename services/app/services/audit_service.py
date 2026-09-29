# -*- coding: utf-8 -*-
"""Журнал действий пользователей (audit_log) — единая точка записи и чтения.

Каждая запись дополняется request_id и ip из контекста запроса (middleware)
и дублируется в системный лог (logger «audit»).
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from .. import models_db as dbm
from ..logging_setup import client_ip_var, log_event, request_id_var

log = logging.getLogger("audit")

# человекочитаемые названия действий (для UI)
ACTION_RU = {
    "auth.login": "вход в систему",
    "auth.login_failed": "неудачная попытка входа",
    "auth.logout": "выход из системы",
    "admin.create_user": "создание пользователя",
    "admin.set_user_active": "блокировка/разблокировка пользователя",
    "admin.data_load": "загрузка данных журнала",
    "admin.replay": "пересчёт истории прогнозов",
    "admin.models_reload": "перезагрузка моделей",
    "admin.bootstrap": "загрузка справочников",
    "admin.clock_reset": "перезапуск реплея (с января)",
    "admin.clock_pause": "пауза реплея",
    "admin.clock_resume": "возобновление реплея",
    "admin.clock_step": "ручной шаг реплея",
    "admin.clock_speed": "скорость демо-прокрута",
    "forecast.view": "просмотр карточки прогноза",
    "forecast.decision": "решение по прогнозу",
    "ticket.create": "создание заявки",
    "ticket.auto_generate": "автоформирование заявок",
    "ticket.status": "смена статуса заявки",
    "ticket.attachment": "вложение фото к заявке",
    "alert.push": "отправка push-уведомления",
    "incident.journal": "происшествие журнала СМВУ",
    "client.error": "ошибка веб-интерфейса",
}


def record(db: Session, action: str, user_id: int | None = None,
           entity_type: str | None = None, entity_id: str | int | None = None,
           detail: dict | None = None, commit: bool = True,
           level: int = logging.INFO) -> dbm.AuditLog:
    d = dict(detail or {})
    d.setdefault("ip", client_ip_var.get())
    d.setdefault("request_id", request_id_var.get())
    row = dbm.AuditLog(user_id=user_id, action=action, entity_type=entity_type,
                       entity_id=None if entity_id is None else str(entity_id),
                       detail=d)
    db.add(row)
    if commit:
        db.commit()
    log_event(log, level, f"{action} {entity_type or ''}:{entity_id or ''}".strip(),
              action=action, user_id=user_id, **{k: v for k, v in d.items()
                                                  if k not in ("ip", "request_id")})
    return row


def query(db: Session, action: str | None = None, user_id: int | None = None,
          entity_type: str | None = None, entity_id: str | None = None,
          q: str | None = None, since: dt.datetime | None = None,
          page: int = 1, size: int = 50) -> dict:
    base = db.query(dbm.AuditLog, dbm.User.username, dbm.User.role) \
        .outerjoin(dbm.User, dbm.User.id == dbm.AuditLog.user_id)
    if action:
        if action.endswith("*"):
            base = base.filter(dbm.AuditLog.action.like(action[:-1] + "%"))
        else:
            base = base.filter(dbm.AuditLog.action == action)
    if user_id is not None:
        base = base.filter(dbm.AuditLog.user_id == user_id)
    if entity_type:
        base = base.filter(dbm.AuditLog.entity_type == entity_type)
    if entity_id:
        base = base.filter(dbm.AuditLog.entity_id == str(entity_id))
    if since is not None:
        base = base.filter(dbm.AuditLog.created_at >= since)
    if q:
        like = f"%{q}%"
        base = base.filter((dbm.User.username.like(like)) |
                           (dbm.AuditLog.action.like(like)) |
                           (dbm.AuditLog.entity_id.like(like)))
    total = base.count()
    rows = (base.order_by(dbm.AuditLog.id.desc())
            .offset((page - 1) * size).limit(size).all())
    items = [{"id": a.id, "action": a.action,
              "action_ru": ACTION_RU.get(a.action, a.action),
              "user_id": a.user_id, "username": u, "role": r,
              "entity_type": a.entity_type, "entity_id": a.entity_id,
              "detail": a.detail or {},
              "created_at": a.created_at.isoformat() if a.created_at else None}
             for a, u, r in rows]
    return {"total": total, "page": page, "size": size, "items": items}


def stats(db: Session, hours: int = 24) -> dict:
    from sqlalchemy import func
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    rows = (db.query(dbm.AuditLog.action, func.count(dbm.AuditLog.id))
            .filter(dbm.AuditLog.created_at >= since)
            .group_by(dbm.AuditLog.action).all())
    return {"hours": hours,
            "by_action": [{"action": a, "action_ru": ACTION_RU.get(a, a), "n": n}
                          for a, n in sorted(rows, key=lambda x: -x[1])],
            "total": sum(n for _, n in rows)}
